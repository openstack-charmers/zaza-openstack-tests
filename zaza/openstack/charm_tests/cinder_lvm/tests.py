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


def with_conf(key, value):
    def patched(f):
        def inner(*args, **kwargs):
            prev = openstack_utils.get_application_config_option(
                'cinder-lvm', key)
            try:
                zaza.model.set_application_config('cinder-lvm', {key: value})
                zaza.model.wait_for_agent_status(model_name=None)
                return f(*args, **kwargs)
            finally:
                zaza.model.set_application_config(
                    'cinder-lvm', {key: str(prev)})
                zaza.model.wait_for_agent_status(model_name=None)
        return inner
    return patched


class CinderLVMTest(test_utils.OpenStackBaseTest):
    """Encapsulate cinder-lvm tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(CinderLVMTest, cls).setUpClass(application_name='cinder-lvm')
        cls.model_name = zaza.model.get_juju_model()
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session)

    @classmethod
    def tearDown(cls):
        volumes = cls.cinder_client.volumes
        for volume in volumes.list():
            if volume.name.startswith('zaza'):
                try:
                    volume.detach()
                    volumes.delete(volume)
                except Exception:
                    pass

    def test_cinder_config(self):
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
            'sudo cp /etc/cinder/cinder.conf /tmp/',
            model_name=self.model_name)
        zaza.model.block_until_oslo_config_entries_match(
            'cinder',
            '/tmp/cinder.conf',
            expected_contents,
            model_name=self.model_name,
            timeout=10)

    def _tst_create_volume(self):
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
        test_vol = self._tst_create_volume()
        self.assertTrue(test_vol)

        host = getattr(test_vol, 'os-vol-host-attr:host').split('#')[0]
        self.assertTrue(host.startswith('cinder@LVM'))

    @with_conf('overwrite', 'true')
    @with_conf('block-device', '/dev/vdc')
    def test_volume_overwrite(self):
        self._tst_create_volume()

    @with_conf('block-device', 'none')
    def test_device_none(self):
        self._tst_create_volume()

    @with_conf('remove-missing', 'true')
    def test_remove_missing_volume(self):
        self._tst_create_volume()

    @with_conf('remove-missing-force', 'true')
    def test_remove_missing_force(self):
        self._tst_create_volume()
