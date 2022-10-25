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

"""Encapsulate ``octavia-diskimage-retrofit`` testing."""
import logging

import distro_info
import zaza.model

import zaza.openstack.utilities.openstack as openstack
import zaza.openstack.charm_tests.test_utils as test_utils


class OctaviaDiskimageRetrofitTest(test_utils.OpenStackBaseTest):
    """Encapsulate ``octavia-diskimage-retrofit`` tests.

    Note that a full end to end test is performed by using the
    ``octavia-diskimage-retrofit`` charm for building amphora image
    used in the ``octavia`` charm functional tests.
    """

    def test_retrofit_image(self):
        """Run ``retrofit-image`` action."""
        action = zaza.model.run_action(
            'octavia-diskimage-retrofit/0',
            'retrofit-image',
            action_params={})
        self.assertEqual(action.status, 'completed')
        logging.info('Run it again, expect failure')
        action = zaza.model.run_action(
            'octavia-diskimage-retrofit/0',
            'retrofit-image',
            action_params={})
        self.assertEqual(action.status, 'failed')
        logging.info('Run it again, with force')
        action = zaza.model.run_action(
            'octavia-diskimage-retrofit/0',
            'retrofit-image',
            action_params={'force': True})
        self.assertEqual(action.status, 'completed')

    def _check_retrofit_image_source_image(self, filters):
        session = openstack.get_overcloud_keystone_session()
        glance = openstack.get_glance_session_client(session)

        for image in glance.images.list(filters=filters):
            logging.info('Image found %s with filters %s', image.id, str(filters))
            action = zaza.model.run_action(
                'octavia-diskimage-retrofit/0',
                'retrofit-image',
                action_params={'source-image': image.id})
            self.assertEqual(action.status, 'completed')
            break

    def test_retrofit_image_source_image(self):
        """Run ``retrofit-image`` action specifying an LTS as source image."""
        distro = distro_info.UbuntuDistroInfo()
        for version in distro.supported(result="object"):
            if not distro.is_lts(version.series):
                # skip non-LTS releases
                continue

            # distro.version for the LTS releases has the LTS suffix
            os_version = distro.version.replace(' LTS', '')
            logging.info('Testing retrofit-image action with ubuntu %s', os_version)
            self._check_retrofit_image_source_image(
                {'os_distro': 'ubuntu',
                 'os_version': os_version}
            )
