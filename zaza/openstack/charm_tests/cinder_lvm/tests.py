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

"""Encapsulate cinder-lvm testing."""

import logging
import uuid

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class CinderLVMTest(test_utils.OpenStackBaseTest):
    """Encapsulate cinder-lvm tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(CinderLVMTest, cls).setUpClass(application_name='cinder-lvm')
        cls.model_name = zaza.model.get_juju_model()
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session)
        cls.block_device = openstack_utils.get_application_config_option(
            'cinder-lvm', 'block-device', model_name=cls.model_name)

    @classmethod
    def tearDown(cls):
        """Remove test resources."""
        volumes = cls.cinder_client.volumes
        for volume in volumes.list():
            if volume.name.startswith('zaza'):
                try:
                    volume.detach()
                    volumes.delete(volume)
                except Exception:
                    pass

    def test_cinder_config(self):
        """Test that configuration options match our expectations."""
        logging.info('cinder-lvm')
        expected_contents = {
            'LVM-zaza-lvm': {
                'volume_clear': ['zero'],
                'volumes_dir': ['/var/lib/cinder/volumes'],
                'volume_name_template': ['volume-%s'],
                'volume_clear_size': ['0'],
                'volume_driver': ['cinder.volume.drivers.lvm.LVMVolumeDriver'],
            }}

        zaza.model.run_on_leader(
            'cinder',
            'sudo cp /etc/cinder/cinder.conf /tmp/')
        zaza.model.block_until_oslo_config_entries_match(
            'cinder',
            '/tmp/cinder.conf',
            expected_contents,
            timeout=10)

    def _create_volume(self):
        """Create a volume via the LVM backend."""
        test_vol_name = "zaza{}".format(uuid.uuid1().fields[0])
        vol_new = self.cinder_client.volumes.create(
            name=test_vol_name,
            size='1')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            wait_iteration_max_time=12000,
            stop_after_attempt=5,
            expected_status='available',
            msg='Volume status wait')
        return self.cinder_client.volumes.find(name=test_vol_name)

    def test_create_volume(self):
        """Test creating a volume with basic configuration."""
        test_vol = self._create_volume()
        self.assertTrue(test_vol)

        host = getattr(test_vol, 'os-vol-host-attr:host').split('#')[0]
        self.assertTrue(host.startswith('cinder@LVM'))

    def test_volume_overwrite(self):
        """Test creating a volume by overwriting one on a loop device."""
        with self.config_change({'overwrite': 'false',
                                 'block-device': self.block_device},
                                {'overwrite': 'true',
                                 'block-device': '/tmp/vol|2G'}):
            self._create_volume()

    def test_device_none(self):
        """Test creating a volume in a dummy device (set as 'none')."""
        with self.config_change({'block-device': self.block_device},
                                {'block-device': 'none'}):
            self._create_volume()

    def test_remove_missing_volume(self):
        """Test creating a volume after remove missing ones in a group."""
        with self.config_change({'remove-missing': 'false'},
                                {'remove-missing': 'true'}):
            self._create_volume()

    def test_remove_missing_force(self):
        """Test creating a volume by forcefully removing missing ones."""
        with self.config_change({'remove-missing-force': 'false'},
                                {'remove-missing-force': 'true'}):
            self._create_volume()
