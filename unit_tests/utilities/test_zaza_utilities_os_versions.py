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


import unit_tests.utils as ut_utils
from zaza.openstack.utilities import os_versions


class TestOpenStackUtils(ut_utils.BaseTestCase):

    def test_compare_openstack(self):
        antelope = os_versions.CompareOpenStack('antelope')
        zed = os_versions.CompareOpenStack('zed')
        yoga = os_versions.CompareOpenStack('yoga')
        self.assertGreater(antelope, zed)
        self.assertLess(zed, antelope)
        self.assertGreaterEqual(zed, zed)
        self.assertGreaterEqual(antelope, yoga)
        self.assertGreaterEqual(zed, yoga)

        self.assertEqual("CompareOpenStack<zed>", repr(zed))
