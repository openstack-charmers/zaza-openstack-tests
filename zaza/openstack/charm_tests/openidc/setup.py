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

"""Code for setting up Keystone OpenID Connect federation."""

import logging

import zaza.model

from zaza.charm_lifecycle import utils as lifecycle_utils
from zaza.openstack.charm_tests.keystone_federation.utils import (
    keystone_federation_setup,
)
from zaza.openstack.utilities import (
    cli as cli_utils,
    openstack as openstack_utils,
)

APP_NAME = 'keystone-openidc'
FEDERATED_DOMAIN = "federated_domain"
FEDERATED_GROUP = "federated_users"
MEMBER = "Member"
IDP = "openid"
LOCAL_IDP_REMOTE_ID = 'https://{}:8443/realms/demorealm'
REMOTE_ID = "http://openidc"
PROTOCOL_NAME = "openid"
MAP_TEMPLATE = '''
[{{
        "local": [
            {{
                "user": {{
                    "name": "{{1}}",
                    "email": "{{2}}"
                }},
                "group": {{
                    "name": "{group_id}",
                    "domain": {{
                        "id": "{domain_id}"
                    }}
                }},
                "projects": [
                {{
                    "name": "{{1}}_project",
                    "roles": [
                                 {{
                                     "name": "{role_name}"
                                 }}
                             ]
                }}
                ]
           }}
        ],
        "remote": [
            {{
                "type": "HTTP_OIDC_SUB"
            }},
            {{
                "type": "HTTP_OIDC_USERNAME"
            }},
            {{
                "type": "HTTP_OIDC_EMAIL"
            }}
        ]
}}]
'''
REQUIRED_KEYS_MSG = 'required keys: oidc_client_id, oidc_provider_metadata_url'
# Default objects created by openidc-test-fixture charm
DEFAULT_CLIENT_ID = 'keystone'
DEFAULT_CLIENT_SECRET = 'ubuntu11'
DEFAULT_REALM = 'demorealm'
OPENIDC_TEST_FIXTURE = 'openidc-test-fixture'  # app's name


# NOTE(freyes): workaround for bug http://pad.lv/1982948
def relate_keystone_openidc():
    """Add relation between keystone and keystone-openidc.

    .. note: This is a workaround for the bug http://pad.lv/1982948
    """
    cli_utils.setup_logging()
    relations_added = False
    if not zaza.model.get_relation_id(APP_NAME, 'keystone'):
        logging.info('Adding relation keystone-openidc -> keystone')
        zaza.model.add_relation(APP_NAME,
                                'keystone-fid-service-provider',
                                'keystone:keystone-fid-service-provider')
        relations_added = True
    if not zaza.model.get_relation_id(APP_NAME, 'openstack-dashboard'):
        logging.info('Adding relation keystone-openidc -> openstack-dashboard')
        zaza.model.add_relation(
            APP_NAME,
            'websso-fid-service-provider',
            'openstack-dashboard:websso-fid-service-provider'
        )
        relations_added = True

    if relations_added:
        zaza.model.wait_for_agent_status()

    # NOTE: the test bundle has been deployed with a non-related
    # keystone-opendic subordinate application, and thus Zaza is expecting no
    # unit from this application. We are now relating it to a principal
    # keystone application with 3 units. We now need to make sure we wait for
    # the units to get fully deployed before proceeding:
    test_config = lifecycle_utils.get_charm_config(fatal=False)
    target_deploy_status = test_config.get('target_deploy_status', {})
    try:
        # this is a HA deployment
        target_deploy_status['keystone-openidc']['num-expected-units'] = 3
        opts = {
            'workload-status-message-prefix': REQUIRED_KEYS_MSG,
            'workload-status': 'blocked',
        }
        target_deploy_status['keystone-openidc'].update(opts)
    except KeyError:
        # num-expected-units wasn't set to 0, no expectation to be
        # fixed, let's move on.
        pass

    zaza.model.wait_for_application_states(
        states=target_deploy_status)


def configure_keystone_openidc():
    """Configure OpenIDC testing fixture certificate."""
    units = zaza.model.get_units(OPENIDC_TEST_FIXTURE)
    assert len(units) > 0, 'openidc-test-fixture units not found'
    ip = zaza.model.get_unit_public_address(units[0])
    url = 'https://{ip}:8443/realms/{realm}/.well-known/openid-configuration'
    cfg = {'oidc-client-id': DEFAULT_CLIENT_ID,
           'oidc-client-secret': DEFAULT_CLIENT_SECRET,
           'oidc-provider-metadata-url': url.format(ip=ip,
                                                    realm=DEFAULT_REALM)}
    zaza.model.set_application_config(APP_NAME, cfg)
    zaza.model.wait_for_agent_status()
    test_config = lifecycle_utils.get_charm_config(fatal=False)
    target_deploy_status = test_config.get('target_deploy_status', {})
    target_deploy_status.update({
        'keystone-openidc': {
            'workload-status': 'active',
            'workload-status-message': 'Unit is ready'
        },
    })
    zaza.model.wait_for_application_states(states=target_deploy_status)


def keystone_federation_setup_site1():
    """Configure Keystone Federation for the local IdP #1."""
    idp_unit = zaza.model.get_units("openidc-test-fixture")[0]
    idp_remote_id = LOCAL_IDP_REMOTE_ID.format(
        zaza.model.get_unit_public_address(idp_unit))

    keystone_session = openstack_utils.get_overcloud_keystone_session()
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    role = keystone_client.roles.find(name=MEMBER)
    logging.info('Using role name %s with id %s', role.name, role.id)

    keystone_federation_setup(
        federated_domain=FEDERATED_DOMAIN,
        federated_group=FEDERATED_GROUP,
        idp_name=IDP,
        idp_remote_id=idp_remote_id,
        protocol_name=PROTOCOL_NAME,
        map_template=MAP_TEMPLATE,
        role_name=role.name,
    )
