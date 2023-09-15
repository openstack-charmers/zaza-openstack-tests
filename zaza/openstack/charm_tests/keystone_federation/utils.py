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
"""Code for setting up a Keystone Federation Provider."""

import json
import logging

import keystoneauth1

from zaza.openstack.utilities import (
    cli as cli_utils,
    openstack as openstack_utils,
)


def keystone_federation_setup(federated_domain: str,
                              federated_group: str,
                              idp_name: str,
                              idp_remote_id: str,
                              protocol_name: str,
                              map_template: str,
                              role_name: str = 'Member',
                              ):
    """Configure Keystone Federation."""
    cli_utils.setup_logging()
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)

    try:
        domain = keystone_client.domains.find(name=federated_domain)
        logging.info('Reusing domain %s with id %s',
                     federated_domain, domain.id)
    except keystoneauth1.exceptions.http.NotFound:
        logging.info('Creating domain %s', federated_domain)
        domain = keystone_client.domains.create(
            federated_domain,
            description="Federated Domain",
            enabled=True)

    try:
        group = keystone_client.groups.find(
            name=federated_group, domain=domain)
        logging.info('Reusing group %s with id %s', federated_group, group.id)
    except keystoneauth1.exceptions.http.NotFound:
        logging.info('Creating group %s', federated_group)
        group = keystone_client.groups.create(
            federated_group,
            domain=domain,
            enabled=True)

    role = keystone_client.roles.find(name=role_name)
    assert role is not None, 'Role %s not found' % role_name
    logging.info('Granting %s role to group %s on domain %s',
                 role.name, group.name, domain.name)
    keystone_client.roles.grant(role, group=group, domain=domain)

    try:
        idp = keystone_client.federation.identity_providers.get(idp_name)
        logging.info('Reusing identity provider %s with id %s',
                     idp_name, idp.id)
    except keystoneauth1.exceptions.http.NotFound:
        logging.info('Creating identity provider %s', idp_name)
        idp = keystone_client.federation.identity_providers.create(
            idp_name,
            remote_ids=[idp_remote_id],
            domain_id=domain.id,
            enabled=True)

    JSON_RULES = json.loads(map_template.format(
        domain_id=domain.id, group_id=group.id, role_name=role_name))

    map_name = "{}_mapping".format(idp_name)
    try:
        keystone_client.federation.mappings.get(map_name)
        logging.info('Reusing mapping %s', map_name)
    except keystoneauth1.exceptions.http.NotFound:
        logging.info('Creating mapping %s', map_name)
        keystone_client.federation.mappings.create(
            map_name, rules=JSON_RULES)

    try:
        keystone_client.federation.protocols.get(idp_name, protocol_name)
        logging.info('Reusing protocol %s from identity provider %s',
                     protocol_name, idp_name)
    except keystoneauth1.exceptions.http.NotFound:
        logging.info(('Creating protocol %s for identity provider %s with '
                      'mapping %s'), protocol_name, idp_name, map_name)
        keystone_client.federation.protocols.create(
            protocol_name, mapping=map_name, identity_provider=idp)
