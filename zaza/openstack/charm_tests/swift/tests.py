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

"""Encapsulate swift testing."""

import logging

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.configure.guest
import zaza.openstack.utilities.openstack as openstack_utils


class SwiftImageCreateTest(test_utils.OpenStackBaseTest):
    """Test swift proxy via glance."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(SwiftImageCreateTest, cls).setUpClass()
        cls.image_name = 'zaza-swift-lts'
        swift_session = openstack_utils.get_keystone_session_from_relation(
            'swift-proxy')

        cls.swift = openstack_utils.get_swift_session_client(
            swift_session)
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session)

    def test_100_create_image(self):
        """Create an image and do simple validation of image in swift."""
        glance_setup.add_lts_image(image_name=self.image_name)
        headers, containers = self.swift.get_account()
        self.assertEqual(len(containers), 1)
        container_name = containers[0].get('name')
        headers, objects = self.swift.get_container(container_name)
        images = openstack_utils.get_images_by_name(
            self.glance_client,
            self.image_name)
        self.assertEqual(len(images), 1)
        image = images[0]
        total_bytes = 0
        for ob in objects:
            if '{}-'.format(image['id']) in ob['name']:
                total_bytes = total_bytes + int(ob['bytes'])
        logging.info(
            'Checking glance image size {} matches swift '
            'image size {}'.format(image['size'], total_bytes))
        self.assertEqual(image['size'], total_bytes)
        openstack_utils.delete_image(self.glance_client, image['id'])

class SwiftProxyTests(test_utils.OpenStackBaseTest):

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(['swift-proxy-server', 'haproxy', 'apache2',
                                'memcached']):
            logging.info("Testing pause resume")

    def test_903_disk_usage_action(self):
        """Check diskusage action runs."""
        logging.info('Running diskusage action on leader')
        action = zaza.model.run_action_on_leader(
            'swift-proxy',
            'diskusage',
            action_params={})
        self.assertEqual(action.status, "completed")

class SwiftStorageTests(test_utils.OpenStackBaseTest):

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        services = ['swift-account-server',
                    'swift-account-auditor',
                    'swift-account-reaper',
                    'swift-account-replicator',
                    'swift-container-server',
                    'swift-container-auditor',
                    'swift-container-replicator',
                    'swift-container-updater',
                    'swift-object-server',
                    'swift-object-auditor',
                    'swift-object-replicator',
                    'swift-object-updater',
                    'swift-container-sync']
        with self.pause_resume(services):
            logging.info("Testing pause resume")
