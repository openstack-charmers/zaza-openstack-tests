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

"""Encapsulate cinder-netapp testing."""

import zaza.model
from zaza.openstack.charm_tests.cinder_backend.tests import CinderBackendTest


class CinderNetAppTest(CinderBackendTest):
    """Encapsulate netapp tests."""

    configs = zaza.model.get_application_config("cinder-netapp")
    family = configs['netapp-storage-family']['value']
    protocol = configs['netapp-storage-protocol']['value']
    backend_name = configs['volume-backend-name']['value']
    expected_contents = {
        'cinder-netapp': {
            'netapp_storage_family': [family],
            'netapp_storage_protocol': [protocol],
            'volume_backend_name': [backend_name],
            'volume_driver':
                ['cinder.volume.drivers.netapp.common.NetAppDriver'],
        }}

    def check_volume_host(self, volume):
        """Validate the volume id from the expected backend.

        :param volume: Volume to check
        :type volume: cinderclient.v3.volumes.Volume
        """
        host = getattr(volume, 'os-vol-host-attr:host')
        self.assertEqual(
            host.split('#')[0].split('@')[1],
            'cinder-netapp')
