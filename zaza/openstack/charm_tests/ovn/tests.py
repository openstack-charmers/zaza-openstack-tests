# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Encapsulate OVN testing."""

import logging

import juju

import tenacity

import zaza

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.utilities.openstack as openstack_utils


class BaseCharmOperationTest(test_utils.BaseCharmTest):
    """Base OVN Charm operation tests."""

    # override if not possible to determine release pair from charm under test
    release_application = None

    @classmethod
    def setUpClass(cls):
        """Run class setup for OVN charm operation tests."""
        super(BaseCharmOperationTest, cls).setUpClass()
        cls.services = ['NotImplemented']  # This must be overridden
        cls.nrpe_checks = ['NotImplemented']  # This must be overridden
        cls.current_release = openstack_utils.get_os_release(
            openstack_utils.get_current_os_release_pair(
                cls.release_application or cls.application_name))

    @tenacity.retry(
        retry=tenacity.retry_if_result(lambda ret: ret is not None),
        # sleep for 2mins to allow 1min cron job to run...
        wait=tenacity.wait_fixed(120),
        stop=tenacity.stop_after_attempt(2))
    def _retry_check_commands_on_units(self, cmds, units):
        return generic_utils.check_commands_on_units(cmds, units)

    def test_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped, then resume and check
        they are started.
        """
        with self.pause_resume(self.services):
            logging.info('Testing pause resume (services="{}")'
                         .format(self.services))

    def test_nrpe_configured(self):
        """Confirm that the NRPE service check files are created."""
        units = zaza.model.get_units(self.application_name)
        cmds = []
        for check_name in self.nrpe_checks:
            cmds.append(
                'egrep -oh /usr/local.* /etc/nagios/nrpe.d/'
                'check_{}.cfg'.format(check_name)
            )
        ret = self._retry_check_commands_on_units(cmds, units)
        if ret:
            logging.info(ret)
        self.assertIsNone(ret, msg=ret)


class CentralCharmOperationTest(BaseCharmOperationTest):
    """OVN Central Charm operation tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for OVN Central charm operation tests."""
        super(CentralCharmOperationTest, cls).setUpClass()
        cls.services = [
            'ovn-northd',
            'ovsdb-server',
        ]
        source = zaza.model.get_application_config(
            cls.application_name)['source']['value']
        logging.info(source)
        if 'train' in source:
            cls.nrpe_checks = [
                'ovn-northd',
                'ovn-nb-ovsdb',
                'ovn-sb-ovsdb',
            ]
        else:
            # Ussuri or later (distro or cloudarchive)
            cls.nrpe_checks = [
                'ovn-northd',
                'ovn-ovsdb-server-sb',
                'ovn-ovsdb-server-nb',
            ]


class ChassisCharmOperationTest(BaseCharmOperationTest):
    """OVN Chassis Charm operation tests."""

    release_application = 'ovn-central'

    @classmethod
    def setUpClass(cls):
        """Run class setup for OVN Chassis charm operation tests."""
        super(ChassisCharmOperationTest, cls).setUpClass()
        cls.services = [
            'ovn-controller',
        ]
        if cls.application_name == 'ovn-chassis':
            principal_app_name = 'magpie'
        else:
            principal_app_name = cls.application_name
        source = zaza.model.get_application_config(
            principal_app_name)['source']['value']
        logging.info(source)
        if 'train' in source:
            cls.nrpe_checks = [
                'ovn-host',
                'ovs-vswitchd',
                'ovsdb-server',
            ]
        else:
            # Ussuri or later (distro or cloudarchive)
            cls.nrpe_checks = [
                'ovn-controller',
                'ovsdb-server',
                'ovs-vswitchd',
            ]


class OVSOVNMigrationTest(test_utils.BaseCharmTest):
    """OVS to OVN migration tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for OVN migration tests."""
        super(OVSOVNMigrationTest, cls).setUpClass()
        cls.current_release = openstack_utils.get_os_release(
            openstack_utils.get_current_os_release_pair())

    def setUp(self):
        """Perform migration steps prior to validation."""
        super(OVSOVNMigrationTest, self).setUp()
        # These steps are here due to them having to be executed once and in a
        # specific order prior to running any tests. The steps should still
        # be idempotent if at all possible as a courtesy to anyone iterating
        # on the test code.
        try:
            if self.one_time_init_done:
                logging.debug('Skipping migration steps as they have already '
                              'run.')
                return
        except AttributeError:
            logging.info('Performing migration steps.')

        # as we progress through the steps our target deploy status changes
        # store it in the class instance so the individual methods can
        # update when appropriate.
        self.target_deploy_status = self.test_config.get(
            'target_deploy_status', {})

        # Stop Neutron agents on hypervisors
        self._pause_units('neutron-openvswitch')
        try:
            self._pause_units('neutron-gateway')
        except KeyError:
            logging.info(
                'No neutron-gateway in deployment, skip pausing it.')

        # Add the neutron-api-plugin-ovn subordinate which will make the
        # `neutron-api-plugin-ovn` unit appear in the deployment.
        #
        # NOTE: The OVN drivers will not be activated until we change the
        # value for the `manage-neutron-plugin-legacy-mode` config.
        self._add_neutron_api_plugin_ovn_subordinate_relation()

        # Adjust MTU on overlay networks
        #
        # Prior to this the end user will already have lowered the MTU on their
        # running instances through the use of the `instance-mtu` configuration
        # option and manual reconfiguration of instances that do not use DHCP.
        #
        # We update the value for the MTU on the overlay networks at this point
        # in time because:
        #
        # - Agents are paused and will not actually reconfigure the networks.
        #
        # - Making changes to non-Geneve networks are prohibited as soon as the
        #   OVN drivers are activated.
        #
        # - Get the correct MTU value into the OVN database on first sync.
        #
        #   - This will be particularly important for any instances using
        #     stateless IPv6 autoconfiguration (SLAAC) as there is currently
        #     no config knob to feed MTU information into the legacy ML2+OVS
        #     `radvd` configuration or the native OVN RA.
        #
        #   - Said instances will reconfigure their IPv6 MTU as soon as they
        #     receive an RA with correct MTU when OVN takes over control.
        self._run_migrate_mtu_action()

        # Flip `manage-neutron-plugin-legacy-mode` to enable it
        #
        # NOTE(fnordahl): until we sync/repair the OVN DB this will make the
        # `neutron-server` log errors. However we need the neutron unit to be
        # unpaused while doing this to have the configuration rendered. The
        # configuration is consumed by the `neutron-ovn-db-sync` tool.
        self._configure_neutron_api()

        # Stop the Neutron server prior to OVN DB sync/repair
        self._pause_units('neutron-api')

        # Sync the OVN DB
        self._run_migrate_ovn_db_action()
        # Perform the optional morphing of Neutron DB action
        self._run_offline_neutron_morph_db_action()
        self._resume_units('neutron-api')

        # Run `cleanup` action on neutron-openvswitch units/hypervisors
        self._run_cleanup_action('neutron-openvswitch')
        # Run `cleanup` action on neutron-gateway units when present
        try:
            self._run_cleanup_action('neutron-gateway')
        except KeyError:
            logging.info(
                'No neutron-gateway in deployment, skip cleanup of it.')

        # Start the OVN controller on hypervisors
        #
        # NOTE(fnordahl): it is very important to have run cleanup prior to
        # starting these, if you don't do that it is almost guaranteed that
        # you will program the network to a state of infinite loop.
        self._resume_units('ovn-chassis')

        try:
            self._resume_units('ovn-dedicated-chassis')
        except KeyError:
            logging.info(
                'No ovn-dedicated-chassis in deployment, skip resume.')

        # And we should be off to the races

        self.one_time_init_done = True

    def _add_neutron_api_plugin_ovn_subordinate_relation(self):
        """Add relation between neutron-api and neutron-api-plugin-ovn."""
        try:
            logging.info('Adding relation neutron-api-plugin-ovn '
                         '-> neutron-api')
            zaza.model.add_relation(
                'neutron-api-plugin-ovn', 'neutron-plugin',
                'neutron-api:neutron-plugin-api-subordinate')
            zaza.model.wait_for_agent_status()
            zaza.model.wait_for_application_states(
                states=self.test_config.get('target_deploy_status', {}))
        except juju.errors.JujuAPIError:
            # we were not able to add the relation, let's make sure it's
            # because it's already there
            assert (zaza.model.get_relation_id(
                'neutron-api-plugin-ovn', 'neutron-api',
                remote_interface_name='neutron-plugin-api-subordinate')
                is not None), 'Unable to add relation required for test'
            logging.info('--> On the other hand, did not need to add the '
                         'relation as it was already there.')

    def _configure_neutron_api(self):
        """Set configuration option `manage-neutron-plugin-legacy-mode`."""
        logging.info('Configuring `manage-neutron-plugin-legacy-mode` for '
                     'neutron-api...')
        n_api_config = {
            'manage-neutron-plugin-legacy-mode': False,
        }
        with self.config_change(
                n_api_config, n_api_config, 'neutron-api'):
            logging.info('done')

    def _run_offline_neutron_morph_db_action(self):
        """Run offline-neutron-morph-db action."""
        logging.info('Running the optional `offline-neutron-morph-db` action '
                     'on neutron-api-plugin-ovn/leader')
        generic_utils.assertActionRanOK(
            zaza.model.run_action_on_leader(
                'neutron-api-plugin-ovn',
                'offline-neutron-morph-db',
                action_params={
                    'i-really-mean-it': True},
                raise_on_failure=True,
            )
        )

    def _run_migrate_ovn_db_action(self):
        """Run migrate-ovn-db action."""
        logging.info('Running `migrate-ovn-db` action on '
                     'neutron-api-plugin-ovn/leader')
        generic_utils.assertActionRanOK(
            zaza.model.run_action_on_leader(
                'neutron-api-plugin-ovn',
                'migrate-ovn-db',
                action_params={
                    'i-really-mean-it': True},
                raise_on_failure=True,
            )
        )

    # Charm readiness is no guarantee for API being ready to serve requests.
    # https://bugs.launchpad.net/charm-neutron-api/+bug/1854518
    @tenacity.retry(wait=tenacity.wait_exponential(min=5, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(3))
    def _run_migrate_mtu_action(self):
        """Run migrate-mtu action with retry.

        The action is idempotent.

        Due to LP: #1854518 and the point in time of the test life cycle we run
        this action the probability for the Neutron API not being available
        for the script to do its job is high, thus we retry.
        """
        logging.info('Running `migrate-mtu` action on '
                     'neutron-api-plugin-ovn/leader')
        generic_utils.assertActionRanOK(
            zaza.model.run_action_on_leader(
                'neutron-api-plugin-ovn',
                'migrate-mtu',
                action_params={
                    'i-really-mean-it': True},
                raise_on_failure=True,
            )
        )

    def _pause_units(self, application):
        """Pause units of application.

        :param application: Name of application
        :type application: str
        """
        logging.info('Pausing {} units'.format(application))
        zaza.model.run_action_on_units(
            [unit.entity_id
                for unit in zaza.model.get_units(application)],
            'pause',
            raise_on_failure=True,
        )
        self.target_deploy_status.update(
            {
                application: {
                    'workload-status': 'maintenance',
                    'workload-status-message': 'Paused',
                },
            },
        )

    def _run_cleanup_action(self, application):
        """Run cleanup action on application units.

        :param application: Name of application
        :type application: str
        """
        logging.info('Running `cleanup` action on {} units.'
                     .format(application))
        zaza.model.run_action_on_units(
            [unit.entity_id
                for unit in zaza.model.get_units(application)],
            'cleanup',
            action_params={
                'i-really-mean-it': True},
            raise_on_failure=True,
        )

    def _resume_units(self, application):
        """Resume units of application.

        :param application: Name of application
        :type application: str
        """
        logging.info('Resuming {} units'.format(application))
        zaza.model.run_action_on_units(
            [unit.entity_id
                for unit in zaza.model.get_units(application)],
            'resume',
            raise_on_failure=True,
        )
        self.target_deploy_status.pop(application)

    def test_ovs_ovn_migration(self):
        """Test migration of existing Neutron ML2+OVS deployment to OVN.

        The test should be run after deployment and validation of a legacy
        deployment combined with subsequent run of a network connectivity test
        on instances created prior to the migration.
        """
        # The setUp method of this test class will perform the migration steps.
        # The tests.yaml is programmed to do further validation after the
        # migration.

        # Reset the n-gw and n-ovs instance-mtu configuration option so it does
        # not influence how further tests are executed.
        reset_config_keys = ['instance-mtu']
        for app in ('neutron-gateway', 'neutron-openvswitch'):
            try:
                zaza.model.reset_application_config(app, reset_config_keys)
                logging.info('Reset configuration to default on "{}" for "{}"'
                             .format(app, reset_config_keys))
            except KeyError:
                pass
        zaza.model.wait_for_agent_status()
        zaza.model.wait_for_application_states(
            states=self.target_deploy_status)
        # Workaround for our old friend LP: #1852221 which hit us again on
        # Groovy. We make the os_release check explicit so that we can
        # re-evaluate the need for the workaround at the next release.
        if self.current_release == openstack_utils.get_os_release(
                'groovy_victoria'):
            try:
                for application in ('ovn-chassis', 'ovn-dedicated-chassis'):
                    for unit in zaza.model.get_units(application):
                        zaza.model.run_on_unit(
                            unit.entity_id,
                            'systemctl restart ovs-vswitchd')
            except KeyError:
                # One of the applications is not in the model, which is fine
                pass


class OVNChassisDeferredRestartTest(test_utils.BaseDeferredRestartTest):
    """Deferred restart tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for deferred restart tests."""
        super().setUpClass(application_name='ovn-chassis')

    def run_tests(self):
        """Run deferred restart tests."""
        # Trigger a config change which triggers a deferred hook.
        self.run_charm_change_hook_test('configure_ovs')

        # Trigger a package change which requires a restart
        self.run_package_change_test(
            'openvswitch-switch',
            'openvswitch-switch')

    def get_new_config(self):
        """Return the config key and new value to trigger a hook execution.

        :returns: Config key and new value
        :rtype: (str, bool)
        """
        app_config = zaza.model.get_application_config(self.application_name)
        return 'enable-sriov', str(not app_config['enable-sriov']['value'])
