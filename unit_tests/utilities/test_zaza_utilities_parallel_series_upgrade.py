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

import asyncio
import mock
import unit_tests.utils as ut_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.utilities.series_upgrade as series_upgrade
import zaza.openstack.utilities.parallel_series_upgrade as upgrade_utils

FAKE_STATUS = {
    'can-upgrade-to': '',
    'charm': 'local:trusty/app-136',
    'subordinate-to': [],
    'units': {'app/0': {'leader': True,
                        'machine': '0',
                        'subordinates': {
                            'app-hacluster/0': {
                                   'charm': 'local:trusty/hacluster-0',
                                   'leader': True}}},
              'app/1': {'machine': '1',
                        'subordinates': {
                            'app-hacluster/1': {
                                   'charm': 'local:trusty/hacluster-0'}}},
              'app/2': {'machine': '2',
                        'subordinates': {
                            'app-hacluster/2': {
                                   'charm': 'local:trusty/hacluster-0'}}}}}


class Test_ParallelSeriesUpgradeSync(ut_utils.BaseTestCase):
    def setUp(self):
        super(Test_ParallelSeriesUpgradeSync, self).setUp()
        # Juju Status Object and data
        # self.juju_status = mock.MagicMock()
        # self.juju_status.applications.__getitem__.return_value = FAKE_STATUS
        # self.patch_object(upgrade_utils, "model")
        # self.model.get_status.return_value = self.juju_status

    def test_get_leader_and_non_leaders(self):
        expected = ({
            'app/0': {
                'leader': True,
                'machine': '0',
                'subordinates': {
                    'app-hacluster/0': {
                        'charm': 'local:trusty/hacluster-0',
                        'leader': True}}}}, {
            'app/1': {
                'machine': '1',
                'subordinates': {
                    'app-hacluster/1': {
                        'charm': 'local:trusty/hacluster-0'}}},
            'app/2': {
                'machine': '2',
                'subordinates': {
                    'app-hacluster/2': {
                        'charm': 'local:trusty/hacluster-0'}}}})

        self.assertEqual(
            expected,
            upgrade_utils.get_leader_and_non_leaders(FAKE_STATUS)
        )

    def test_app_config_openstack_charm(self):
        expected = {
            'origin': 'openstack-origin',
            'pause_non_leader_subordinate': True,
            'pause_non_leader_primary': True,
            'post_upgrade_functions': [],
            'pre_upgrade_functions': [],
            'post_application_upgrade_functions': [],
            'follower_first': False, }
        config = upgrade_utils.app_config('keystone')
        self.assertEqual(expected, config)

    def test_app_config_mongo(self):
        expected = {
            'origin': None,
            'pause_non_leader_subordinate': True,
            'pause_non_leader_primary': True,
            'post_upgrade_functions': [],
            'pre_upgrade_functions': [],
            'post_application_upgrade_functions': [],
            'follower_first': True, }
        config = upgrade_utils.app_config('mongodb')
        self.assertEqual(expected, config)

    def test_app_config_ceph(self):
        expected = {
            'origin': 'source',
            'pause_non_leader_subordinate': False,
            'pause_non_leader_primary': False,
            'post_upgrade_functions': [],
            'pre_upgrade_functions': [],
            'post_application_upgrade_functions': [],
            'follower_first': False, }
        config = upgrade_utils.app_config('ceph-mon')
        self.assertEqual(expected, config)

    def test_app_config_percona(self):
        expected = {
            'origin': 'source',
            'pause_non_leader_subordinate': True,
            'pause_non_leader_primary': True,
            'post_upgrade_functions': [],
            'pre_upgrade_functions': [],
            'post_application_upgrade_functions': [
                ('zaza.openstack.charm_tests.mysql.utils.'
                 'complete_cluster_series_upgrade')
            ],
            'follower_first': False, }
        config = upgrade_utils.app_config('percona-cluster')
        self.assertEqual(expected, config)


class AioTestCase(ut_utils.BaseTestCase):
    def __init__(self, methodName='runTest', loop=None):
        self.loop = loop or asyncio.get_event_loop()
        self._function_cache = {}
        super(AioTestCase, self).__init__(methodName=methodName)

    def coroutine_function_decorator(self, func):
        def wrapper(*args, **kw):
            return self.loop.run_until_complete(func(*args, **kw))
        return wrapper

    def __getattribute__(self, item):
        attr = object.__getattribute__(self, item)
        if asyncio.iscoroutinefunction(attr) and item.startswith('test_'):
            if item not in self._function_cache:
                self._function_cache[item] = (
                    self.coroutine_function_decorator(attr))
            return self._function_cache[item]
        return attr


class TestParallelSeriesUpgrade(AioTestCase):
    def setUp(self):
        super(TestParallelSeriesUpgrade, self).setUp()
        self.patch_object(series_upgrade, "async_prepare_series_upgrade")
        self.patch_object(generic_utils, 'check_call')
        # Juju Status Object and data

        self.juju_status = mock.AsyncMock()
        self.juju_status.return_value.applications.__getitem__.return_value = \
            FAKE_STATUS
        self.patch_object(upgrade_utils, "model")
        self.model.async_get_status = self.juju_status
        self.async_run_action = mock.AsyncMock()
        self.model.async_run_action = self.async_run_action

    @mock.patch.object(upgrade_utils.os_utils, 'async_set_origin')
    @mock.patch.object(upgrade_utils, 'run_post_application_upgrade_functions')
    @mock.patch.object(
        upgrade_utils.series_upgrade_utils, 'async_prepare_series_upgrade')
    @mock.patch.object(upgrade_utils.series_upgrade_utils, 'async_set_series')
    @mock.patch.object(upgrade_utils, 'maybe_pause_things')
    @mock.patch.object(upgrade_utils, 'series_upgrade_machine')
    async def test_parallel_series_upgrade(
        self,
        mock_series_upgrade_machine,
        mock_maybe_pause_things,
        mock_async_set_series,
        mock_async_prepare_series_upgrade,
        mock_post_application_upgrade_functions,
        mock_async_set_origin,
    ):
        await upgrade_utils.parallel_series_upgrade(
            'app',
            from_series='trusty',
            to_series='xenial',
        )
        mock_async_set_series.assert_called_once_with(
            'app', to_series='xenial')
        self.juju_status.assert_called()
        mock_async_prepare_series_upgrade.assert_has_calls([
            mock.call('1', to_series='xenial'),
            mock.call('2', to_series='xenial'),
            mock.call('0', to_series='xenial'),
        ])
        mock_maybe_pause_things.assert_called()
        mock_series_upgrade_machine.assert_has_calls([
            mock.call(
                '1',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
            mock.call(
                '2',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
            mock.call(
                '0',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
        ])
        mock_async_set_origin.assert_called_once_with(
            'app', 'openstack-origin')
        mock_post_application_upgrade_functions.assert_called_once_with(None)

    @mock.patch.object(upgrade_utils.os_utils, 'async_set_origin')
    @mock.patch.object(upgrade_utils, 'run_post_application_upgrade_functions')
    @mock.patch.object(
        upgrade_utils.series_upgrade_utils, 'async_prepare_series_upgrade')
    @mock.patch.object(upgrade_utils.series_upgrade_utils, 'async_set_series')
    @mock.patch.object(upgrade_utils, 'maybe_pause_things')
    @mock.patch.object(upgrade_utils, 'series_upgrade_machine')
    async def test_serial_series_upgrade(
        self,
        mock_series_upgrade_machine,
        mock_maybe_pause_things,
        mock_async_set_series,
        mock_async_prepare_series_upgrade,
        mock_post_application_upgrade_functions,
        mock_async_set_origin,
    ):
        await upgrade_utils.serial_series_upgrade(
            'app',
            from_series='trusty',
            to_series='xenial',
        )
        mock_async_set_series.assert_called_once_with(
            'app', to_series='xenial')
        self.juju_status.assert_called()
        mock_async_prepare_series_upgrade.assert_has_calls([
            mock.call('0', to_series='xenial'),
            mock.call('1', to_series='xenial'),
            mock.call('2', to_series='xenial'),
        ])
        mock_maybe_pause_things.assert_called()
        mock_series_upgrade_machine.assert_has_calls([
            mock.call(
                '0',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
            mock.call(
                '1',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
            mock.call(
                '2',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
        ])
        mock_async_set_origin.assert_called_once_with(
            'app', 'openstack-origin')
        mock_post_application_upgrade_functions.assert_called_once_with(None)

    @mock.patch.object(
        upgrade_utils.series_upgrade_utils, 'async_complete_series_upgrade')
    @mock.patch.object(upgrade_utils, 'reboot')
    @mock.patch.object(upgrade_utils, 'async_do_release_upgrade')
    @mock.patch.object(upgrade_utils, 'async_dist_upgrade')
    async def test_series_upgrade_machine(
        self,
        mock_async_dist_upgrade,
        mock_async_do_release_upgrade,
        mock_reboot,
        mock_async_complete_series_upgrade
    ):
        await upgrade_utils.series_upgrade_machine(
            '1',
            post_upgrade_functions=None,
            pre_upgrade_functions=None,
            files=None,
            workaround_script=None)
        mock_async_dist_upgrade.assert_called_once_with('1')
        mock_async_do_release_upgrade.assert_called_once_with('1')
        mock_reboot.assert_called_once_with('1')
        mock_async_complete_series_upgrade.assert_called_once_with('1')

    async def test_maybe_pause_things_primary(self):
        await upgrade_utils.maybe_pause_things(
            FAKE_STATUS,
            ['app/1', 'app/2'],
            pause_non_leader_subordinate=False,
            pause_non_leader_primary=True)
        self.async_run_action.assert_has_calls([
            mock.call('app/1', "pause", action_params={}),
            mock.call('app/2', "pause", action_params={}),
        ])

    async def test_maybe_pause_things_subordinates(self):
        await upgrade_utils.maybe_pause_things(
            FAKE_STATUS,
            ['app/1', 'app/2'],
            pause_non_leader_subordinate=True,
            pause_non_leader_primary=False)
        self.async_run_action.assert_has_calls([
            mock.call('app-hacluster/1', "pause", action_params={}),
            mock.call('app-hacluster/2', "pause", action_params={}),
        ])

    async def test_maybe_pause_things_all(self):
        await upgrade_utils.maybe_pause_things(
            FAKE_STATUS,
            ['app/1', 'app/2'],
            pause_non_leader_subordinate=True,
            pause_non_leader_primary=True)
        self.async_run_action.assert_has_calls([
            mock.call('app-hacluster/1', "pause", action_params={}),
            mock.call('app/1', "pause", action_params={}),
            mock.call('app-hacluster/2', "pause", action_params={}),
            mock.call('app/2', "pause", action_params={}),
        ])

    async def test_maybe_pause_things_none(self):
        await upgrade_utils.maybe_pause_things(
            FAKE_STATUS,
            ['app/1', 'app/2'],
            pause_non_leader_subordinate=False,
            pause_non_leader_primary=False)
        self.async_run_action.assert_not_called()

    @mock.patch.object(upgrade_utils, 'run_on_machine')
    async def test_async_do_release_upgrade(self, mock_run_on_machine):
        await upgrade_utils.async_do_release_upgrade('1')
        do_release_upgrade_cmd = (
            'yes | sudo DEBIAN_FRONTEND=noninteractive '
            'do-release-upgrade -f DistUpgradeViewNonInteractive')
        mock_run_on_machine.assert_called_once_with(
            '1', do_release_upgrade_cmd, timeout='120m'
        )

    async def test_prepare_series_upgrade(self):
        await upgrade_utils.prepare_series_upgrade(
            '1', to_series='xenial'
        )
        self.async_prepare_series_upgrade.assert_called_once_with(
            '1', to_series='xenial'
        )

    @mock.patch.object(upgrade_utils, 'run_on_machine')
    async def test_reboot(self, mock_run_on_machine):
        await upgrade_utils.reboot('1')
        mock_run_on_machine.assert_called_once_with(
            '1', 'shutdown --reboot now & exit'
        )

    async def test_run_on_machine(self):
        await upgrade_utils.run_on_machine('1', 'test')
        self.check_call.assert_called_once_with(
            ['juju', 'run', '--machine=1', 'test'])

    async def test_run_on_machine_with_timeout(self):
        await upgrade_utils.run_on_machine('1', 'test', timeout='20m')
        self.check_call.assert_called_once_with(
            ['juju', 'run', '--machine=1', '--timeout=20m', 'test'])

    async def test_run_on_machine_with_model(self):
        await upgrade_utils.run_on_machine('1', 'test', model_name='test')
        self.check_call.assert_called_once_with(
            ['juju', 'run', '--machine=1', '--model=test', 'test'])

    @mock.patch.object(upgrade_utils, 'run_on_machine')
    async def test_async_dist_upgrade(self, mock_run_on_machine):
        await upgrade_utils.async_dist_upgrade('1')
        apt_update_command = (
            """yes | sudo DEBIAN_FRONTEND=noninteractive apt --assume-yes """
            """-o "Dpkg::Options::=--force-confdef" """
            """-o "Dpkg::Options::=--force-confold" dist-upgrade""")
        mock_run_on_machine.assert_has_calls([
            mock.call('1', 'sudo apt update'),
            mock.call('1', apt_update_command),
        ])
