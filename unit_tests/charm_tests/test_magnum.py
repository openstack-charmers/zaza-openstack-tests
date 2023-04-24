# Copyright 2023 Canonical Ltd.
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

import os
import unittest

from unittest import mock

import zaza.openstack.charm_tests.magnum.setup as magnum_setup


class TestMagnumSetup(unittest.TestCase):

    @mock.patch.object(magnum_setup.openstack_utils,
                       'get_current_os_release_pair')
    def test_get_fedora_coreos_image_url(self, get_current_os_release_pair):
        get_current_os_release_pair.return_value = 'focal_ussuri'
        self.assertEqual(magnum_setup.FEDORA_COREOS_IMAGE['ussuri'],
                         magnum_setup.get_fedora_coreos_image_url())

        self.assertEqual(magnum_setup.FEDORA_COREOS_IMAGE['xena'],
                         magnum_setup.get_fedora_coreos_image_url('xena'))
        self.assertEqual(magnum_setup.DEFAULT_FEDORA_COREOS_IMAGE_URL,
                         magnum_setup.get_fedora_coreos_image_url('foobar'))

    @mock.patch.object(magnum_setup, 'get_fedora_coreos_image_url')
    @mock.patch.object(magnum_setup.openstack_utils,
                       'get_overcloud_keystone_session')
    @mock.patch.object(magnum_setup.openstack_utils,
                       'get_glance_session_client')
    @mock.patch.object(magnum_setup.openstack_utils,
                       'create_image')
    def test_add_image(self, create_image, get_glance_session_client,
                       get_overcloud_keystone_session,
                       get_fedora_coreos_image_url):
        image_url = 'http://example.com/image.qcow2'
        with mock.patch.dict(os.environ,
                             {'TEST_MAGNUM_QCOW2_IMAGE_URL':
                              image_url},
                             clear=True) as environ:  # noqa:F841
            magnum_setup.add_image()
            create_image.assert_called_with(
                get_glance_session_client(),
                image_url,
                magnum_setup.IMAGE_NAME,
                properties={'os_distro': magnum_setup.IMAGE_NAME}
            )
            get_fedora_coreos_image_url.assert_not_called()

        image_url = 'http://example.com/fedora-coreos.qcow2'
        get_fedora_coreos_image_url.return_value = image_url
        with mock.patch.dict(os.environ, {},
                             clear=True) as environ:  # noqa:F841
            magnum_setup.add_image()
            create_image.assert_called_with(
                get_glance_session_client(),
                image_url,
                magnum_setup.IMAGE_NAME,
                properties={'os_distro': magnum_setup.IMAGE_NAME}
            )
            get_fedora_coreos_image_url.assert_called()
