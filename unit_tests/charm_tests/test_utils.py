# Copyright 2020 Canonical Ltd.
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

import unittest
import zaza.openstack.charm_tests.test_utils as test_utils

from unittest.mock import patch


class TestOpenStackBaseTest(unittest.TestCase):

    @patch.object(test_utils.openstack_utils, 'get_cacert')
    @patch.object(test_utils.openstack_utils, 'get_overcloud_keystone_session')
    @patch.object(test_utils.BaseCharmTest, 'setUpClass')
    def test_setUpClass(self, _setUpClass, _get_ovcks, _get_cacert):

        class MyTestClass(test_utils.OpenStackBaseTest):
            model_name = 'deadbeef'

        MyTestClass.setUpClass('foo', 'bar')
        _setUpClass.assert_called_with('foo', 'bar')


class TestUtils(unittest.TestCase):

    def test_format_addr(self):
        self.assertEquals('1.2.3.4', test_utils.format_addr('1.2.3.4'))
        self.assertEquals(
            '[2001:db8::42]', test_utils.format_addr('2001:db8::42'))
        with self.assertRaises(ValueError):
            test_utils.format_addr('999.999.999.999')
        with self.assertRaises(ValueError):
            test_utils.format_addr('2001:db8::g')
