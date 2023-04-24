#!/usr/bin/env python3

# Copyright 2019 Canonical Ltd.
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

"""Encapsulate Cloudkitty testing."""

import logging

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils

from cloudkittyclient import client


class CloudkittyTest(test_utils.OpenStackBaseTest):
    """Encapsulate Cloudkitty tests."""

    API_VERSION = '1'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Cloudkitty tests."""
        super(CloudkittyTest, cls).setUpClass()
        cls.current_release = openstack_utils.get_os_release()

        logging.info('Instantiating cloudkitty client...')
        cls.cloudkitty = client.Client(
            CloudkittyTest.API_VERSION,
            session=cls.keystone_session
        )

    def tearDown(self):
        """Run teardown for test class."""
        rating = self.cloudkitty.rating

        if not rating.get_module(module_id='hashmap').get('enabled'):
            rating.update_module(module_id='hashmap', enabled=True)

        hashmap = rating.hashmap
        for service in hashmap.get_service().get('services'):

            service_id = service.get('service_id')

            fields = hashmap.get_field(service_id=service_id)
            for field in fields.get('fields'):
                hashmap.delete_field(field_id=field.get('field_id'))

            mappings = hashmap.get_mapping(service_id=service_id)
            for mapping in mappings.get('mappings'):
                hashmap.delete_mapping(mapping_id=mapping.get('mapping_id'))

            hashmap.delete_service(service_id=service_id)

        for group in hashmap.get_group().get('groups'):
            hashmap.delete_group(group_id=group.get('group_id'))

    def test_400_api_connection(self):
        """Simple api calls to check service is up and responding."""
        report = self.cloudkitty.report
        tenants_list = report.get_tenants()
        assert tenants_list == []

    def test_401_module_enable_and_disable(self):
        """Test enable and disable module via API."""
        rating = self.cloudkitty.rating
        modules = rating.get_module()

        for module in modules.get('modules'):
            module_id = module.get('module_id')

            # noop module can't be disabled
            if module_id == 'noop':
                continue

            logging.info('Enabling {} module'.format(module_id))
            rating.update_module(module_id=module_id, enabled=True)
            module = rating.get_module(module_id=module_id)
            assert module.get('enabled')

            logging.info('Disabling {} module'.format(module_id))
            rating.update_module(module_id=module_id, enabled=False)
            module = rating.get_module(module_id=module_id)
            assert not module.get('enabled')

    def test_402_create_mapping(self):
        """Test mapping create via API."""
        rating = self.cloudkitty.rating

        if not rating.get_module(module_id='hashmap').get('enabled'):
            rating.update_module(module_id='hashmap', enabled=True)

        hashmap = rating.hashmap

        service = hashmap.create_service(name='test-service')
        service_id = service.get('service_id')

        field = hashmap.create_field(name='test-field', service_id=service_id)
        field_id = field.get('field_id')

        group = hashmap.create_group(name='test-group')
        group_id = group.get('group_id')

        hashmap.create_mapping(
            type='flat', field_id=field_id,
            group_id=group_id, value='test-value', cost=0.1)
