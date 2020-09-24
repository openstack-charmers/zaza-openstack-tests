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

import mock
import unittest

import zaza.openstack.charm_tests.tempest.setup as tempest_setup


class TestTempestSetup(unittest.TestCase):
    """Test class to encapsulate testing Mysql test utils."""

    def setUp(self):
        super(TestTempestSetup, self).setUp()

    def test_add_environment_var_config_with_missing_variable(self):
        ctxt = {}
        with self.assertRaises(Exception) as context:
            tempest_setup.add_environment_var_config(ctxt, ['swift'])
        self.assertEqual(
            ('Environment variables [TEST_SWIFT_IP] must all be '
             'set to run this test'),
            str(context.exception))

    @mock.patch.object(tempest_setup.deployment_env, 'get_deployment_context')
    def test_add_environment_var_config_with_all_variables(
            self,
            get_deployment_context):
        ctxt = {}
        get_deployment_context.return_value = {
            'TEST_GATEWAY': 'test',
            'TEST_CIDR_EXT': 'test',
            'TEST_FIP_RANGE': 'test',
            'TEST_NAMESERVER': 'test',
            'TEST_CIDR_PRIV': 'test',
        }
        tempest_setup.add_environment_var_config(ctxt, ['neutron'])
        self.assertEqual(ctxt['test_gateway'], 'test')

    @mock.patch.object(tempest_setup.deployment_env, 'get_deployment_context')
    def test_add_environment_var_config_with_some_variables(
            self,
            get_deployment_context):
        ctxt = {}
        get_deployment_context.return_value = {
            'TEST_GATEWAY': 'test',
            'TEST_NAMESERVER': 'test',
            'TEST_CIDR_PRIV': 'test',
        }
        with self.assertRaises(Exception) as context:
            tempest_setup.add_environment_var_config(ctxt, ['neutron'])
        self.assertEqual(
            ('Environment variables [TEST_CIDR_EXT, TEST_FIP_RANGE] must '
             'all be set to run this test'),
            str(context.exception))
