#!/usr/bin/env python3

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

"""Encapsulate cinder-backup testing."""

import logging

import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.test_utils as test_utils


class CinderBackupSwiftTest(test_utils.OpenStackBaseTest):
    """Encapsulate cinder-backup tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running cinder tests."""
        super(CinderBackupSwiftTest, cls).setUpClass()
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session)

    def test_cinder_volume_backup_create_delete(self):
        """Create volume backup and then delete it."""
        # Create volume
        logging.info('Creating volume')
        size = 1
        volume = openstack_utils.create_volume(
            self.cinder_client,
            size)
        # Create volume backup
        logging.info('Creating volume backup')
        volume_backup = openstack_utils.create_volume_backup(
            self.cinder_client,
            volume.id)
        record = openstack_utils.get_volume_backup_metadata(
            self.cinder_client,
            volume_backup.id
        )

        #Check if backup was created via Swift
        assert record['backup_service'] == 'cinder.backup.drivers.swift.SwiftBackupDriver'

        # Delete volume backup
        logging.info('Deleting volume backup')
        openstack_utils.delete_volume_backup(
            self.cinder_client,
            volume_backup.id)
        logging.info('Deleting volume')
        openstack_utils.delete_volume(self.cinder_client, volume.id)
