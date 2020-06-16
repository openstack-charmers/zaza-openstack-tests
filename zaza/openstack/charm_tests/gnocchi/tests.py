#!/usr/bin/env python3

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

"""Encapsulate Gnocchi testing."""

import boto3
import logging
from gnocchiclient.v1 import client as gnocchi_client

import zaza.model as model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils
from zaza.openstack.charm_tests.swift.tests import S3APITest


class GnocchiTest(test_utils.OpenStackBaseTest):
    """Encapsulate Gnocchi tests."""

    @property
    def services(self):
        """Return a list of services for the selected OpenStack release."""
        return ['haproxy', 'gnocchi-metricd', 'apache2']

    def test_200_api_connection(self):
        """Simple api calls to check service is up and responding."""
        logging.info('Instantiating gnocchi client...')
        overcloud_auth = openstack_utils.get_overcloud_auth()
        keystone = openstack_utils.get_keystone_client(overcloud_auth)
        gnocchi_ep = keystone.service_catalog.url_for(
            service_type='metric',
            interface='publicURL'
        )
        gnocchi = gnocchi_client.Client(
            session=openstack_utils.get_overcloud_keystone_session(),
            adapter_options={
                'endpoint_override': gnocchi_ep,
            }
        )

        logging.info('Checking api functionality...')
        assert(gnocchi.status.get() != [])

    def test_910_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started.
        """
        with self.pause_resume(self.services):
            logging.info("Testing pause and resume")


class GnocchiS3Test(test_utils.OpenStackBaseTest):
    """Tests for S3 storage backend"""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(GnocchiS3Test, cls).setUpClass()

        session = openstack_utils.get_overcloud_keystone_session()
        ks_client = openstack_utils.get_keystone_session_client(session)

        # Get token data so we can clean our user_id and project_id
        token_data = ks_client.tokens.get_token_data(session.get_token())
        project_id = token_data['token']['project']['id']
        user_id = token_data['token']['user']['id']

        # Store URL to service providing S3 compatible API
        for entry in token_data['token']['catalog']:
            if entry['type'] == 's3':
                for endpoint in entry['endpoints']:
                    if endpoint['interface'] == 'public':
                        cls.s3_region = endpoint['region']
                        cls.s3_endpoint = endpoint['url']

        # Create AWS compatible application credentials in Keystone
        cls.ec2_creds = ks_client.ec2.create(user_id, project_id)

    # kwargs = {
    #         'region_name': swift.s3_region,
    #         'aws_access_key_id': swift.ec2_creds.access,
    #         'aws_secret_access_key': swift.ec2_creds.secret,
    #         'endpoint_url': swift.s3_endpoint,
    #         'verify': swift.cacert,
    #     }
    
    def update_gnocchi_config_for_s3(self):
        """Update Gnocchi with the correct values for the S3 backend"""
        
        logging.debug('Changing charm setting to connect to S3')
        model.set_application_config(
            'gnocchi',
            {'s3-endpoint-url': self.s3_endpoint,
            's3-region-name': self.s3_region,
            's3-access-key-id': self.ec2_creds.access,
            's3-secret-access-key': self.ec2_creds.secret},
            model_name=self.model_name
        )
        logging.debug(
                'Waiting for units to execute config-changed hook')
        model.wait_for_agent_status(model_name=self.model_name)
        logging.debug(
                'Waiting for units to reach target states')
        model.wait_for_application_states(
            model_name=self.model_name,
            states={'gnocchi': {
                            'workload-status-': 'active',
                            'workload-status-message': 'Unit is ready'}}
        )
        model.block_until_all_units_idle()
