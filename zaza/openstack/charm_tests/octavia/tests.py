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

"""Encapsulate octavia testing."""

import logging
import subprocess
import tenacity
import unittest

from keystoneauth1 import exceptions as keystone_exceptions
import octaviaclient.api.v2.octavia
import osc_lib.exceptions

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils

from zaza.openstack.utilities import generic as generic_utils
from zaza.openstack.utilities import ObjectRetrierWraps
from zaza.openstack.utilities.exceptions import (
    LoadBalancerUnexpectedState,
    LoadBalancerUnrecoverableError,
)

LBAAS_ADMIN_ROLE = 'load-balancer_admin'


def _op_role_current_user(keystone_client, keystone_session, op, role_name,
                          scope=None):
    """Perform role operation on current user.

    :param keystone_client: Keysonte cilent object
    :type keystone_client: keystoneclient.v3.Client
    :param keystone_session: Keystone session object
    :type keystone_session: keystoneauth1.session.Session
    :param op: Operation to perform, one of ('grant', 'revoke')
    :type op: str
    :param role_name: Name of role
    :type role_name: str
    :param scope: Scope to apply role to, one of ('domain', 'project'(default))
    :type scope: Optional[str]
    :returns: the granted role returned from server.
    :rtype: keystoneclient.v3.roles.Role
    :raises: ValueError, keystoneauth1.exceptions.*
    """
    allowed_ops = ('grant', 'revoke')
    if op not in allowed_ops:
        raise ValueError('op "{}" not in allowed_ops "{}"'
                         .format(op, allowed_ops))
    scope = scope or 'project'
    allowed_scope = ('domain', 'project')
    if scope not in allowed_scope:
        raise ValueError('scope "{}" not in allowed_scope "{}"'
                         .format(scope, allowed_scope))

    logging.info('{} "{}" role {} current user with "{}" scope...'
                 .format(op.capitalize(), role_name,
                         'to' if op == 'grant' else 'from',
                         scope))
    role_method = getattr(keystone_client.roles, op)
    token = keystone_session.get_token()
    token_data = keystone_client.tokens.get_token_data(token)
    role = keystone_client.roles.find(name=role_name)

    kwargs = {
        'user': token_data['token']['user']['id'],
        scope: token_data['token'][scope]['id'],
    }
    return role_method(
        role,
        **kwargs)


def grant_role_current_user(keystone_client, keystone_session, role_name,
                            scope=None):
    """Grant role to current user.

    Please refer to docstring for _op_role_current_user.
    """
    _op_role_current_user(
        keystone_client, keystone_session, 'grant', role_name, scope=scope)


def revoke_role_current_user(keystone_client, keystone_session, role_name,
                             scope=None):
    """Grant role to current user.

    Please refer to docstring for _op_role_current_user.
    """
    _op_role_current_user(
        keystone_client, keystone_session, 'revoke', role_name, scope=scope)


class CharmOperationTest(test_utils.OpenStackBaseTest):
    """Charm operation tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Octavia charm operation tests."""
        super(CharmOperationTest, cls).setUpClass()

    def get_port_ips(self):
        """Extract IP info from Neutron ports tagged with charm-octavia."""
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        neutron_client = openstack_utils.get_neutron_session_client(
            keystone_session)
        resp = neutron_client.list_ports(tags='charm-octavia')
        neutron_ip_list = []
        for port in resp['ports']:
            for ip_info in port['fixed_ips']:
                neutron_ip_list.append(ip_info['ip_address'])
        return neutron_ip_list

    def test_update_controller_ip_port_list(self):
        """Test update_controller_ip_port_list.

        Add a unit and then delete a unit, then query the list of ports to
        check that the port has been deleted.
        """
        raise unittest.SkipTest("Skipping because of lp:1951858")
        app = self.test_config['charm_name']
        logging.info("test_update_controller_ip_port_list: start test")
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()
        ips = self.get_port_ips()
        num = len(ips)
        logging.info('initial hm port num is {}: {}'.format(num, ips))

        logging.info("test_update_controller_ip_port_list: add one unit")
        logging.info("Adding one unit ...")
        zaza.model.add_unit(app)
        logging.info("Wait until one unit is added ...")
        zaza.model.block_until_unit_count(app, num+1)
        zaza.model.wait_for_application_states()
        ips = self.get_port_ips()
        logging.info('hm ports are {} after adding one unit'.format(ips))
        self.assertTrue(len(ips) == num+1)

        logging.info("test_update_controller_ip_port_list: remove one unit")
        logging.info("Removing one unit ...")
        _, nons = generic_utils.get_leaders_and_non_leaders(app)
        zaza.model.destroy_unit(app, nons[0])
        logging.info("Wait until one unit is deleted ...")
        zaza.model.block_until_unit_count(app, num)
        zaza.model.wait_for_application_states()
        ips = self.get_port_ips()
        logging.info('hm ports are {} after deleting one unit'.format(ips))
        self.assertTrue(len(ips) == num)

    def test_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped, then resume and check
        they are started.
        """
        services = [
            'apache2',
            'octavia-health-manager',
            'octavia-housekeeping',
            'octavia-worker',
        ]
        if openstack_utils.ovn_present():
            services.append('octavia-driver-agent')
        logging.info('Skipping pause resume test LP: #1886202...')
        return
        logging.info('Testing pause resume (services="{}")'
                     .format(services))
        with self.pause_resume(services, pgrep_full=True):
            pass


class LBAASv2Test(test_utils.OpenStackBaseTest):
    """LBaaSv2 service tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running LBaaSv2 service tests."""
        super(LBAASv2Test, cls).setUpClass()
        cls.keystone_client = ObjectRetrierWraps(
            openstack_utils.get_keystone_session_client(cls.keystone_session))

        if (openstack_utils.get_os_release() >=
                openstack_utils.get_os_release('focal_wallaby')):
            # add role to admin user for the duration of the test
            grant_role_current_user(cls.keystone_client, cls.keystone_session,
                                    LBAAS_ADMIN_ROLE)

        cls.neutron_client = ObjectRetrierWraps(
            openstack_utils.get_neutron_session_client(cls.keystone_session))
        cls.octavia_client = ObjectRetrierWraps(
            openstack_utils.get_octavia_session_client(cls.keystone_session))
        cls.RESOURCE_PREFIX = 'zaza-octavia'

        # NOTE(fnordahl): in the event of a test failure we do not want to run
        # tear down code as it will make debugging a problem virtually
        # impossible.  To alleviate each test method will set the
        # `run_tearDown` instance variable at the end which will let us run
        # tear down only when there were no failure.
        cls.run_tearDown = False
        # List of load balancers created by this test
        cls.loadbalancers = []
        # List of floating IPs created by this test
        cls.fips = []

    def _remove_amphorae_instances(self):
        """Remove amphorae instances forcefully.

        In some situations Octavia is unable to remove load balancer resources.
        This helper can be used to remove the underlying instances.
        """
        result = self.octavia_client.amphora_list()
        for amphora in result.get('amphorae', []):
            for server in self.nova_client.servers.list():
                if 'compute_id' in amphora and server.id == amphora[
                        'compute_id']:
                    try:
                        openstack_utils.delete_resource(
                            self.nova_client.servers,
                            server.id,
                            msg="server")
                    except AssertionError as e:
                        logging.warning(
                            'Gave up waiting for resource cleanup: "{}"'
                            .format(str(e)))

    @tenacity.retry(stop=tenacity.stop_after_attempt(3),
                    wait=tenacity.wait_exponential(
                        multiplier=1, min=2, max=10))
    def resource_cleanup(self, only_local=False):
        """Remove resources created during test execution.

        :param only_local: When set to true do not call parent method
        :type only_local: bool
        """
        for lb in self.loadbalancers:
            try:
                self.octavia_client.load_balancer_delete(
                    lb['id'], cascade=True)
            except octaviaclient.api.v2.octavia.OctaviaClientException as e:
                logging.info('Octavia is unable to delete load balancer: "{}"'
                             .format(e))
                logging.info('Attempting to forcefully remove amphorae')
                self._remove_amphorae_instances()
            else:
                try:
                    self.wait_for_lb_resource(
                        self.octavia_client.load_balancer_show, lb['id'],
                        provisioning_status='DELETED')
                except osc_lib.exceptions.NotFound:
                    pass
        # allow resource cleanup to be run multiple times
        self.loadbalancers = []

        if (openstack_utils.get_os_release() >=
                openstack_utils.get_os_release('focal_wallaby')):
            # revoke role from admin user added by this test
            revoke_role_current_user(self.keystone_client,
                                     self.keystone_session,
                                     LBAAS_ADMIN_ROLE)

        for fip in self.fips:
            self.neutron_client.delete_floatingip(fip)
        # allow resource cleanup to be run multiple times
        self.fips = []

        if only_local:
            return

        # we run the parent resource_cleanup last as it will remove instances
        # referenced as members in the above cleaned up load balancers
        super(LBAASv2Test, self).resource_cleanup()

    @staticmethod
    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(LoadBalancerUnexpectedState),
        wait=tenacity.wait_fixed(1), reraise=True,
        stop=tenacity.stop_after_delay(900))
    def wait_for_lb_resource(octavia_show_func, resource_id,
                             provisioning_status=None, operating_status=None):
        """Wait for loadbalancer resource to reach expected status."""
        provisioning_status = provisioning_status or 'ACTIVE'
        resp = octavia_show_func(resource_id)
        logging.info("Current provisioning status: {}, waiting for {}"
                     .format(resp['provisioning_status'], provisioning_status))

        msg = ('load balancer resource has not reached '
               'expected provisioning status: {}'.format(resp))

        # ERROR is a final state, once it's reached there is no reason to keep
        # retrying and delaying the failure.
        if resp['provisioning_status'] == 'ERROR':
            raise LoadBalancerUnrecoverableError(msg)
        elif resp['provisioning_status'] != provisioning_status:
            raise LoadBalancerUnexpectedState(msg)

        if operating_status:
            logging.info('Current operating status: {}, waiting for {}'
                         .format(resp['operating_status'], operating_status))
            if not resp['operating_status'] == operating_status:
                raise LoadBalancerUnexpectedState((
                    'load balancer resource has not reached '
                    'expected operating status: {}'.format(resp)))

        return resp

    @staticmethod
    def get_lb_providers(octavia_client):
        """Retrieve loadbalancer providers.

        :param octavia_client: Octavia client object
        :type octavia_client: OctaviaAPI
        :returns: Dictionary with provider information, name as keys
        :rtype: Dict[str,Dict[str,str]]
        """
        providers = {
            provider['name']: provider
            for provider in octavia_client.provider_list().get('providers', [])
            if provider['name'] != 'octavia'  # alias for `amphora`, skip
        }
        return providers

    def _create_lb_resources(self, octavia_client, provider, vip_subnet_id,
                             member_subnet_id, payload_ips):
        # The `amphora` provider is required for load balancing based on
        # higher layer protocols
        if provider == 'amphora':
            protocol = 'HTTP'
            algorithm = 'ROUND_ROBIN'
            monitor = True
        else:
            protocol = 'TCP'
            algorithm = 'SOURCE_IP_PORT'
            monitor = False

        result = octavia_client.load_balancer_create(
            json={
                'loadbalancer': {
                    'description': 'Created by Zaza',
                    'admin_state_up': True,
                    'vip_subnet_id': vip_subnet_id,
                    'name': 'zaza-{}-0'.format(provider),
                    'provider': provider,
                }})
        lb = result['loadbalancer']
        self.loadbalancers.append(lb)
        lb_id = lb['id']

        logging.info('Awaiting loadbalancer to reach provisioning_status '
                     '"ACTIVE"')
        resp = self.wait_for_lb_resource(
            octavia_client.load_balancer_show, lb_id)
        logging.info(resp)

        result = octavia_client.listener_create(
            json={
                'listener': {
                    'loadbalancer_id': lb_id,
                    'name': 'listener1',
                    'protocol': protocol,
                    'protocol_port': 80
                },
            })
        listener_id = result['listener']['id']
        logging.info('Awaiting listener to reach provisioning_status '
                     '"ACTIVE"')
        resp = self.wait_for_lb_resource(
            octavia_client.listener_show, listener_id)
        logging.info(resp)

        result = octavia_client.pool_create(
            json={
                'pool': {
                    'listener_id': listener_id,
                    'name': 'pool1',
                    'lb_algorithm': algorithm,
                    'protocol': protocol,
                },
            })
        pool_id = result['pool']['id']
        logging.info('Awaiting pool to reach provisioning_status '
                     '"ACTIVE"')
        resp = self.wait_for_lb_resource(octavia_client.pool_show, pool_id)
        logging.info(resp)

        if monitor:
            result = octavia_client.health_monitor_create(
                json={
                    'healthmonitor': {
                        'pool_id': pool_id,
                        'delay': 5,
                        'max_retries': 4,
                        'timeout': 10,
                        'type': 'HTTP',
                        'url_path': '/',
                    },
                })
            healthmonitor_id = result['healthmonitor']['id']
            logging.info('Awaiting healthmonitor to reach provisioning_status '
                         '"ACTIVE"')
            resp = self.wait_for_lb_resource(
                octavia_client.health_monitor_show,
                healthmonitor_id)
            logging.info(resp)

        for ip in payload_ips:
            result = octavia_client.member_create(
                pool_id=pool_id,
                json={
                    'member': {
                        'subnet_id': member_subnet_id,
                        'address': ip,
                        'protocol_port': 80,
                    },
                })
            member_id = result['member']['id']
            logging.info('Awaiting member to reach provisioning_status '
                         '"ACTIVE"')
            resp = self.wait_for_lb_resource(
                lambda x: octavia_client.member_show(
                    pool_id=pool_id, member_id=x),
                member_id,
                operating_status='')
            # Temporarily disable this check until we figure out why
            # operational_status sometimes does not become 'ONLINE'
            # while the member does indeed work and the subsequent
            # retrieval of payload through loadbalancer is successful
            # ref LP: #1896729.
            #    operating_status='ONLINE' if monitor else '')
            logging.info(resp)
        return lb

    @staticmethod
    @tenacity.retry(wait=tenacity.wait_fixed(1),
                    reraise=True, stop=tenacity.stop_after_delay(900))
    def _get_payload(ip):
        return subprocess.check_output(
            ['wget', '-O', '-',
             'http://{}/'.format(ip)],
            universal_newlines=True)

    def test_create_loadbalancer(self):
        """Create load balancer."""
        # Prepare payload instances
        # First we allow communication to port 80 by adding a security group
        # rule
        project_id = openstack_utils.get_project_id(
            self.keystone_client, 'admin', domain_name='admin_domain')
        openstack_utils.add_neutron_secgroup_rules(
            self.neutron_client,
            project_id,
            [{'protocol': 'tcp',
              'port_range_min': '80',
              'port_range_max': '80',
              'direction': 'ingress'}])

        # Then we request two Ubuntu instances with the Apache web server
        # installed
        instance_1, instance_2 = self.launch_guests(
            userdata='#cloud-config\npackages:\n - apache2\n')

        # Get IP of the prepared payload instances
        payload_ips = []
        for server in (instance_1, instance_2):
            payload_ips.append(server.networks[openstack_utils.PRIVATE_NET][0])
        self.assertTrue(len(payload_ips) > 0)

        resp = self.neutron_client.list_networks(
            name=openstack_utils.PRIVATE_NET)
        subnet_id = resp['networks'][0]['subnets'][0]
        if openstack_utils.dvr_enabled():
            resp = self.neutron_client.list_networks(
                name='private_lb_fip_network')
            vip_subnet_id = resp['networks'][0]['subnets'][0]
        else:
            vip_subnet_id = subnet_id
        for provider in self.get_lb_providers(self.octavia_client).keys():
            logging.info('Creating loadbalancer with provider {}'
                         .format(provider))
            final_exc = None
            # NOTE: we cannot use tenacity here as the method we call into
            # already uses it to wait for operations to complete.
            for retry in range(0, 3):
                try:
                    lb = self._create_lb_resources(self.octavia_client,
                                                   provider,
                                                   vip_subnet_id,
                                                   subnet_id,
                                                   payload_ips)
                    break
                except (AssertionError,
                        keystone_exceptions.connection.ConnectFailure) as e:
                    logging.info('Retrying load balancer creation, last '
                                 'failure: "{}"'.format(str(e)))
                    self.resource_cleanup(only_local=True)
                    final_exc = e
            else:
                raise final_exc

            lb_fp = openstack_utils.create_floating_ip(
                self.neutron_client,
                openstack_utils.EXT_NET,
                port={'id': lb['vip_port_id']})

            snippet = 'This is the default welcome page'
            assert snippet in self._get_payload(lb_fp['floating_ip_address'])
            logging.info('Found "{}" in page retrieved through load balancer '
                         ' (provider="{}") at "http://{}/"'
                         .format(snippet, provider,
                                 lb_fp['floating_ip_address']))

        # If we get here, it means the tests passed
        self.run_resource_cleanup = True
