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

"""Code for configuring octavia."""

import os
import base64
import logging

import zaza.openstack.utilities.cert as cert
import zaza.charm_lifecycle.utils
import zaza.openstack.charm_tests.test_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.utilities.openstack as openstack
import zaza.openstack.configure.guest


def ensure_lts_images():
    """Ensure that bionic and focal images are available for the tests."""
    glance_setup.add_lts_image(image_name='bionic', release='bionic')
    glance_setup.add_lts_image(image_name='focal', release='focal')


def add_amphora_image(image_url=None):
    """Add Octavia ``amphora`` test image to glance.

    :param image_url: URL where image resides
    :type image_url: str
    """
    image_name = 'amphora-x64-haproxy'
    if not image_url:
        image_url = (
            os.environ.get('FUNCTEST_AMPHORA_LOCATION', None) or
            'http://tarballs.openstack.org/octavia/test-images/'
            'test-only-amphora-x64-haproxy-ubuntu-xenial.qcow2')
    glance_setup.add_image(
        image_url,
        image_name=image_name,
        tags=['octavia-amphora'])


def configure_octavia():
    """Do mandatory post deployment configuration of Octavia."""
    # Tell Octavia charm it is safe to create cloud resources
    logging.info('Running `configure-resources` action on Octavia leader unit')
    zaza.model.run_action_on_leader(
        'octavia',
        'configure-resources',
        action_params={})
    # Generate certificates for controller/load balancer instance communication
    (issuing_cakey, issuing_cacert) = cert.generate_cert(
        'OSCI Zaza Issuer',
        password='zaza',
        generate_ca=True)
    (controller_cakey, controller_cacert) = cert.generate_cert(
        'OSCI Zaza Octavia Controller',
        generate_ca=True)
    (controller_key, controller_cert) = cert.generate_cert(
        '*.serverstack',
        issuer_name='OSCI Zaza Octavia Controller',
        signing_key=controller_cakey)
    controller_bundle = controller_cert + controller_key
    cert_config = {
        'lb-mgmt-issuing-cacert': base64.b64encode(
            issuing_cacert).decode('utf-8'),
        'lb-mgmt-issuing-ca-private-key': base64.b64encode(
            issuing_cakey).decode('utf-8'),
        'lb-mgmt-issuing-ca-key-passphrase': 'zaza',
        'lb-mgmt-controller-cacert': base64.b64encode(
            controller_cacert).decode('utf-8'),
        'lb-mgmt-controller-cert': base64.b64encode(
            controller_bundle).decode('utf-8'),
    }
    logging.info('Configuring certificates for mandatory Octavia '
                 'client/server authentication '
                 '(client being the ``Amphorae`` load balancer instances)')

    # Our expected workload status will change after we have configured the
    # certificates
    test_config = zaza.charm_lifecycle.utils.get_charm_config()
    del test_config['target_deploy_status']['octavia']

    _singleton = zaza.openstack.charm_tests.test_utils.OpenStackBaseTest()
    _singleton.setUpClass()
    with _singleton.config_change(cert_config, cert_config):
        # wait for configuration to be applied then return
        pass


def prepare_payload_instance():
    """Prepare a instance we can use as payload test."""
    session = openstack.get_overcloud_keystone_session()
    keystone = openstack.get_keystone_session_client(session)
    neutron = openstack.get_neutron_session_client(session)
    project_id = openstack.get_project_id(
        keystone, 'admin', domain_name='admin_domain')
    openstack.add_neutron_secgroup_rules(
        neutron,
        project_id,
        [{'protocol': 'tcp',
          'port_range_min': '80',
          'port_range_max': '80',
          'direction': 'ingress'}])
    zaza.openstack.configure.guest.launch_instance(
        glance_setup.LTS_IMAGE_NAME,
        userdata='#cloud-config\npackages:\n - apache2\n')


def centralized_fip_network():
    """Create network with centralized router for connecting lb and fips.

    There are currently a few outstanding upstream issues with connecting a
    Octavia loadbalancer to the outside world through a Floating IP when used
    in conjunction with Neutron DVR [0][1][2][3][4][5].

    Although there are some fixes provided in the referenced material, the
    current implementation still show issues and appearas to limit how we can
    model a DVR deployment.

    A approach to work around this is to create a separate non-distributed
    network for hosting the load balancer VIP and connecting it to a FIP.

    The payload- and loadbalancer- instances can stay in a distributed
    network, only the VIP must be in a non-distributed network.
    (although the actual hosting of said router can be on a compute host
    acting as a "centralized" snat router in a DVR deployment.)

    0: https://bit.ly/30LgX4T
    1: https://bugs.launchpad.net/neutron/+bug/1583694
    2: https://bugs.launchpad.net/neutron/+bug/1667877
    3: https://review.opendev.org/#/c/437970/
    4: https://review.opendev.org/#/c/437986/
    5: https://review.opendev.org/#/c/466434/
    """
    if not openstack.dvr_enabled():
        logging.info('DVR not enabled, skip.')
        return
    keystone_session = openstack.get_overcloud_keystone_session()
    neutron_client = openstack.get_neutron_session_client(
        keystone_session)

    resp = neutron_client.create_network(
        {'network': {'name': 'private_lb_fip_network'}})
    network = resp['network']
    resp = neutron_client.create_subnet(
        {
            'subnets': [
                {
                    'name': 'private_lb_fip_subnet',
                    'network_id': network['id'],
                    'ip_version': 4,
                    'cidr': '10.42.0.0/24',
                },
            ],
        })
    subnet = resp['subnets'][0]
    resp = neutron_client.create_router(
        {
            'router': {
                'name': 'lb_fip_router',
                'external_gateway_info': {
                    'network_id': openstack.get_net_uuid(
                        neutron_client, 'ext_net'),
                },
                'distributed': False,
            },
        })
    router = resp['router']
    neutron_client.add_interface_router(
        router['id'], {'subnet_id': subnet['id']})
