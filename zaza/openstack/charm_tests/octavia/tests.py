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

import osc_lib.exceptions

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class CharmOperationTest(test_utils.OpenStackBaseTest):
    """Charm operation tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Octavia charm operation tests."""
        super(CharmOperationTest, cls).setUpClass()

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
        cls.keystone_client = openstack_utils.get_keystone_session_client(
            cls.keystone_session)
        cls.neutron_client = openstack_utils.get_neutron_session_client(
            cls.keystone_session)
        cls.octavia_client = openstack_utils.get_octavia_session_client(
            cls.keystone_session)
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

    def resource_cleanup(self):
        """Remove resources created during test execution."""
        for lb in self.loadbalancers:
            self.octavia_client.load_balancer_delete(lb['id'], cascade=True)
            try:
                self.wait_for_lb_resource(
                    self.octavia_client.load_balancer_show, lb['id'],
                    provisioning_status='DELETED')
            except osc_lib.exceptions.NotFound:
                pass
        for fip in self.fips:
            self.neutron_client.delete_floatingip(fip)
        # we run the parent resource_cleanup last as it will remove instances
        # referenced as members in the above cleaned up load balancers
        super(LBAASv2Test, self).resource_cleanup()

    @staticmethod
    @tenacity.retry(retry=tenacity.retry_if_exception_type(AssertionError),
                    wait=tenacity.wait_fixed(1), reraise=True,
                    stop=tenacity.stop_after_delay(900))
    def wait_for_lb_resource(octavia_show_func, resource_id,
                             provisioning_status=None, operating_status=None):
        """Wait for loadbalancer resource to reach expected status."""
        provisioning_status = provisioning_status or 'ACTIVE'
        resp = octavia_show_func(resource_id)
        logging.info(resp['provisioning_status'])
        assert resp['provisioning_status'] == provisioning_status, (
            'load balancer resource has not reached '
            'expected provisioning status: {}'
            .format(resp))
        if operating_status:
            logging.info(resp['operating_status'])
            assert resp['operating_status'] == operating_status, (
                'load balancer resource has not reached '
                'expected operating status: {}'.format(resp))

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
                operating_status='ONLINE' if monitor else '')
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
            payload_ips.append(server.networks['private'][0])
        self.assertTrue(len(payload_ips) > 0)

        resp = self.neutron_client.list_networks(name='private')
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
            lb = self._create_lb_resources(self.octavia_client, provider,
                                           vip_subnet_id, subnet_id,
                                           payload_ips)
            self.loadbalancers.append(lb)

            lb_fp = openstack_utils.create_floating_ip(
                self.neutron_client, 'ext_net', port={'id': lb['vip_port_id']})

            snippet = 'This is the default welcome page'
            assert snippet in self._get_payload(lb_fp['floating_ip_address'])
            logging.info('Found "{}" in page retrieved through load balancer '
                         ' (provider="{}") at "http://{}/"'
                         .format(snippet, provider,
                                 lb_fp['floating_ip_address']))

        # If we get here, it means the tests passed
        self.run_resource_cleanup = True
