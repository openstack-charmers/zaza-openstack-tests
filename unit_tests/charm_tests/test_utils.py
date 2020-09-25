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
        self.assertEquals(f.method({}), 'aDefault')
        self.assertEquals(f.method({
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
            'anApp', alterna_config.keys(), model_name='aModel')
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
