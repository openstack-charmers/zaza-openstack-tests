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
import yaml
import zaza

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.utilities.juju


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
        if not zaza.model.get_relation_id(
                self.application_name, 'nrpe',
                remote_interface_name='nrpe-external-master'):
            self.skipTest('The NRPE charm is not related to the '
                          'charm under test.')
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

    def test_prefer_chassis_as_gw(self):
        """Confirm effect of prefer-chassis-as-gw configuration option."""
        expected_key = 'external-ids:ovn-cms-options'
        expected_value = 'enable-chassis-as-gw'
        with self.config_change(
                {}, {'prefer-chassis-as-gw': True},
                reset_to_charm_default=True):
            for unit in zaza.model.get_units(self.application_name):
                self.assertEqual(
                    zaza.model.run_on_unit(
                        unit.entity_id,
                        'ovs-vsctl get open-vswitch . {}'.format(expected_key)
                    )['Stdout'].rstrip(),
                    expected_value)
                logging.info(
                    '{}: "{}" set to "{}"'
                    .format(unit.entity_id, expected_key, expected_value))
        logging.info('Config restored, checking things went back to normal')
        for unit in zaza.model.get_units(self.application_name):
            self.assertEqual(
                zaza.model.run_on_unit(
                    unit.entity_id,
                    'ovs-vsctl get open-vswitch . '
                    'external-ids:ovn-cms-options')['Code'],
                '1')
            logging.info(
                '{}: "{}" no longer present'
                .format(unit.entity_id, expected_key))

    def test_wrong_bridge_config(self):
        """Confirm that ovn-chassis units block with wrong bridge config."""
        stored_target_deploy_status = self.test_config.get(
            'target_deploy_status', {})
        new_target_deploy_status = stored_target_deploy_status.copy()
        new_target_deploy_status[self.application_name] = {
            'workload-status': 'blocked',
            'workload-status-message': 'Wrong format',
        }
        if 'target_deploy_status' in self.test_config:
            self.test_config['target_deploy_status'].update(
                new_target_deploy_status)
        else:
            self.test_config['target_deploy_status'] = new_target_deploy_status

        with self.config_change(
                self.config_current(
                    application_name=self.application_name,
                    keys=['bridge-interface-mappings']),
                {'bridge-interface-mappings': 'incorrect'}):
            logging.info('Charm went into blocked state as expected, restore '
                         'configuration')
            self.test_config[
                'target_deploy_status'] = stored_target_deploy_status


class DPDKTest(test_utils.BaseCharmTest):
    """DPDK-related tests."""

    def _openvswitch_switch_dpdk_installed(self):
        """Assert that the openvswitch-switch-dpdk package is installed.

        :raises: zaza.model.CommandRunFailed
        """
        cmd = 'dpkg-query -s openvswitch-switch-dpdk'
        for unit in zaza.model.get_units(self.application_name):
            zaza.utilities.juju.remote_run(
                unit.name, cmd, model_name=self.model_name, fatal=True)

    def _ovs_dpdk_init_configured(self):
        """Assert that DPDK is configured.

        :raises: AssertionError, zaza.model.CommandRunFailed
        """
        cmd = 'ovs-vsctl get open-vswitch . other_config:dpdk-init'
        for unit in zaza.model.get_units(self.application_name):
            result = zaza.utilities.juju.remote_run(
                unit.name,
                cmd,
                model_name=self.model_name,
                fatal=True).rstrip()
            assert result == '"true"', (
                'DPDK not configured on {}'.format(unit.name))

    def _ovs_dpdk_initialized(self):
        """Assert that OVS successfully initialized DPDK.

        :raises: AssertionError, zaza.model.CommandRunFailed
        """
        cmd = 'ovs-vsctl get open-vswitch . dpdk_initialized'
        for unit in zaza.model.get_units(self.application_name):
            result = zaza.utilities.juju.remote_run(
                unit.name,
                cmd,
                model_name=self.model_name,
                fatal=True).rstrip()
            assert result == 'true', (
                'DPDK not initialized on {}'.format(unit.name))

    def _ovs_br_ex_port_is_system_interface(self):
        """Assert br-ex bridge is created and has system port in it.

        :raises: zaza.model.CommandRunFailed
        """
        cmd = ('ip link show dev $(ovs-vsctl --bare --columns name '
               'find port external_ids:charm-ovn-chassis=br-ex)')
        for unit in zaza.model.get_units(self.application_name):
            zaza.utilities.juju.remote_run(
                unit.name, cmd, model_name=self.model_name, fatal=True)

    def _ovs_br_ex_port_is_dpdk_interface(self):
        """Assert br-ex bridge is created and has DPDK port in it.

        :raises: zaza.model.CommandRunFailed
        """
        cmd = (
            'dpdk-devbind.py --status-dev net '
            '| grep ^$(ovs-vsctl --bare --columns options '
            'find interface external_ids:charm-ovn-chassis=br-ex '
            '|cut -f2 -d=)'
            '|grep "drv=vfio-pci unused=$"')
        for unit in zaza.model.get_units(self.application_name):
            zaza.utilities.juju.remote_run(
                unit.name, cmd, model_name=self.model_name, fatal=True)

    def _ovs_br_ex_interface_not_in_error(self):
        """Assert br-ex bridge is created and interface is not in error.

        :raises: AssertionError, zaza.model.CommandRunFailed
        """
        cmd = (
            'ovs-vsctl --bare --columns error '
            'find interface external_ids:charm-ovn-chassis=br-ex')
        for unit in zaza.model.get_units(self.application_name):
            result = zaza.utilities.juju.remote_run(
                unit.name,
                cmd,
                model_name=self.model_name,
                fatal=True).rstrip()
            assert result == '', result

    def _dpdk_pre_post_flight_check(self):
        """Assert state of the system before and after enable/disable DPDK."""
        with self.assertRaises(
                zaza.model.CommandRunFailed,
                msg='openvswitch-switch-dpdk unexpectedly installed'):
            self._openvswitch_switch_dpdk_installed()
        with self.assertRaises(
                zaza.model.CommandRunFailed,
                msg='OVS unexpectedly configured for DPDK'):
            self._ovs_dpdk_init_configured()
        with self.assertRaises(
                AssertionError,
                msg='OVS unexpectedly has DPDK initialized'):
            self._ovs_dpdk_initialized()

    def test_enable_dpdk(self):
        """Confirm that transitioning to/from DPDK works."""
        logging.info('Pre-flight check')
        self._dpdk_pre_post_flight_check()
        self._ovs_br_ex_port_is_system_interface()

        self.enable_hugepages_vfio_on_hvs_in_vms(4)
        with self.config_change(
                {
                    'enable-dpdk': False,
                    'dpdk-driver': '',
                },
                {
                    'enable-dpdk': True,
                    'dpdk-driver': 'vfio-pci',
                },
                application_name='ovn-chassis'):
            logging.info('Checking openvswitch-switch-dpdk is installed')
            self._openvswitch_switch_dpdk_installed()
            logging.info('Checking DPDK is configured in OVS')
            self._ovs_dpdk_init_configured()
            logging.info('Checking DPDK is successfully initialized in OVS')
            self._ovs_dpdk_initialized()
            logging.info('Checking that br-ex configed with DPDK interface...')
            self._ovs_br_ex_port_is_dpdk_interface()
            logging.info('and is not in error.')
            self._ovs_br_ex_interface_not_in_error()

        logging.info('Post-flight check')
        self._dpdk_pre_post_flight_check()

        self.disable_hugepages_vfio_on_hvs_in_vms()
        self._ovs_br_ex_port_is_system_interface()


class OVSOVNMigrationTest(test_utils.BaseCharmTest):
    """OVS to OVN migration tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for OVN migration tests."""
        super(OVSOVNMigrationTest, cls).setUpClass()

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

            # NOTE(lourot): usually in this scenario, the test bundle has been
            # originally deployed with a non-related neutron-api-plugin-ovn
            # subordinate application, and thus Zaza has been taught to expect
            # initially no unit from this application. We are now relating it
            # to a principal neutron-api application with one unit. Thus we now
            # need to make sure we wait for one unit from this subordinate
            # before proceeding:
            target_deploy_status = self.test_config.get('target_deploy_status',
                                                        {})
            try:
                target_deploy_status['neutron-api-plugin-ovn'][
                    'num-expected-units'] = 1
            except KeyError:
                # num-expected-units wasn't set to 0, no expectation to be
                # fixed, let's move on.
                pass

            zaza.model.wait_for_application_states(
                states=target_deploy_status)

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
        zaza.model.block_until_all_units_idle()
        zaza.model.wait_for_application_states(
            states=self.target_deploy_status)


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


class OVNDedicatedChassisDeferredRestartTest(
        test_utils.BaseDeferredRestartTest):
    """Deferred restart tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for deferred restart tests."""
        super().setUpClass(application_name='ovn-dedicated-chassis')

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
        new_value = str(not app_config['disable-mlockall'].get('value', False))
        return 'disable-mlockall', new_value


class OVNCentralDeferredRestartTest(
        test_utils.BaseDeferredRestartTest):
    """Deferred restart tests for OVN Central."""

    @classmethod
    def setUpClass(cls):
        """Run setup for deferred restart tests."""
        super().setUpClass(application_name='ovn-central')

    def run_tests(self):
        """Run deferred restart tests."""
        # Charm does not defer hooks so that test is not included.
        # Trigger a package change which requires a restart
        self.run_package_change_test(
            'ovn-central',
            'ovn-central')


class OVNCentralDownscaleTests(test_utils.BaseCharmTest):
    """Tests for cluster-status and cluster-kick actions."""

    SB_CMD = "ovn-appctl -t /var/run/ovn/ovnsb_db.ctl {}"
    NB_CMD = "ovn-appctl -t /var/run/ovn/ovnnb_db.ctl {}"

    def _cluster_status_action(self):
        """Return Southbound and Northbound cluster status.

        This function returns data as reported by "cluster-status" action
        parsed into two dictionaries in the following order:
        "Southbound status", "Northbound status"
        """
        yaml_load_err = "Status of '{}' could not be loaded as yaml:\n{}"
        status_raw = zaza.model.run_action_on_leader("ovn-central",
                                                     "cluster-status")
        status_data = status_raw.data["results"]
        # Verify expected items in the action result
        self.assertIn("ovnnb", status_data)
        self.assertIn("ovnsb", status_data)

        try:
            nb_status = yaml.safe_load(status_data["ovnnb"])
        except yaml.YAMLError:
            self.fail(yaml_load_err.format("northbound-cluster",
                                           status_data["ovnnb"]))
        try:
            sb_status = yaml.safe_load(status_data["ovnsb"])
        except yaml.YAMLError:
            self.fail(yaml_load_err.format("southbound-cluster",
                                           status_data["ovnsb"]))

        return sb_status, nb_status

    @staticmethod
    def _add_unit(number_of_units=1):
        """Add specified number of units to ovn-central application.

        This function also waits until the application reaches active state.
        """
        zaza.model.add_unit(
            "ovn-central",
            count=number_of_units,
            wait_appear=True
        )
        zaza.model.wait_for_application_states()

    @staticmethod
    def _remove_unit(unit_name):
        """Remove specified unit from ovn-central application.

        This function also waits until the application reaches active state
        again.
        """
        zaza.model.destroy_unit("ovn-central", unit_name)
        zaza.model.block_until_all_units_idle()
        zaza.model.wait_for_application_states()

    def _assert_servers_cleanly_removed(self, sb_id, nb_id):
        """Assert that specified members were removed from cluster.

        This checks that they are no longer listed in cluster_status
        and that there are no missing server.
        :param sb_id: ID of a Southbound server that should no longer be
            present
        :type sb_id: str
        :param nb_id: ID of a Northbound server that should no longer be
            present
        :type nb_id: str
        """
        sb_status, nb_status = self._cluster_status_action()

        self.assertNotIn(sb_id, sb_status["unit_map"])
        self.assertNotIn("UNKNOWN", sb_status["unit_map"])
        self.assertNotIn(nb_id, nb_status["unit_map"])
        self.assertNotIn("UNKNOWN", nb_status["unit_map"])

    def _get_server_ids(self, unit_name):
        """Return SB and NB server id belonging to the servers on the unit.

        :return: Southbound and Northbound IDs (in this order)
        :rtype: str, str
        """
        missing_unit_err = ("Failed to find Server IDs. Unit {} is already"
                            " missing from the {} cluster status")
        sb_status, nb_status = self._cluster_status_action()

        for unit, server_id in sb_status["unit_map"].items():
            if unit_name == unit:
                sb_id = server_id
                break
        else:
            self.fail(missing_unit_err.format(unit_name, "Southbound"))

        for unit, server_id in nb_status["unit_map"].items():
            if unit_name == unit:
                nb_id = server_id
                break
        else:
            self.fail(missing_unit_err.format(unit_name, "Northbound"))

        return sb_id, nb_id

    def _get_unit_hosting_ovn(self, leader):
        """Return ID of a unit with at least one OVN server leader/follower.

        :param leader: If `True`, this method returns ID of a unit that host
            at least one leader. Otherwise, the ID of a unit hosting at least
            one follower will be returned.
        :type leader: bool
        :return: ID of a unit hosting OVN leader/follower (based on the
            `leader` param)
        :rtype: str
        """
        # It's sufficient to parse only one of the cluster statuses To
        # determine if unit holds at least one leader or one follower.
        cluster_status, _ = self._cluster_status_action()
        leader_id = cluster_status["leader"]
        if leader_id == "self":
            leader_id = cluster_status["server_id"][:4]

        for unit_id, server_id in cluster_status["unit_map"].items():
            if (server_id == leader_id) == leader:
                return unit_id
        else:
            self.fail("Test failed to locate unit that hosts OVN leader.")

    def test_cluster_status(self):
        """Test that cluster-status action returns expected results."""
        application = zaza.model.get_application("ovn-central")
        sb_status, nb_status = self._cluster_status_action()

        # Verify that cluster status includes "unit_map" field with correct
        # type
        for status in (nb_status, sb_status):
            self.assertIn("unit_map", status)
            self.assertIsInstance(status["unit_map"], dict)

        # Verify that units and their Server IDs are properly paired
        expected_mapping = {}
        for unit in application.units:
            unit_name = unit.entity_id
            nb_status_cmd = self.NB_CMD.format("cluster/status OVN_Northbound")
            sb_status_cmd = self.SB_CMD.format("cluster/status OVN_Southbound")
            nb_cluster_status = zaza.model.run_on_unit(unit_name,
                                                       nb_status_cmd)
            sb_cluster_status = zaza.model.run_on_unit(unit_name,
                                                       sb_status_cmd)
            nb_id = nb_cluster_status["Stdout"].splitlines()[0]
            sb_id = sb_cluster_status["Stdout"].splitlines()[0]
            expected_mapping[unit_name] = {"sb_id": sb_id, "nb_id": nb_id}

        for unit_name, unit_data in expected_mapping.items():
            sb_id = unit_data["sb_id"]
            nb_id = unit_data["nb_id"]
            self.assertEqual(sb_status["unit_map"][unit_name], sb_id)
            self.assertEqual(nb_status["unit_map"][unit_name], nb_id)

    def test_cluster_kick(self):
        """Test forcefully removing a member of an ovn cluster.

        If unit fails to remove itself gracefully from the
        Southbound/Northbound OVN clusters, it can be kicked using
        "cluster-kick" action. This test simulates such scenario by removing
        contents of "/var/run/ovn/*" to mess with OVN communication before
        removal of the unit which prevents the unit from gracefully leaving
        the OVN cluster.
        """
        logging.info("Add a ovn-central unit to be kicked")
        self._add_unit()
        application = zaza.model.get_application("ovn-central")
        removed_unit = application.units[-1].entity_id
        removed_sb_id, removed_nb_id = self._get_server_ids(removed_unit)

        logging.info("Killing OVN services on %s unit" % removed_unit)
        zaza.model.run_on_unit(removed_unit, "rm -rf /var/run/ovn/*")

        logging.info("Removing unit %s", removed_unit)
        self._remove_unit(removed_unit)

        # Verify that Server IDs of the removed unit are no longer associated
        # with the units ID and show in "UNKNOWN" instead
        sb_status, nb_status = self._cluster_status_action()

        self.assertNotIn(removed_sb_id, sb_status["unit_map"])
        self.assertIn(removed_sb_id, sb_status["unit_map"]["UNKNOWN"])
        self.assertNotIn(removed_nb_id, nb_status["unit_map"])
        self.assertIn(removed_nb_id, nb_status["unit_map"]["UNKNOWN"])

        logging.info("Requesting kick of removed servers (Southbound ID: %s, "
                     "Northbound ID: %s) from OVN clusters",
                     removed_sb_id,
                     removed_nb_id)
        action_params = {"sb-server-id": removed_sb_id,
                         "nb-server-id": removed_nb_id,
                         "i-really-mean-it": True}
        zaza.model.run_action_on_leader("ovn-central",
                                        "cluster-kick",
                                        action_params=action_params)

        # Verify that Server IDs of the removed unit are completely removed
        # from the cluster status
        self._assert_servers_cleanly_removed(removed_sb_id, removed_nb_id)

    def test_cluster_downscale(self):
        """Test unit's graceful departure from OVN cluster.

        When ovn-central unit is removed. It should automatically leave from
        OVN clusters (Northbound and Southbound) as well.
        """
        logging.info("Adding units needed for downscaling test.")
        self._add_unit(2)

        # Remove unit hosting at least one follower
        non_leader_unit = self._get_unit_hosting_ovn(leader=False)
        logging.info(
            "Removing unit (%s) that hosts OVN follower server.",
            non_leader_unit
        )

        non_leader_sb, non_leader_nb = self._get_server_ids(non_leader_unit)
        self._remove_unit(non_leader_unit)
        self._assert_servers_cleanly_removed(non_leader_sb, non_leader_nb)

        # Remove unit hosting at least one leader
        leader_unit = self._get_unit_hosting_ovn(leader=True)
        logging.info(
            "Removing unit (%s) that hosts OVN leader server.",
            leader_unit
        )

        leader_sb, leader_nb = self._get_server_ids(leader_unit)
        self._remove_unit(leader_unit)
        self._assert_servers_cleanly_removed(leader_sb, leader_nb)
