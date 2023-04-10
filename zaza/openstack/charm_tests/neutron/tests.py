#!/usr/bin/env python3

# Copyright 2018 Canonical Ltd.
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

"""Encapsulating testing of some `neutron-*` charms.

`neutron-api`, `neutron-gateway` and `neutron-openvswitch`
"""


import copy
import logging
import tenacity

from neutronclient.common import exceptions as neutronexceptions

import yaml
import zaza
import zaza.openstack.charm_tests.neutron.setup as neutron_setup
import zaza.openstack.charm_tests.nova.utils as nova_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.configure.guest as guest
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.tempest.tests as tempest_tests
import zaza.utilities.machine_os


class NeutronPluginApiSharedTests(test_utils.OpenStackBaseTest):
    """Shared tests for Neutron Plugin API Charms."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Neutron Openvswitch tests."""
        super(NeutronPluginApiSharedTests, cls).setUpClass()

        cls.current_os_release = openstack_utils.get_os_release()
        cls.bionic_stein = openstack_utils.get_os_release('bionic_stein')
        cls.trusty_mitaka = openstack_utils.get_os_release('trusty_mitaka')

        if cls.current_os_release >= cls.bionic_stein:
            cls.pgrep_full = True
        else:
            cls.pgrep_full = False

    def test_211_ovs_use_veth(self):
        """Verify proper handling of ovs-use-veth setting."""
        current_release = openstack_utils.get_os_release()
        xenial_mitaka = openstack_utils.get_os_release('xenial_mitaka')
        if current_release < xenial_mitaka:
            logging.info(
                "Skipping OVS use veth test. ovs_use_veth is always True on "
                "Trusty.")
            return
        conf_file = "/etc/neutron/dhcp_agent.ini"
        expected = {"DEFAULT": {"ovs_use_veth": ["False"]}}
        test_config = zaza.charm_lifecycle.utils.get_charm_config(fatal=False)
        states = test_config.get("target_deploy_status", {})
        alt_states = copy.deepcopy(states)
        alt_states[self.application_name] = {
            "workload-status": "blocked",
            "workload-status-message":
                "Mismatched existing and configured ovs-use-veth. See log."}

        if "neutron-openvswitch" in self.application_name:
            logging.info("Turning on DHCP and metadata")
            zaza.model.set_application_config(
                self.application_name,
                {"enable-local-dhcp-and-metadata": "True"})
            zaza.model.wait_for_application_states(states=states)

        logging.info("Check for expected default ovs-use-veth setting of "
                     "False")
        zaza.model.block_until_oslo_config_entries_match(
            self.application_name,
            conf_file,
            expected,
        )
        logging.info("Setting conflicting ovs-use-veth to True")
        zaza.model.set_application_config(
            self.application_name,
            {"ovs-use-veth": "True"})
        logging.info("Wait to go into a blocked workload status")
        zaza.model.wait_for_application_states(states=alt_states)
        # Check the value stayed the same
        logging.info("Check that the value of ovs-use-veth setting "
                     "remained False")
        zaza.model.block_until_oslo_config_entries_match(
            self.application_name,
            conf_file,
            expected,
        )
        logging.info("Setting ovs-use-veth to match existing.")
        zaza.model.set_application_config(
            self.application_name,
            {"ovs-use-veth": "False"})
        logging.info("Wait to go into unit ready workload status")
        zaza.model.wait_for_application_states(states=states)


class NeutronGatewayTest(NeutronPluginApiSharedTests):
    """Test basic Neutron Gateway Charm functionality."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Neutron Gateway tests."""
        super(NeutronGatewayTest, cls).setUpClass()
        cls.services = cls._get_services()

        # set up clients
        cls.neutron_client = (
            openstack_utils.get_neutron_session_client(cls.keystone_session))

    _APP_NAME = 'neutron-gateway'

    def test_401_enable_qos(self):
        """Check qos settings set via neutron-api charm."""
        logging.info('running qos check')

        qos_enabled = zaza.model.get_application_config(
            'neutron-api')['enable-qos']['value']

        if qos_enabled is True:
            logging.info('qos already enabled, not running enable-qos '
                         'test')
            return

        with self.config_change(
                {'enable-qos': False},
                {'enable-qos': True},
                application_name="neutron-api"):

            self._validate_openvswitch_agent_qos()

    @tenacity.retry(wait=tenacity.wait_exponential(min=5, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(8))
    def _validate_openvswitch_agent_qos(self):
        """Validate that the qos extension is enabled in the ovs agent."""
        # obtain the dhcp agent to identify the neutron-gateway host
        dhcp_agent = self.neutron_client.list_agents(
            binary='neutron-dhcp-agent')['agents'][0]
        neutron_gw_host = dhcp_agent['host']
        logging.debug('neutron gw host: {}'.format(neutron_gw_host))

        # check extensions on the ovs agent to validate qos
        ovs_agent = self.neutron_client.list_agents(
            binary='neutron-openvswitch-agent',
            host=neutron_gw_host)['agents'][0]

        self.assertIn('qos', ovs_agent['configurations']['extensions'])

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        current_value = zaza.model.get_application_config(
            self._APP_NAME)['debug']['value']
        new_value = str(not bool(current_value)).title()
        current_value = str(current_value).title()

        set_default = {'debug': current_value}
        set_alternate = {'debug': new_value}
        default_entry = {'DEFAULT': {'debug': [current_value]}}
        alternate_entry = {'DEFAULT': {'debug': [new_value]}}

        # Config file affected by juju set config change
        conf_file = '/etc/neutron/neutron.conf'

        # Make config change, check for service restarts
        logging.info(
            'Setting verbose on {} {}'.format(self._APP_NAME, set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            self.services,
            pgrep_full=self.pgrep_full)

    def test_910_pause_and_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(
                self.services,
                pgrep_full=self.pgrep_full):
            logging.info("Testing pause resume")

    def test_920_change_aa_profile(self):
        """Test changing the Apparmor profile mode."""
        services = ['neutron-openvswitch-agent',
                    'neutron-dhcp-agent',
                    'neutron-l3-agent',
                    'neutron-metadata-agent',
                    'neutron-metering-agent']

        set_default = {'aa-profile-mode': 'disable'}
        set_alternate = {'aa-profile-mode': 'complain'}

        mtime = zaza.model.get_unit_time(
            self.lead_unit,
            model_name=self.model_name)
        logging.debug('Remote unit timestamp {}'.format(mtime))

        with self.config_change(set_default, set_alternate):
            for unit in zaza.model.get_units(self._APP_NAME,
                                             model_name=self.model_name):
                logging.info('Checking number of profiles in complain '
                             'mode in {}'.format(unit.entity_id))
                run = zaza.model.run_on_unit(
                    unit.entity_id,
                    'aa-status --complaining',
                    model_name=self.model_name)
                output = run['Stdout']
                self.assertTrue(int(output) >= len(services))

    @classmethod
    def _get_services(cls):
        """
        Return the services expected in Neutron Gateway.

        :returns: A list of services
        :rtype: list[str]
        """
        services = ['neutron-dhcp-agent',
                    'neutron-metadata-agent',
                    'neutron-metering-agent',
                    'neutron-openvswitch-agent']

        trusty_icehouse = openstack_utils.get_os_release('trusty_icehouse')
        xenial_newton = openstack_utils.get_os_release('xenial_newton')
        bionic_train = openstack_utils.get_os_release('bionic_train')

        if cls.current_os_release <= trusty_icehouse:
            services.append('neutron-vpn-agent')
        if cls.current_os_release < xenial_newton:
            services.append('neutron-lbaas-agent')
        if xenial_newton <= cls.current_os_release < bionic_train:
            services.append('neutron-lbaasv2-agent')

        return services


class NeutronGatewayShowActionsTest(test_utils.OpenStackBaseTest):
    """Test "show" actions of Neutron Gateway Charm.

    actions:
      * show-routers
      * show-dhcp-networks
      * show-loadbalancers
    """

    SKIP_LBAAS_TESTS = True

    @classmethod
    def setUpClass(cls, application_name='neutron-gateway', model_alias=None):
        """Run class setup for running Neutron Gateway tests."""
        super(NeutronGatewayShowActionsTest, cls).setUpClass(
            application_name, model_alias)
        # set up clients
        cls.neutron_client = (
            openstack_utils.get_neutron_session_client(cls.keystone_session))

        # Loadbalancer tests not supported on Train and above and on
        # releases Mitaka and below
        current = openstack_utils.get_os_release()
        bionic_train = openstack_utils.get_os_release('bionic_train')
        xenial_mitaka = openstack_utils.get_os_release('xenial_mitaka')
        cls.SKIP_LBAAS_TESTS = not (xenial_mitaka > current < bionic_train)

    def _assert_result_match(self, action_result, resource_list,
                             resource_name):
        """Assert that action_result contains same data as resource_list."""
        # make sure that action completed successfully
        if action_result.status != 'completed':
            self.fail('Juju Action failed: {}'.format(action_result.message))

        # extract data from juju action
        action_data = action_result.data.get('results', {}).get(resource_name)
        resources_from_action = yaml.safe_load(action_data)

        # pull resource IDs from expected resource list and juju action data
        expected_resource_ids = {resource['id'] for resource in resource_list}
        result_resource_ids = resources_from_action.keys()

        # assert that juju action returned expected resources
        self.assertEqual(result_resource_ids, expected_resource_ids)

    def test_show_routers(self):
        """Test that show-routers action reports correct neutron routers."""
        # fetch neutron routers using neutron client
        ngw_unit = zaza.model.get_units(self.application_name,
                                        model_name=self.model_name)[0]
        routers_from_client = self.neutron_client.list_routers().get(
            'routers', [])

        if not routers_from_client:
            self.fail('At least one router must be configured for this test '
                      'to pass.')

        # fetch neutron routers using juju-action
        result = zaza.model.run_action(ngw_unit.entity_id,
                                       'show-routers',
                                       model_name=self.model_name)

        # assert that data from neutron client match data from juju action
        self._assert_result_match(result, routers_from_client, 'router-list')

    def test_show_dhcp_networks(self):
        """Test that show-dhcp-networks reports correct DHCP networks."""
        # fetch DHCP networks using neutron client
        ngw_unit = zaza.model.get_units(self.application_name,
                                        model_name=self.model_name)[0]
        networks_from_client = self.neutron_client.list_networks().get(
            'networks', [])

        if not networks_from_client:
            self.fail('At least one network must be configured for this test '
                      'to pass.')

        # fetch DHCP networks using juju-action
        result = zaza.model.run_action(ngw_unit.entity_id,
                                       'show-dhcp-networks',
                                       model_name=self.model_name)

        # assert that data from neutron client match data from juju action
        self._assert_result_match(result, networks_from_client,
                                  'dhcp-networks')

    def test_show_load_balancers(self):
        """Test that show-loadbalancers reports correct loadbalancers."""
        if self.SKIP_LBAAS_TESTS:
            self.skipTest('LBaasV2 is not supported in this version.')

        loadbalancer_id = None

        try:
            # create LBaasV2 for the purpose of this test
            lbaas_name = 'test_lbaas'
            subnet_list = self.neutron_client.list_subnets(
                name='private_subnet').get('subnets', [])

            if not subnet_list:
                raise RuntimeError('Expected subnet "private_subnet" is not '
                                   'configured.')

            subnet = subnet_list[0]
            loadbalancer_data = {'loadbalancer': {'name': lbaas_name,
                                                  'vip_subnet_id': subnet['id']
                                                  }
                                 }
            loadbalancer = self.neutron_client.create_loadbalancer(
                body=loadbalancer_data)
            loadbalancer_id = loadbalancer['loadbalancer']['id']

            # test that client and action report same data
            ngw_unit = zaza.model.get_units(self.application_name,
                                            model_name=self.model_name)[0]
            lbaas_from_client = self.neutron_client.list_loadbalancers().get(
                'loadbalancers', [])

            result = zaza.model.run_action(ngw_unit.entity_id,
                                           'show-load-balancers',
                                           model_name=self.model_name)

            self._assert_result_match(result, lbaas_from_client,
                                      'load-balancers')
        finally:
            if loadbalancer_id:
                self.neutron_client.delete_loadbalancer(loadbalancer_id)


class NeutronCreateNetworkTest(test_utils.OpenStackBaseTest):
    """Test creating a Neutron network through the API.

    This is broken out into a separate class as it can be useful as standalone
    tests for Neutron plugin subordinate charms.
    """

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Neutron Gateway tests."""
        super(NeutronCreateNetworkTest, cls).setUpClass()
        cls.current_os_release = openstack_utils.get_os_release()

        # set up clients
        cls.neutron_client = (
            openstack_utils.get_neutron_session_client(cls.keystone_session))
        cls.neutron_client.format = 'json'

    _TEST_NET_NAME = 'test_net'

    def test_400_create_network(self):
        """Create a network, verify that it exists, and then delete it."""
        self._wait_for_neutron_ready()
        self._assert_test_network_doesnt_exist()
        self._create_test_network()
        net_id = self._assert_test_network_exists_and_return_id()
        self._delete_test_network(net_id)
        self._assert_test_network_doesnt_exist()

    @classmethod
    def _wait_for_neutron_ready(cls):
        logging.info('Waiting for Neutron to become ready...')
        zaza.model.wait_for_application_states()
        for attempt in tenacity.Retrying(
                wait=tenacity.wait_fixed(5),  # seconds
                stop=tenacity.stop_after_attempt(12),
                reraise=True):
            with attempt:
                cls.neutron_client.list_networks()

    def _create_test_network(self):
        logging.info('Creating neutron network...')
        network = {'name': self._TEST_NET_NAME}
        self.neutron_client.create_network({'network': network})

    def _delete_test_network(self, net_id):
        logging.info('Deleting neutron network...')
        self.neutron_client.delete_network(net_id)

    def _assert_test_network_exists_and_return_id(self):
        logging.debug('Confirming new neutron network...')
        networks = self.neutron_client.list_networks(name=self._TEST_NET_NAME)
        logging.debug('Networks: {}'.format(networks))
        net_len = len(networks['networks'])
        assert net_len == 1, (
            "Expected 1 network, found {}".format(net_len))
        network = networks['networks'][0]
        assert network['name'] == self._TEST_NET_NAME, \
            "network {} not found".format(self._TEST_NET_NAME)
        return network['id']

    def _assert_test_network_doesnt_exist(self):
        networks = self.neutron_client.list_networks(name=self._TEST_NET_NAME)
        net_count = len(networks['networks'])
        assert net_count == 0, (
            "Expected zero networks, found {}".format(net_count))


class NeutronApiTest(NeutronCreateNetworkTest):
    """Test basic Neutron API Charm functionality."""

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        current_value = zaza.model.get_application_config(
            'neutron-api')['debug']['value']
        new_value = str(not bool(current_value)).title()
        current_value = str(current_value).title()

        set_default = {'debug': current_value}
        set_alternate = {'debug': new_value}
        default_entry = {'DEFAULT': {'debug': [current_value]}}
        alternate_entry = {'DEFAULT': {'debug': [new_value]}}

        # Config file affected by juju set config change
        conf_file = '/etc/neutron/neutron.conf'

        # Make config change, check for service restarts
        logging.info(
            'Setting verbose on neutron-api {}'.format(set_alternate))
        bionic_stein = openstack_utils.get_os_release('bionic_stein')
        if openstack_utils.get_os_release() >= bionic_stein:
            pgrep_full = True
        else:
            pgrep_full = False
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            ['neutron-server'],
            pgrep_full=pgrep_full)

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(
                ["/usr/bin/neutron-server",
                 "/usr/sbin/apache2",
                 "/usr/sbin/haproxy"],
                pgrep_full=True):
            logging.info("Testing pause resume")


class SecurityTest(test_utils.OpenStackBaseTest):
    """Neutron Security Tests."""

    def test_security_checklist(self):
        """Verify expected state with security-checklist."""
        expected_failures = []
        expected_passes = [
            'validate-file-ownership',
            'validate-file-permissions',
        ]
        expected_to_pass = True

        # override settings depending on application name so we can reuse
        # the class for multiple charms
        if self.application_name == 'neutron-api':
            tls_checks = [
                'validate-uses-tls-for-keystone',
            ]

            expected_failures = [
                'validate-enables-tls',  # LP: #1851610
            ]

            expected_passes.append('validate-uses-keystone')

            if zaza.model.get_relation_id(
                    'neutron-api',
                    'vault',
                    remote_interface_name='certificates'):
                expected_passes.extend(tls_checks)
            else:
                expected_failures.extend(tls_checks)

            expected_to_pass = False

        for unit in zaza.model.get_units(self.application_name,
                                         model_name=self.model_name):
            logging.info('Running `security-checklist` action'
                         ' on  unit {}'.format(unit.entity_id))
            test_utils.audit_assertions(
                zaza.model.run_action(
                    unit.entity_id,
                    'security-checklist',
                    model_name=self.model_name,
                    action_params={}),
                expected_passes,
                expected_failures,
                expected_to_pass=expected_to_pass)


class NeutronOpenvSwitchTest(NeutronPluginApiSharedTests):
    """Test basic Neutron Openvswitch Charm functionality."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Neutron Openvswitch tests."""
        super(NeutronOpenvSwitchTest, cls).setUpClass()

        # set up client
        cls.neutron_client = (
            openstack_utils.get_neutron_session_client(cls.keystone_session))

    def test_101_neutron_sriov_config(self):
        """Verify data in the sriov agent config file."""
        xenial_mitaka = openstack_utils.get_os_release('xenial_mitaka')
        if self.current_os_release < xenial_mitaka:
            logging.debug('Skipping test, sriov agent not supported on < '
                          'xenial/mitaka')
            return

        zaza.model.set_application_config(
            self.application_name,
            {'enable-sriov': 'True'})

        zaza.model.wait_for_agent_status()
        zaza.model.wait_for_application_states()

        self._check_settings_in_config(
            self.application_name,
            'sriov-device-mappings',
            'physical_device_mappings',
            ['', 'physnet42:eth42'],
            'sriov_nic',
            '/etc/neutron/plugins/ml2/sriov_agent.ini')

        # the CI environment does not expose an actual SR-IOV NIC to the
        # functional tests. consequently the neutron-sriov agent will not
        # run, and the charm will update its status as such. this will prevent
        # the success of pause/resume test.
        #
        # disable sriov after validation of config file is complete.
        logging.info('Disabling SR-IOV after verifying config file data...')

        zaza.model.set_application_config(
            self.application_name,
            {'enable-sriov': 'False'})

        logging.info('Waiting for config-changes to complete...')
        zaza.model.wait_for_agent_status()
        zaza.model.wait_for_application_states()

        logging.debug('OK')

    def _check_settings_in_config(self, service, charm_key,
                                  config_file_key, vpair,
                                  section, conf_file):

        set_default = {charm_key: vpair[0]}
        set_alternate = {charm_key: vpair[1]}
        app_name = service

        expected = {
            section: {
                config_file_key: [str(vpair[1])],
            },
        }

        with self.config_change(set_default,
                                set_alternate,
                                application_name=app_name):
            zaza.model.block_until_oslo_config_entries_match(
                self.application_name,
                conf_file,
                expected,
            )
        logging.debug('OK')

    def test_201_l2pop_propagation(self):
        """Verify that l2pop setting propagates to neutron-ovs."""
        self._check_settings_in_config(
            'neutron-api',
            'l2-population',
            'l2_population',
            [False, True],
            'agent',
            '/etc/neutron/plugins/ml2/openvswitch_agent.ini')

    def test_202_nettype_propagation(self):
        """Verify that nettype setting propagates to neutron-ovs."""
        self._check_settings_in_config(
            'neutron-api',
            'overlay-network-type',
            'tunnel_types',
            ['vxlan', 'gre'],
            'agent',
            '/etc/neutron/plugins/ml2/openvswitch_agent.ini')

    def test_301_secgroup_propagation_local_override(self):
        """Verify disable-security-groups overrides what neutron-api says."""
        if self.current_os_release >= self.trusty_mitaka:
            conf_file = "/etc/neutron/plugins/ml2/openvswitch_agent.ini"
        else:
            conf_file = "/etc/neutron/plugins/ml2/ml2_conf.ini"

        with self.config_change(
                {'neutron-security-groups': False},
                {'neutron-security-groups': True},
                application_name='neutron-api'):
            with self.config_change(
                    {'disable-security-groups': False},
                    {'disable-security-groups': True}):
                zaza.model.block_until_oslo_config_entries_match(
                    self.application_name,
                    conf_file,
                    {'securitygroup': {'enable_security_group': ['False']}})

    def test_401_restart_on_config_change(self):
        """Verify that the specified services are restarted.

        When the config is changed we need to make sure that the services are
        restarted.
        """
        self.restart_on_changed(
            '/etc/neutron/neutron.conf',
            {'debug': False},
            {'debug': True},
            {'DEFAULT': {'debug': ['False']}},
            {'DEFAULT': {'debug': ['True']}},
            ['neutron-openvswitch-agent'],
            pgrep_full=self.pgrep_full)

    def test_501_enable_qos(self):
        """Check qos settings set via neutron-api charm."""
        if self.current_os_release < self.trusty_mitaka:
            logging.debug('Skipping test')
            return

        set_default = {'enable-qos': False}
        set_alternate = {'enable-qos': True}
        app_name = 'neutron-api'

        conf_file = '/etc/neutron/plugins/ml2/openvswitch_agent.ini'
        expected = {
            'agent': {
                'extensions': ['qos'],
            },
        }

        with self.config_change(set_default,
                                set_alternate,
                                application_name=app_name):
            zaza.model.block_until_oslo_config_entries_match(
                self.application_name,
                conf_file,
                expected,
            )
        logging.debug('OK')

    def test_901_pause_and_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(['neutron-openvswitch-agent'],
                               pgrep_full=self.pgrep_full):
            logging.info('Testing pause resume')


class NeutronBridgePortMappingTest(NeutronPluginApiSharedTests):
    """Test correct handling of network-bridge-port mapping functionality."""

    def test_600_conflict_data_ext_ports(self):
        """Verify proper handling of conflict between data-port and ext-port.

        Configuring ext-port and data-port at the same time should make the
        charm to enter "blocked" state. After unsetting ext-port charm should
        be active again.
        """
        if self.application_name not in ["neutron-gateway",
                                         "neutron-openvswitch"]:
            logging.debug("Skipping test, charm under test is not "
                          "neutron-gateway or neutron-openvswitch")
            return

        current_data_port = zaza.model.get_application_config(
            self.application_name).get("data-port").get("value", "")
        current_ext_port = zaza.model.get_application_config(
            self.application_name).get("ext-port").get("value", "")
        logging.debug("Current data-port: '{}'".format(current_data_port))
        logging.debug("Current data-port: '{}'".format(current_ext_port))

        test_config = zaza.charm_lifecycle.utils.get_charm_config(
            fatal=False)
        current_state = test_config.get("target_deploy_status", {})
        blocked_state = copy.deepcopy(current_state)
        blocked_state[self.application_name] = {
            "workload-status": "blocked",
            "workload-status-message":
                "ext-port set when data-port set: see config.yaml"}

        logging.info("Setting conflicting ext-port and data-port options")
        zaza.model.set_application_config(
            self.application_name, {"data-port": "br-phynet43:eth43",
                                    "ext-port": "br-phynet43:eth43"})
        zaza.model.wait_for_application_states(states=blocked_state)

        # unset ext-port and wait for app state to return to active
        logging.info("Unsetting conflicting ext-port option")
        zaza.model.set_application_config(
            self.application_name, {"ext-port": ""})
        zaza.model.wait_for_application_states(states=current_state)

        # restore original config
        zaza.model.set_application_config(
            self.application_name, {'data-port': current_data_port,
                                    'ext-port': current_ext_port})
        zaza.model.wait_for_application_states(states=current_state)
        logging.info('OK')


class NeutronOvsVsctlTest(NeutronPluginApiSharedTests):
    """Test 'ovs-vsctl'-related functionality on Neutron charms."""

    def test_800_ovs_bridges_are_managed_by_us(self):
        """Checking OVS bridges' external-id.

        OVS bridges created by us should be marked as managed by us in their
        external-id. See
        http://docs.openvswitch.org/en/latest/topics/integration/
        """
        for unit in zaza.model.get_units(self.application_name,
                                         model_name=self.model_name):
            for bridge_name in ('br-int', 'br-ex'):
                logging.info(
                    'Checking that the bridge {}:{}'.format(
                        unit.name, bridge_name
                    ) + ' is marked as managed by us'
                )
                expected_external_id = 'charm-{}=managed'.format(
                    self.application_name)
                actual_external_id = zaza.model.run_on_unit(
                    unit.entity_id,
                    'ovs-vsctl br-get-external-id {}'.format(bridge_name),
                    model_name=self.model_name
                )['Stdout'].strip()
                self.assertEqual(actual_external_id, expected_external_id)


def router_address_from_subnet(subnet):
    """Retrieve router address from subnet."""
    return subnet['gateway_ip']


class NeutronNetworkingBase(test_utils.OpenStackBaseTest):
    """Base for checking openstack instances have valid networking."""

    RESOURCE_PREFIX = 'zaza-neutrontests'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Neutron API Networking tests."""
        super(NeutronNetworkingBase, cls).setUpClass(
            application_name='neutron-api')
        cls.neutron_client = (
            openstack_utils.get_neutron_session_client(cls.keystone_session))

        cls.project_subnet = cls.neutron_client.find_resource(
            'subnet',
            neutron_setup.OVERCLOUD_NETWORK_CONFIG['project_subnet_name'])
        cls.external_subnet = cls.neutron_client.find_resource(
            'subnet',
            neutron_setup.OVERCLOUD_NETWORK_CONFIG['external_subnet_name'])

        # Override this if you want your test to attach instances directly to
        # the external provider network
        cls.attach_to_external_network = False

        # Override this if you want your test to launch instances with a
        # specific flavor
        cls.instance_flavor = None

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(8))
    def validate_instance_can_reach_other(self,
                                          instance_1,
                                          instance_2,
                                          verify,
                                          mtu=None):
        """
        Validate that an instance can reach a fixed and floating of another.

        :param instance_1: The instance to check networking from
        :type instance_1: nova_client.Server

        :param instance_2: The instance to check networking from
        :type instance_2: nova_client.Server

        :param verify: callback to verify result
        :type verify: callable

        :param mtu: Check that we can send non-fragmented packets of given size
        :type mtu: Optional[int]
        """
        if not self.attach_to_external_network:
            floating_1 = floating_ips_from_instance(instance_1)[0]
            floating_2 = floating_ips_from_instance(instance_2)[0]
        address_1 = fixed_ips_from_instance(instance_1)[0]
        address_2 = fixed_ips_from_instance(instance_2)[0]

        username = guest.boot_tests['bionic']['username']
        password = guest.boot_tests['bionic'].get('password')
        privkey = openstack_utils.get_private_key(nova_utils.KEYPAIR_NAME)

        cmds = [
            'ping -c 1',
        ]
        if mtu:
            # the on-wire packet will be 28 bytes larger than the value
            # provided to ping(8) -s parameter
            packetsize = mtu - 28
            cmds.append(
                'ping -M do -s {} -c 1'.format(packetsize))

        for cmd in cmds:
            if self.attach_to_external_network:
                openstack_utils.ssh_command(
                    username, address_1, 'instance-1',
                    '{} {}'.format(cmd, address_2),
                    password=password, privkey=privkey, verify=verify)
            else:
                openstack_utils.ssh_command(
                    username, floating_1, 'instance-1',
                    '{} {}'.format(cmd, address_2),
                    password=password, privkey=privkey, verify=verify)

                openstack_utils.ssh_command(
                    username, floating_1, 'instance-1',
                    '{} {}'.format(cmd, floating_2),
                    password=password, privkey=privkey, verify=verify)

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(8))
    def validate_instance_can_reach_router(self, instance, verify, mtu=None):
        """
        Validate that an instance can reach it's primary gateway.

        :param instance: The instance to check networking from
        :type instance: nova_client.Server

        :param verify: callback to verify result
        :type verify: callable

        :param mtu: Check that we can send non-fragmented packets of given size
        :type mtu: Optional[int]
        """
        if self.attach_to_external_network:
            router = router_address_from_subnet(self.external_subnet)
            address = fixed_ips_from_instance(instance)[0]
        else:
            router = router_address_from_subnet(self.project_subnet)
            address = floating_ips_from_instance(instance)[0]

        username = guest.boot_tests['bionic']['username']
        password = guest.boot_tests['bionic'].get('password')
        privkey = openstack_utils.get_private_key(nova_utils.KEYPAIR_NAME)

        cmds = [
            'ping -c 1',
        ]
        if mtu:
            # the on-wire packet will be 28 bytes larger than the value
            # provided to ping(8) -s parameter
            packetsize = mtu - 28
            cmds.append(
                'ping -M do -s {} -c 1'.format(packetsize))

        for cmd in cmds:
            openstack_utils.ssh_command(
                username, address, 'instance', '{} {}'.format(cmd, router),
                password=password, privkey=privkey, verify=verify)

    @tenacity.retry(wait=tenacity.wait_exponential(min=5, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(8),
                    retry=tenacity.retry_if_exception_type(AssertionError))
    def check_server_state(self, nova_client, state, server_id=None,
                           server_name=None):
        """Wait for server to reach desired state.

        :param nova_client: Nova client to use when checking status
        :type nova_client: nova client
        :param state: Target state for server
        :type state: str
        :param server_id: UUID of server to check
        :type server_id: str
        :param server_name: Name of server to check
        :type server_name: str
        :raises: AssertionError
        """
        if server_name:
            server_id = nova_client.servers.find(name=server_name).id
        server = nova_client.servers.find(id=server_id)
        assert server.status == state

    @tenacity.retry(wait=tenacity.wait_exponential(min=5, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(8),
                    retry=tenacity.retry_if_exception_type(AssertionError))
    def check_neutron_agent_up(self, neutron_client, host_name):
        """Wait for agents to come up.

        :param neutron_client: Neutron client to use when checking status
        :type neutron_client: neutron client
        :param host_name: The name of the host whose agents need checking
        :type host_name: str
        :raises: AssertionError
        """
        for agent in neutron_client.list_agents()['agents']:
            if agent['host'] == host_name:
                assert agent['admin_state_up']
                assert agent['alive']

    def effective_network_mtu(self, network_name):
        """Retrieve effective MTU for a network.

        If the `instance-mtu` configuration option is set to a value lower than
        the network MTU this method will return the value of that. Otherwise
        Neutron's value for MTU on a network will be returned.

        :param network_name: Name of network to query
        :type network_name: str
        :returns: MTU for network
        :rtype: int
        """
        cfg_instance_mtu = None
        for app in ('neutron-gateway', 'neutron-openvswitch'):
            try:
                cfg = zaza.model.get_application_config(app)
                cfg_instance_mtu = int(cfg['instance-mtu']['value'])
                break
            except KeyError:
                pass

        networks = self.neutron_client.show_network('', name=network_name)
        network_mtu = int(next(iter(networks['networks']))['mtu'])

        if cfg_instance_mtu and cfg_instance_mtu < network_mtu:
            logging.info('Using MTU from application "{}" config: {}'
                         .format(app, cfg_instance_mtu))
            return cfg_instance_mtu
        else:
            logging.info('Using MTU from network "{}": {}'
                         .format(network_name, network_mtu))
            return network_mtu

    def check_connectivity(self, instance_1, instance_2):
        """Run North/South and East/West connectivity tests."""
        def verify(stdin, stdout, stderr):
            """Validate that the SSH command exited 0."""
            self.assertEqual(stdout.channel.recv_exit_status(), 0)

        try:
            mtu_1 = self.effective_network_mtu(
                network_name_from_instance(instance_1))
            mtu_2 = self.effective_network_mtu(
                network_name_from_instance(instance_2))
            mtu_min = min(mtu_1, mtu_2)
        except neutronexceptions.NotFound:
            # Older versions of OpenStack cannot look up network by name, just
            # skip the check if that is the case.
            mtu_1 = mtu_2 = mtu_min = None

        # Verify network from 1 to 2
        self.validate_instance_can_reach_other(
            instance_1, instance_2, verify, mtu_min)

        # Verify network from 2 to 1
        self.validate_instance_can_reach_other(
            instance_2, instance_1, verify, mtu_min)

        # Validate tenant to external network routing
        self.validate_instance_can_reach_router(instance_1, verify, mtu_1)
        self.validate_instance_can_reach_router(instance_2, verify, mtu_2)


def floating_ips_from_instance(instance):
    """
    Retrieve floating IPs from an instance.

    :param instance: The instance to fetch floating IPs from
    :type instance: nova_client.Server

    :returns: A list of floating IPs for the specified server
    :rtype: list[str]
    """
    return ips_from_instance(instance, 'floating')


def fixed_ips_from_instance(instance):
    """
    Retrieve fixed IPs from an instance.

    :param instance: The instance to fetch fixed IPs from
    :type instance: nova_client.Server

    :returns: A list of fixed IPs for the specified server
    :rtype: list[str]
    """
    return ips_from_instance(instance, 'fixed')


def network_name_from_instance(instance):
    """Retrieve name of primary network the instance is attached to.

    :param instance: The instance to fetch name of network from.
    :type instance: nova_client.Server
    :returns: Name of primary network the instance is attached to.
    :rtype: str
    """
    return next(iter(instance.addresses))


def ips_from_instance(instance, ip_type):
    """
    Retrieve IPs of a certain type from an instance.

    :param instance: The instance to fetch IPs from
    :type instance: nova_client.Server
    :param ip_type: the type of IP to fetch, floating or fixed
    :type ip_type: str

    :returns: A list of IPs for the specified server
    :rtype: list[str]
    """
    if ip_type not in ['floating', 'fixed']:
        raise RuntimeError(
            "Only 'floating' and 'fixed' are valid IP types to search for"
        )
    return list([
        ip['addr'] for ip in instance.addresses[
            network_name_from_instance(instance)]
        if ip['OS-EXT-IPS:type'] == ip_type])


class NeutronNetworkingTest(NeutronNetworkingBase):
    """Ensure that openstack instances have valid networking."""

    def test_instances_have_networking(self):
        """Validate North/South and East/West networking.

        Tear down can optionally be disabled by setting the module path +
        class name + run_tearDown key under the `tests_options` key in
        tests.yaml.

        Abbreviated example:
        ...charm_tests.neutron.tests.NeutronNetworkingTest.run_tearDown: false
        """
        instance_1, instance_2 = self.retrieve_guests()
        if not all([instance_1, instance_2]):
            self.launch_guests(
                attach_to_external_network=self.attach_to_external_network,
                flavor_name=self.instance_flavor)
            instance_1, instance_2 = self.retrieve_guests()
        self.check_connectivity(instance_1, instance_2)
        self.run_resource_cleanup = self.get_my_tests_options(
            'run_resource_cleanup', True)


class DPDKNeutronNetworkingTest(NeutronNetworkingTest):
    """Ensure that openstack instances have valid networking with DPDK."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Neutron API Networking tests."""
        super(DPDKNeutronNetworkingTest, cls).setUpClass()

        # At this point in time the charms do not support configuring overlay
        # networks with DPDK.  To perform end to end validation we need to
        # attach instances directly to the provider network and subsequently
        # DHCP needs to be enabled on that network.
        #
        # Note that for instances wired with DPDK the DHCP request/response is
        # handled as private communication between the ovn-controller and the
        # instance, and as such there is no risk of rogue DHCP replies escaping
        # to the surrounding network.
        cls.attach_to_external_network = True
        cls.instance_flavor = 'hugepages'
        cls.external_subnet = cls.neutron_client.find_resource(
            'subnet',
            neutron_setup.OVERCLOUD_NETWORK_CONFIG['external_subnet_name'])
        if ('dhcp_enabled' not in cls.external_subnet or
                not cls.external_subnet['dhcp_enabled']):
            logging.info('Enabling DHCP on subnet {}'
                         .format(cls.external_subnet['name']))
            openstack_utils.update_subnet_dhcp(
                cls.neutron_client, cls.external_subnet, True)

    def test_instances_have_networking(self):
        """Enable DPDK then Validate North/South and East/West networking."""
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
            super().test_instances_have_networking()
        self.run_resource_cleanup = self.get_my_tests_options(
            'run_resource_cleanup', True)

    def resource_cleanup(self):
        """Extend to also revert VFIO NOIOMMU mode on units under test."""
        super().resource_cleanup()
        if not self.run_resource_cleanup:
            return

        if ('dhcp_enabled' not in self.external_subnet or
                not self.external_subnet['dhcp_enabled']):
            logging.info('Disabling DHCP on subnet {}'
                         .format(self.external_subnet['name']))
            openstack_utils.update_subnet_dhcp(
                self.neutron_client, self.external_subnet, False)

        self.disable_hugepages_vfio_on_hvs_in_vms()


class NeutronNetworkingVRRPTests(NeutronNetworkingBase):
    """Check networking when gateways are restarted."""

    def test_gateway_failure(self):
        """Validate networking in the case of a gateway failure."""
        instance_1, instance_2 = self.retrieve_guests()
        if not all([instance_1, instance_2]):
            self.launch_guests()
            instance_1, instance_2 = self.retrieve_guests()
        self.check_connectivity(instance_1, instance_2)

        routers = self.neutron_client.list_routers(
            name=openstack_utils.PROVIDER_ROUTER)['routers']
        assert len(routers) == 1, "Unexpected router count {}".format(
            len(routers))
        provider_router = routers[0]
        l3_agents = self.neutron_client.list_l3_agent_hosting_routers(
            router=provider_router['id'])['agents']
        logging.info(
            'Checking there are multiple L3 agents running tenant router')
        assert len(l3_agents) == 2, "Unexpected l3 agent count {}".format(
            len(l3_agents))
        uc_ks_session = openstack_utils.get_undercloud_keystone_session()
        uc_nova_client = openstack_utils.get_nova_session_client(uc_ks_session)
        uc_neutron_client = openstack_utils.get_neutron_session_client(
            uc_ks_session)
        for agent in l3_agents:
            gateway_hostname = agent['host']
            gateway_server = uc_nova_client.servers.find(name=gateway_hostname)
            logging.info("Shutting down {}".format(gateway_hostname))
            gateway_server.stop()
            self.check_server_state(
                uc_nova_client,
                'SHUTOFF',
                server_name=gateway_hostname)
            self.check_connectivity(instance_1, instance_2)
            gateway_server.start()
            self.check_server_state(
                uc_nova_client,
                'ACTIVE',
                server_name=gateway_hostname)
            self.check_neutron_agent_up(
                uc_neutron_client,
                gateway_hostname)
            self.check_connectivity(instance_1, instance_2)


class NeutronOVSDeferredRestartTest(test_utils.BaseDeferredRestartTest):
    """Deferred restart tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for deferred restart tests."""
        super().setUpClass(application_name='neutron-openvswitch')

    def run_tests(self):
        """Run deferred restart tests."""
        # Trigger a config change which triggers a deferred hook.
        self.run_charm_change_hook_test('config-changed')

        # Trigger a package change which requires a restart
        self.run_package_change_test(
            'openvswitch-switch',
            'openvswitch-switch')


class NeutronGatewayDeferredRestartTest(test_utils.BaseDeferredRestartTest):
    """Deferred restart tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for deferred restart tests."""
        super().setUpClass(application_name='neutron-gateway')

    def run_tests(self):
        """Run deferred restart tests."""
        # Trigger a config change which requires a restart
        self.run_charm_change_restart_test(
            'neutron-l3-agent',
            '/etc/neutron/neutron.conf')

        # Trigger a package change which requires a restart
        self.run_package_change_test(
            'openvswitch-switch',
            'openvswitch-switch')

    def check_clear_hooks(self):
        """Gateway does not defer hooks so noop."""
        return


class NeutronTempestTestK8S(tempest_tests.TempestTestScaleK8SBase):
    """Test neutron k8s scale out and scale back."""

    application_name = "neutron"
