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

from unittest import mock

import zaza.openstack.charm_tests.test_utils as test_utils

import unit_tests.utils as ut_utils


class TestBaseCharmTest(ut_utils.BaseTestCase):

    def setUp(self):
        super(TestBaseCharmTest, self).setUp()
        self.target = test_utils.BaseCharmTest()

    def patch_target(self, attr, return_value=None):
        mocked = mock.patch.object(self.target, attr)
        self._patches[attr] = mocked
        started = mocked.start()
        started.return_value = return_value
        self._patches_start[attr] = started
        setattr(self, attr, started)

    def test_get_my_tests_options(self):

        class FakeTest(test_utils.BaseCharmTest):

            def method(self, test_config):
                self.test_config = test_config
                return self.get_my_tests_options('aKey', 'aDefault')

        f = FakeTest()
        self.assertEqual(f.method({}), 'aDefault')
        self.assertEqual(f.method({
            'tests_options': {
                'unit_tests.charm_tests.test_utils.'
                'FakeTest.method.aKey': 'aValue',
            },
        }), 'aValue')

    def test_config_change(self):
        default_config = {'fakeKey': 'testProvidedDefault'}
        alterna_config = {'fakeKey': 'testProvidedAlterna'}
        self.target.model_name = 'aModel'
        self.target.test_config = {}
        self.patch_target('config_current')
        self.config_current.return_value = default_config
        self.patch_object(test_utils.model, 'set_application_config')
        self.patch_object(test_utils.model, 'wait_for_agent_status')
        self.patch_object(test_utils.model, 'wait_for_application_states')
        self.patch_object(test_utils.model, 'block_until_all_units_idle')
        with self.target.config_change(
                default_config, alterna_config, application_name='anApp'):
            self.set_application_config.assert_called_once_with(
                'anApp', alterna_config, model_name='aModel')
            self.wait_for_agent_status.assert_called_once_with(
                model_name='aModel')
            self.wait_for_application_states.assert_called_once_with(
                model_name='aModel', states={})
            self.block_until_all_units_idle.assert_called_once_with()
        # after yield we will have different calls than the above, measure both
        self.set_application_config.assert_has_calls([
            mock.call('anApp', alterna_config, model_name='aModel'),
            mock.call('anApp', default_config, model_name='aModel'),
        ])
        self.wait_for_application_states.assert_has_calls([
            mock.call(model_name='aModel', states={}),
            mock.call(model_name='aModel', states={}),
        ])
        self.block_until_all_units_idle.assert_has_calls([
            mock.call(),
            mock.call(),
        ])
        # confirm operation with `reset_to_charm_default`
        self.set_application_config.reset_mock()
        self.wait_for_agent_status.reset_mock()
        self.wait_for_application_states.reset_mock()
        self.patch_object(test_utils.model, 'reset_application_config')
        with self.target.config_change(
                default_config, alterna_config, application_name='anApp',
                reset_to_charm_default=True):
            self.set_application_config.assert_called_once_with(
                'anApp', alterna_config, model_name='aModel')
            # we want to assert this not to be called after yield
            self.set_application_config.reset_mock()
        self.assertFalse(self.set_application_config.called)
        self.reset_application_config.assert_called_once_with(
            'anApp', list(alterna_config.keys()), model_name='aModel')
        self.wait_for_application_states.assert_has_calls([
            mock.call(model_name='aModel', states={}),
            mock.call(model_name='aModel', states={}),
        ])
        self.block_until_all_units_idle.assert_has_calls([
            mock.call(),
            mock.call(),
        ])
        # confirm operation where both default and alternate config passed in
        # are the same. This is used to set config and not change it back.
        self.set_application_config.reset_mock()
        self.wait_for_agent_status.reset_mock()
        self.wait_for_application_states.reset_mock()
        self.reset_application_config.reset_mock()
        with self.target.config_change(
                alterna_config, alterna_config, application_name='anApp'):
            self.set_application_config.assert_called_once_with(
                'anApp', alterna_config, model_name='aModel')
            # we want to assert these not to be called after yield
            self.set_application_config.reset_mock()
            self.wait_for_agent_status.reset_mock()
            self.wait_for_application_states.reset_mock()
        self.assertFalse(self.set_application_config.called)
        self.assertFalse(self.reset_application_config.called)
        self.assertFalse(self.wait_for_agent_status.called)
        self.assertFalse(self.wait_for_application_states.called)

    def test_separate_non_string_config(self):
        intended_cfg_keys = ['foo2', 'foo3', 'foo4', 'foo5']
        current_config_mock = {
            'foo2': None,
            'foo3': 'old_bar3',
            'foo4': None,
            'foo5': 'old_bar5',
        }
        self.patch_target('config_current')
        self.config_current.return_value = current_config_mock
        non_string_type_keys = ['foo2', 'foo3', 'foo4']
        expected_result_filtered = {
            'foo3': 'old_bar3',
            'foo5': 'old_bar5',
        }
        expected_result_special = {
            'foo2': None,
            'foo4': None,
        }
        current, non_string = (
            self.target.config_current_separate_non_string_type_keys(
                non_string_type_keys, intended_cfg_keys, 'application_name')
        )

        self.assertEqual(expected_result_filtered, current)
        self.assertEqual(expected_result_special, non_string)

        self.config_current.assert_called_once_with(
            'application_name', intended_cfg_keys)

    def test_separate_special_config_None_params(self):
        current_config_mock = {
            'foo1': 'old_bar1',
            'foo2': None,
            'foo3': 'old_bar3',
            'foo4': None,
            'foo5': 'old_bar5',
        }
        self.patch_target('config_current')
        self.config_current.return_value = current_config_mock
        non_string_type_keys = ['foo2', 'foo3', 'foo4']
        expected_result_filtered = {
            'foo1': 'old_bar1',
            'foo3': 'old_bar3',
            'foo5': 'old_bar5',
        }
        expected_result_special = {
            'foo2': None,
            'foo4': None,
        }
        current, non_string = (
            self.target.config_current_separate_non_string_type_keys(
                non_string_type_keys)
        )

        self.assertEqual(expected_result_filtered, current)
        self.assertEqual(expected_result_special, non_string)

        self.config_current.assert_called_once_with(None, None)

    @mock.patch('zaza.openstack.utilities.generic.get_pkg_version')
    def test_package_version_matches(self, get_pkg_version):
        versions = ['4.3.0', '4.0.0']

        def _check_should_not_run():
            package_version = test_utils.package_version_matches(
                'hacluster', 'crmsh', versions=versions, op='eq')
            if package_version and package_version != '4.4.1':
                return
            raise Exception('should not run')

        for version in versions:
            get_pkg_version.return_value = version
            _check_should_not_run()
            get_pkg_version.reset_mock()

        get_pkg_version.return_value = '4.4.1'
        self.assertRaises(Exception, _check_should_not_run)


class TestOpenStackBaseTest(ut_utils.BaseTestCase):

    def test_setUpClass(self):
        self.patch_object(test_utils.openstack_utils, 'get_cacert')
        self.patch_object(test_utils.openstack_utils,
                          'get_overcloud_keystone_session')
        self.patch_object(test_utils.BaseCharmTest, 'setUpClass')

        class MyTestClass(test_utils.OpenStackBaseTest):
            model_name = 'deadbeef'

        MyTestClass.setUpClass('foo', 'bar')
        self.setUpClass.assert_called_with('foo', 'bar')
