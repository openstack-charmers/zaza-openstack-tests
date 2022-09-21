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
import logging
import pprint

import zaza.model

from zaza.openstack.charm_tests.keystone import BaseKeystoneTest
from zaza.openstack.charm_tests.openidc.setup import (
    FEDERATED_DOMAIN,
    IDP,
    PROTOCOL_NAME,
)
from zaza.openstack.utilities import openstack as openstack_utils


# static users created by openidc-test-fixture charm
OIDC_TEST_USER = 'johndoe'
OIDC_TEST_USER_PASSWORD = 'f00bar'


class CharmKeystoneOpenIDCTest(BaseKeystoneTest):
    """Charm Keystone OpenID Connect tests."""

    def test_token_issue(self):
        """Test token issue with a federated user via openidc."""
        charm_config = zaza.model.get_application_config('keystone-openidc')
        client_id = charm_config['oidc-client-id']['value']
        client_secret = charm_config['oidc-client-secret']['value']
        metadata_url = charm_config['oidc-provider-metadata-url']['value']
        with self.v3_keystone_preferred():
            for ip in self.keystone_ips:
                openrc = {
                    'API_VERSION': 3,
                    'OS_USERNAME': OIDC_TEST_USER,
                    'OS_PASSWORD': OIDC_TEST_USER_PASSWORD,
                    'OS_AUTH_URL': 'https://{}:5000/v3'.format(ip),
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
                logging.info('keystone IP %s', ip)
                logging.info('openrc: %s', pprint.pformat(openrc))
                keystone_session = openstack_utils.get_keystone_session(
                    openrc, scope='PROJECT')
                logging.info('Retrieving token for federated user')
                token = keystone_session.get_token()
                logging.info('Token: %s', token)
                self.assertIsNotNone(token)
        logging.info('OK')
