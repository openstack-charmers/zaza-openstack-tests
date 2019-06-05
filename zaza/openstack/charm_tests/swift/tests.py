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

    @property
    def services(self):
        """List of services controlled by the charm."""
        return ['swift-proxy-server', 'haproxy', 'apache2', 'memcached']

    def get_charm_test_config_options(self):
        """Return current & alternate charm option & expected config entry."""
        current_value = zaza.model.get_application_config(
            'swift-proxy')['debug']['value']
        if bool(current_value):
            config = {
                'default': {
                    'log_entry': {'DEFAULT': {'log_level': ['DEBUG']}},
                    'charm_config': {'debug': 'True'}},
                'alternate': {
                    'log_entry': {'DEFAULT': {'log_level': ['INFO']}},
                    'charm_config': {'debug': 'False'}}}
        else:
            config = {
                'default': {
                    'log_entry': {'DEFAULT': {'log_level': ['INFO']}},
                    'charm_config': {'debug': 'False'}},
                'alternate': {
                    'log_entry': {'DEFAULT': {'log_level': ['DEBUG']}},
                    'charm_config': {'debug': 'True'}}}
        return config

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

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(self.services):
            logging.info("Testing pause resume")

    def test_920_restart_on_change(self):
        """Checking restart happens on config change.

        Change disk format and assert then change propagates to the correct
        file and that services are restarted as a result
        """
        config = self.get_charm_test_config_options()
        self.restart_on_changed(
            '/etc/swift/proxy-server.conf',
            config['default']['charm_config'],
            config['alternate']['charm_config'],
            config['default']['log_entry'],
            config['alternate']['log_entry'],
            ['swift-proxy-server'])

    def test_930_restart_on_change_paused(self):
        """Check service is not started when unit is paused."""
        config = self.get_charm_test_config_options()
        self.restart_on_changed_paused(
            config['default']['charm_config'],
            config['alternate']['charm_config'],
            ['swift-proxy-server'])

    def test_940_disk_usage_action(self):
        """Check diskusage action runs."""
        logging.info('Running diskusage action on leader')
        action = zaza.model.run_action_on_leader(
            'swift-proxy',
            'diskusage',
            action_params={})
        self.assertEqual(action.status, "completed")
