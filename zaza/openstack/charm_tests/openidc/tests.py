# Copyright 2022 Canonical Ltd.
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

"""Keystone OpenID Connect Testing."""
import copy
import logging
import pprint

import zaza.model

from zaza.openstack.charm_tests.glance.setup import CIRROS_IMAGE_NAME
from zaza.openstack.charm_tests.keystone import BaseKeystoneTest
from zaza.openstack.charm_tests.neutron.setup import (
    OVERCLOUD_NETWORK_CONFIG,
    DEFAULT_UNDERCLOUD_NETWORK_CONFIG,
)
from zaza.openstack.charm_tests.nova.setup import manage_ssh_key
from zaza.openstack.charm_tests.openidc.setup import (
    FEDERATED_DOMAIN,
    IDP,
    PROTOCOL_NAME,
)
from zaza.openstack.utilities import (
    generic as generic_utils,
    openstack as openstack_utils,
)

# static users created by openidc-test-fixture charm
OIDC_TEST_USER = 'johndoe'
OIDC_TEST_USER_PASSWORD = 'f00bar'


class BaseCharmKeystoneOpenIDC(BaseKeystoneTest):
    """Charm Keystone OpenID Connect tests."""

    run_resource_cleanup = True
    RESOURCE_PREFIX = 'zaza-openidc'

    @classmethod
    def setUpClass(cls):
        """Define openrc credentials for OIDC_TEST_USER."""
        super().setUpClass()
        charm_config = zaza.model.get_application_config('keystone-openidc')
        client_id = charm_config['oidc-client-id']['value']
        client_secret = charm_config['oidc-client-secret']['value']
        metadata_url = charm_config['oidc-provider-metadata-url']['value']
        cls.oidc_test_openrc = {
            'API_VERSION': 3,
            'OS_USERNAME': OIDC_TEST_USER,
            'OS_PASSWORD': OIDC_TEST_USER_PASSWORD,
            # using the first keystone ip by default, for environments with
            # HA+TLS enabled this is the virtual IP, otherwise it will be one
            # of the keystone units.
            'OS_AUTH_URL': 'https://{}:5000/v3'.format(cls.keystone_ips[0]),
            'OS_PROJECT_DOMAIN_NAME': FEDERATED_DOMAIN,
            'OS_PROJECT_NAME': '{}_project'.format(OIDC_TEST_USER),
            'OS_CACERT': openstack_utils.get_cacert(),
            # openid specific info
            'OS_AUTH_TYPE': 'v3oidcpassword',
            'OS_DISCOVERY_ENDPOINT': metadata_url,
            'OS_OPENID_SCOPE': 'openid email profile',
            'OS_CLIENT_ID': client_id,
            'OS_CLIENT_SECRET': client_secret,
            'OS_IDENTITY_PROVIDER': IDP,
            'OS_PROTOCOL': PROTOCOL_NAME,
        }
        logging.info('openrc: %s', pprint.pformat(cls.oidc_test_openrc))


class TestToken(BaseCharmKeystoneOpenIDC):
    """Test tokens for user's backed by OpenID Connect via Federation."""

    def test_token_issue(self):
        """Test token issue with a federated user via openidc."""
        openrc = copy.deepcopy(self.oidc_test_openrc)
        with self.v3_keystone_preferred():
            for ip in self.keystone_ips:
                logging.info('keystone IP %s', ip)
                openrc['AUTH_URL'] = 'https://{}:5000/v3'.format(ip)
                keystone_session = openstack_utils.get_keystone_session(
                    openrc, scope='PROJECT')
                logging.info('Retrieving token for federated user')
                token = keystone_session.get_token()
                logging.info('Token: %s', token)
                self.assertIsNotNone(token)
        logging.info('OK')


class TestLaunchInstance(BaseCharmKeystoneOpenIDC):
    """Test instance launching in a project defined by Federation mapping."""

    @classmethod
    def setUpClass(cls):
        """Configure user's project network backed by OpenID Connect."""
        super().setUpClass()
        # Get network configuration settings
        network_config = {"private_net_cidr": "192.168.21.0/24"}
        # Declared overcloud settings
        network_config.update(OVERCLOUD_NETWORK_CONFIG)
        # Default undercloud settings
        network_config.update(DEFAULT_UNDERCLOUD_NETWORK_CONFIG)
        # Environment specific settings
        network_config.update(generic_utils.get_undercloud_env_vars())
        ip_version = network_config.get("ip_version") or 4

        keystone_session = openstack_utils.get_keystone_session(
            cls.oidc_test_openrc, scope='PROJECT')
        # find user's project id
        project_id = keystone_session.get_project_id()

        # Get authenticated clients
        neutron_client = openstack_utils.get_neutron_session_client(
            keystone_session)
        nova_client = openstack_utils.get_nova_session_client(
            keystone_session)

        # create 'zaza' key in user's project
        manage_ssh_key(nova_client)

        # create a router attached to the external network
        ext_net_name = network_config["external_net_name"]
        networks = neutron_client.list_networks(name=ext_net_name)
        ext_network = networks['networks'][0]
        provider_router = openstack_utils.create_provider_router(
            neutron_client, project_id)
        openstack_utils.plug_extnet_into_router(
            neutron_client,
            provider_router,
            ext_network)

        # create project's private network
        project_network = openstack_utils.create_project_network(
            neutron_client,
            project_id,
            shared=False,
            network_type=network_config["network_type"],
            net_name=network_config["project_net_name"])
        project_subnet = openstack_utils.create_project_subnet(
            neutron_client,
            project_id,
            project_network,
            network_config["private_net_cidr"],
            ip_version=ip_version,
            subnet_name=network_config["project_subnet_name"])
        openstack_utils.update_subnet_dns(
            neutron_client,
            project_subnet,
            network_config["external_dns"])
        openstack_utils.plug_subnet_into_router(
            neutron_client,
            provider_router['name'],
            project_network,
            project_subnet)
        openstack_utils.add_neutron_secgroup_rules(neutron_client, project_id)

    def test_20_launch_instance(self):
        """Test launching an instance in a project defined by mapping rules."""
        keystone_session = openstack_utils.get_keystone_session(
            self.oidc_test_openrc, scope='PROJECT')

        self.launch_guest('test-42',
                          instance_key=CIRROS_IMAGE_NAME,
                          keystone_session=keystone_session)
