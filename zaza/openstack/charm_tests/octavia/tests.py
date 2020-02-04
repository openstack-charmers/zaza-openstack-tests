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
        self.pause_resume(['apache2'])


class LBAASv2Test(test_utils.OpenStackBaseTest):
    """LBaaSv2 service tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running LBaaSv2 service tests."""
        super(LBAASv2Test, cls).setUpClass()

    @staticmethod
    @tenacity.retry(wait=tenacity.wait_fixed(1),
                    reraise=True, stop=tenacity.stop_after_delay(900))
    def wait_for_lb_resource(octavia_show_func, resource_id,
                             operating_status=None):
        """Wait for loadbalancer resource to reach expected status."""
        resp = octavia_show_func(resource_id)
        logging.info(resp['provisioning_status'])
        assert resp['provisioning_status'] == 'ACTIVE', (
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
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        neutron_client = openstack_utils.get_neutron_session_client(
            keystone_session)
        nova_client = openstack_utils.get_nova_session_client(
            keystone_session)

        # Get IP of the prepared payload instances
        payload_ips = []
        for server in nova_client.servers.list():
            payload_ips.append(server.networks['private'][0])
        self.assertTrue(len(payload_ips) > 0)

        resp = neutron_client.list_networks(name='private')
        subnet_id = resp['networks'][0]['subnets'][0]
        if openstack_utils.dvr_enabled():
            resp = neutron_client.list_networks(name='private_lb_fip_network')
            vip_subnet_id = resp['networks'][0]['subnets'][0]
        else:
            vip_subnet_id = subnet_id
        octavia_client = openstack_utils.get_octavia_session_client(
            keystone_session)
        for provider in self.get_lb_providers(octavia_client).keys():
            logging.info('Creating loadbalancer with provider {}'
                         .format(provider))
            lb = self._create_lb_resources(octavia_client, provider,
                                           vip_subnet_id, subnet_id,
                                           payload_ips)

            lb_fp = openstack_utils.create_floating_ip(
                neutron_client, 'ext_net', port={'id': lb['vip_port_id']})

            snippet = 'This is the default welcome page'
            assert snippet in self._get_payload(lb_fp['floating_ip_address'])
            logging.info('Found "{}" in page retrieved through load balancer '
                         ' (provider="{}") at "http://{}/"'
                         .format(snippet, provider,
                                 lb_fp['floating_ip_address']))
