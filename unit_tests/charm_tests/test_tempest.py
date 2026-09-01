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

import os
import unittest

from unittest import mock

import zaza.openstack.charm_tests.tempest.utils as tempest_utils


class TestTempestUtils(unittest.TestCase):
    """Test class to encapsulate testing Tempest test utils."""

    def test_add_environment_var_config_with_missing_variable(self):
        ctxt = {}
        with self.assertRaises(Exception) as context:
            tempest_utils._add_environment_var_config(ctxt, ['swift'])
        self.assertEqual(
            ('Environment variables [TEST_SWIFT_IP] must all be '
             'set to run this test'),
            str(context.exception))

    @mock.patch.object(tempest_utils.deployment_env, 'get_deployment_context')
    def test_add_environment_var_config_with_all_variables(
            self,
            get_deployment_context):
        ctxt = {}
        get_deployment_context.return_value = {
            'TEST_GATEWAY': 'test',
            'TEST_CIDR_EXT': 'test',
            'TEST_FIP_RANGE': 'test',
            'TEST_NAME_SERVER': 'test',
            'TEST_CIDR_PRIV': 'test',
        }
        tempest_utils._add_environment_var_config(ctxt, ['neutron'])
        self.assertEqual(ctxt['test_gateway'], 'test')

    @mock.patch.object(tempest_utils.deployment_env, 'get_deployment_context')
    def test_add_environment_var_config_with_some_variables(
            self,
            get_deployment_context):
        ctxt = {}
        get_deployment_context.return_value = {
            'TEST_GATEWAY': 'test',
            'TEST_NAME_SERVER': 'test',
            'TEST_CIDR_PRIV': 'test',
        }
        with self.assertRaises(Exception) as context:
            tempest_utils._add_environment_var_config(ctxt, ['neutron'])
        self.assertEqual(
            ('Environment variables [TEST_CIDR_EXT, TEST_FIP_RANGE] must '
             'all be set to run this test'),
            str(context.exception))

    @mock.patch.object(tempest_utils, '_add_image_id')
    def test_add_magnum_config(self, _add_image_id):
        ctxt = {}
        keystone_session = mock.MagicMock()
        with mock.patch.dict(os.environ,
                             {'TEST_REGISTRY_PREFIX': '1.2.3.4:5000'},
                             clear=True) as environ:  # noqa:F841
            tempest_utils._add_magnum_config(ctxt, keystone_session)
            self.assertIn('test_registry_prefix', ctxt)
            self.assertEqual(ctxt['test_registry_prefix'], '1.2.3.4:5000')

        _add_image_id.assert_called()
        ctxt = {}
        with mock.patch.dict(os.environ, {},
                             clear=True) as environ:  # noqa:F841
            tempest_utils._add_magnum_config(ctxt, keystone_session)
            self.assertNotIn('test_registry_prefix', ctxt)
