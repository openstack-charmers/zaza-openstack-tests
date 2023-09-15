#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
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

"""Encapsulate cinder backend tests."""

import uuid

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class CinderBackendTest(test_utils.OpenStackBaseTest):
    """Encapsulate cinder backend tests."""

    expected_config_content = {}
    backend_name = ""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(CinderBackendTest, cls).setUpClass()
        cls.keystone_session = openstack_utils.get_overcloud_keystone_session()
        cls.model_name = zaza.model.get_juju_model()
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session)

    def test_cinder_config(self):
        """Test that configuration options match our expectations."""
        zaza.model.run_on_leader(
            'cinder',
            'sudo cp /etc/cinder/cinder.conf /tmp/')
        zaza.model.block_until_oslo_config_entries_match(
            'cinder',
            '/tmp/cinder.conf',
            self.expected_config_content,
            timeout=2)

    def check_volume_host(self, volume):
        """Validate the volume id from the expected backend.

        :param volume: Volume to check
        :type volume: cinderclient.v3.volumes.Volume
        """
        self.assertEqual(
            getattr(volume, 'os-vol-host-attr:host').split('#')[0],
            'cinder@{}'.format(self.backend_name))

    def test_create_volume(self):
        """Test creating a volume with basic configuration."""
        test_vol_name = "zaza{}".format(uuid.uuid1().fields[0])
        vol_new = self.cinder_client.volumes.create(
            name=test_vol_name,
            size='1')
        try:
            openstack_utils.resource_reaches_status(
                self.cinder_client.volumes,
                vol_new.id,
                wait_iteration_max_time=12000,
                stop_after_attempt=5,
                expected_status='available',
                msg='Volume status wait')
            test_vol = self.cinder_client.volumes.find(name=test_vol_name)
            self.check_volume_host(test_vol)
        finally:
            self.cinder_client.volumes.delete(vol_new)
