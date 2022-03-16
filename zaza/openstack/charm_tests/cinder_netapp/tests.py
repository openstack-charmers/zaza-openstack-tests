#!/usr/bin/env python3

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

"""Encapsulate cinder-netapp testing."""

import uuid

from zaza.openstack.charm_tests.cinder_backend.tests import CinderBackendTest
import zaza.openstack.utilities.openstack as openstack_utils


class CinderNetAppTest(CinderBackendTest):
    """Encapsulate netapp tests."""

    backend_name = 'cinder-netapp'

    expected_config_content = {
        'cinder-netapp': {
            'netapp_storage_family': ['ontap_cluster'],
            'netapp_storage_protocol': ['iscsi'],
            'volume_backend_name': ['NETAPP'],
            'volume_driver':
                ['cinder.volume.drivers.netapp.common.NetAppDriver'],
        }}

    def _create_volume(self, name):
        """Create a cinder volume out of a netapp flexvol."""
        vol = self.cinder_client.volumes.create(
            name=name,
            size='1')
        vol.reset_state('available')
        return vol

    def _volume_host(self, vol):
        ret = getattr(vol, 'os-vol-host-attr:host', None)
        if ret is not None:
            return ret
        # A bit more roundabout, but also works when the attribute
        # hasn't been set yet, for whatever reason.
        for service in vol.manager.api.services.list():
            if 'cinder-volume' in service.binary:
                return service.host

    def test_create_volume(self):
        """Test creating volumes with basic configuration."""
        vol_name = "zaza{}".format(uuid.uuid1().fields[0])
        vol = self._create_volume(vol_name)
        self.assertIsNotNone(vol)
        try:
            openstack_utils.resource_reaches_status(
                self.cinder_client.volumes,
                vol.id,
                wait_iteration_max_time=12000,
                stop_after_attempt=5,
                expected_status='available',
                msg='Volume status wait')
            test_vol = self.cinder_client.volumes.find(name=vol.name)
            host = self._volume_host(test_vol)
            self.assertIn('cinder-netapp', host)
        finally:
            self.cinder_client.volumes.delete(vol)
