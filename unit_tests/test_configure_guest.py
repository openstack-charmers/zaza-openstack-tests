# Copyright 2026 Canonical Ltd.
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

import unit_tests.utils as ut_utils

import zaza.openstack.configure.guest as guest


class TestGetDefaultUserdata(ut_utils.BaseTestCase):

    EXPECTED_NO_PACKAGES = """#cloud-config
apt:
  http_proxy: http://proxy.example.com:3128

write_files:
  - path: /etc/environment
    content: |
      http_proxy=http://proxy.example.com:3128
      https_proxy=http://proxy.example.com:3128
      no_proxy=localhost,127.0.0.1
    append: true

"""

    EXPECTED_PACKAGES = """#cloud-config
apt:
  http_proxy: http://proxy.example.com:3128

write_files:
  - path: /etc/environment
    content: |
      http_proxy=http://proxy.example.com:3128
      https_proxy=http://proxy.example.com:3128
      no_proxy=localhost,127.0.0.1
    append: true

packages:
- nfs-common
- curl
"""

    def setUp(self):
        super().setUp()
        self.patch_object(
            guest.deployment_env, 'get_deployment_context',
            return_value={
                'TEST_HTTP_PROXY': 'http://proxy.example.com:3128',
                'TEST_NO_PROXY': 'localhost,127.0.0.1',
            })

    def test_without_packages(self):
        """Test get_default_userdata without packages."""
        result = guest.get_default_userdata()
        self.assertEqual(result, self.EXPECTED_NO_PACKAGES)

    def test_with_packages(self):
        """Test get_default_userdata with multiple packages."""
        result = guest.get_default_userdata(packages=['nfs-common', 'curl'])
        self.assertEqual(result, self.EXPECTED_PACKAGES)

    def test_with_empty_packages(self):
        """Test get_default_userdata with empty packages list."""
        result = guest.get_default_userdata(packages=[])
        self.assertEqual(result, self.EXPECTED_NO_PACKAGES)

    def test_with_none_packages(self):
        """Test get_default_userdata with packages=None."""
        result = guest.get_default_userdata(packages=None)
        self.assertEqual(result, self.EXPECTED_NO_PACKAGES)
