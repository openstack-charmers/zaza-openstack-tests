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

"""Setup for Gnocchi tests."""

import logging

import zaza.model as model
import zaza.openstack.utilities.openstack as openstack_utils


def configure_s3_backend():
    """Inject S3 parameters from Swift for Gnocchi config."""
    session = openstack_utils.get_overcloud_keystone_session()
    ks_client = openstack_utils.get_keystone_session_client(session)

    logging.info('Retrieving S3 connection data from Swift')
    token_data = ks_client.tokens.get_token_data(session.get_token())
    project_id = token_data['token']['project']['id']
    user_id = token_data['token']['user']['id']

    # Store URL to service providing S3 compatible API
    for entry in token_data['token']['catalog']:
        if entry['type'] == 's3':
            for endpoint in entry['endpoints']:
                if endpoint['interface'] == 'public':
                    s3_region = endpoint['region']
                    s3_endpoint = endpoint['url']

    # Create AWS compatible application credentials in Keystone
    ec2_creds = ks_client.ec2.create(user_id, project_id)

    logging.info('Changing Gnocchi charm config to connect to S3')
    model.set_application_config(
        'gnocchi',
        {'s3-endpoint-url': s3_endpoint,
            's3-region-name': s3_region,
            's3-access-key-id': ec2_creds.access,
            's3-secret-access-key': ec2_creds.secret}
    )
    logging.info('Waiting for units to execute config-changed hook')
    model.wait_for_agent_status()
    logging.info('Waiting for units to reach target states')
    model.wait_for_application_states(
        states={
            'gnocchi': {
                'workload-status-': 'active',
                'workload-status-message': 'Unit is ready'
            },
            'ceilometer': {
                'workload-status': 'blocked',
                'workload-status-message': 'Run the ' +
                'ceilometer-upgrade action on the leader ' +
                'to initialize ceilometer and gnocchi'
            }
        }
    )
    model.block_until_all_units_idle()