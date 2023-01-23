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
import sys
import unittest
import unit_tests.utils as ut_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.utilities.series_upgrade as series_upgrade
import zaza.openstack.utilities.parallel_series_upgrade as upgrade_utils
import zaza

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

FAKE_STATUS_MONGO = {
    'can-upgrade-to': '',
    'charm': 'local:trusty/mongodb-10',
    'subordinate-to': [],
    'units': {'mongo/0': {'leader': True,
                          'machine': '0',
                          'subordinates': {}},
              'mongo/1': {'machine': '1',
                          'subordinates': {}},
              'mongo/2': {'machine': '2',
                          'subordinates': {}}}}


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
            'origin': 'auto',
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


class TestParallelSeriesUpgrade(ut_utils.AioTestCase):
    def setUp(self):
        super(TestParallelSeriesUpgrade, self).setUp()
        if sys.version_info < (3, 6, 0):
            raise unittest.SkipTest("Can't AsyncMock in py35")
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

        self.async_block_until = mock.AsyncMock()
        self.model.async_block_until = self.async_block_until
        self.model.async_wait_for_unit_idle = mock.AsyncMock()
        self.async_run_on_machine = mock.AsyncMock()
        self.model.async_run_on_machine = self.async_run_on_machine
        self.model.async_block_until_units_on_machine_are_idle = \
            mock.AsyncMock()

    @mock.patch.object(upgrade_utils.cl_utils, 'get_class')
    async def test_run_post_application_upgrade_functions(
        self,
        mock_get_class
    ):
        called = mock.AsyncMock()
        mock_get_class.return_value = called
        await upgrade_utils.run_post_application_upgrade_functions(
            ['my.thing'])
        mock_get_class.assert_called_once_with('my.thing')
        called.assert_called()

    @mock.patch.object(upgrade_utils.cl_utils, 'get_class')
    async def test_run_pre_upgrade_functions(self, mock_get_class):
        called = mock.AsyncMock()
        mock_get_class.return_value = called
        await upgrade_utils.run_pre_upgrade_functions('1', ['my.thing'])
        mock_get_class.assert_called_once_with('my.thing')
        called.assert_called_once_with('1')

    @mock.patch.object(upgrade_utils, 'run_post_application_upgrade_functions')
    @mock.patch.object(
        upgrade_utils.series_upgrade_utils, 'async_prepare_series_upgrade')
    @mock.patch.object(upgrade_utils.series_upgrade_utils, 'async_set_series')
    @mock.patch.object(upgrade_utils, 'maybe_pause_things')
    @mock.patch.object(upgrade_utils, 'series_upgrade_machine')
    async def test_async_parallel_series_upgrade_mongo(
        self,
        mock_series_upgrade_machine,
        mock_maybe_pause_things,
        mock_async_set_series,
        mock_async_prepare_series_upgrade,
        mock_post_application_upgrade_functions,
    ):
        self.juju_status.return_value.applications.__getitem__.return_value = \
            FAKE_STATUS_MONGO
        upgrade_config = upgrade_utils.app_config('mongodb')
        await upgrade_utils.async_parallel_series_upgrade(
            'mongodb',
            from_series='trusty',
            to_series='xenial',
            **upgrade_config
        )
        mock_async_set_series.assert_called_once_with(
            'mongodb', to_series='xenial')
        self.juju_status.assert_called()

        # The below is using `any_order=True` because the ordering is
        # undetermined and differs between python versions
        mock_async_prepare_series_upgrade.assert_has_calls([
            mock.call('1', to_series='xenial'),
            mock.call('2', to_series='xenial'),
            mock.call('0', to_series='xenial'),
        ], any_order=True)
        mock_maybe_pause_things.assert_called()
        mock_series_upgrade_machine.assert_has_calls([
            mock.call(
                '1',
                origin=None,
                application='mongodb',
                files=None,
                workaround_script=None,
                post_upgrade_functions=[]),
            mock.call(
                '2',
                origin=None,
                application='mongodb',
                files=None,
                workaround_script=None,
                post_upgrade_functions=[]),
            mock.call(
                '0',
                origin=None,
                application='mongodb',
                files=None,
                workaround_script=None,
                post_upgrade_functions=[]),
        ])
        mock_post_application_upgrade_functions.assert_called_once_with([])

    @mock.patch.object(upgrade_utils, 'run_post_application_upgrade_functions')
    @mock.patch.object(
        upgrade_utils.series_upgrade_utils, 'async_prepare_series_upgrade')
    @mock.patch.object(upgrade_utils.series_upgrade_utils, 'async_set_series')
    @mock.patch.object(upgrade_utils, 'maybe_pause_things')
    @mock.patch.object(upgrade_utils, 'series_upgrade_machine')
    async def test_async_serial_series_upgrade_mongo(
        self,
        mock_series_upgrade_machine,
        mock_maybe_pause_things,
        mock_async_set_series,
        mock_async_prepare_series_upgrade,
        mock_post_application_upgrade_functions,
    ):
        self.juju_status.return_value.applications.__getitem__.return_value = \
            FAKE_STATUS_MONGO
        upgrade_config = upgrade_utils.app_config('mongodb')
        await upgrade_utils.async_serial_series_upgrade(
            'mongodb',
            from_series='trusty',
            to_series='xenial',
            **upgrade_config
        )
        mock_async_set_series.assert_called_once_with(
            'mongodb', to_series='xenial')
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
                origin=None,
                application='mongodb',
                files=None,
                workaround_script=None,
                post_upgrade_functions=[]),
            mock.call(
                '2',
                origin=None,
                application='mongodb',
                files=None,
                workaround_script=None,
                post_upgrade_functions=[]),
            mock.call(
                '0',
                origin=None,
                application='mongodb',
                files=None,
                workaround_script=None,
                post_upgrade_functions=[]),
        ])
        mock_post_application_upgrade_functions.assert_called_once_with([])

    @mock.patch.object(upgrade_utils, 'run_post_application_upgrade_functions')
    @mock.patch.object(
        upgrade_utils.series_upgrade_utils, 'async_prepare_series_upgrade')
    @mock.patch.object(upgrade_utils.series_upgrade_utils, 'async_set_series')
    @mock.patch.object(upgrade_utils, 'maybe_pause_things')
    @mock.patch.object(upgrade_utils, 'series_upgrade_machine')
    async def test_async_parallel_series_upgrade(
        self,
        mock_series_upgrade_machine,
        mock_maybe_pause_things,
        mock_async_set_series,
        mock_async_prepare_series_upgrade,
        mock_post_application_upgrade_functions,
    ):
        await upgrade_utils.async_parallel_series_upgrade(
            'app',
            from_series='trusty',
            to_series='xenial',
        )
        mock_async_set_series.assert_called_once_with(
            'app', to_series='xenial')
        self.juju_status.assert_called()
        # The below is using `any_order=True` because the ordering is
        # undetermined and differs between python versions
        mock_async_prepare_series_upgrade.assert_has_calls([
            mock.call('1', to_series='xenial'),
            mock.call('2', to_series='xenial'),
            mock.call('0', to_series='xenial'),
        ], any_order=True)
        mock_maybe_pause_things.assert_called()
        mock_series_upgrade_machine.assert_has_calls([
            mock.call(
                '1',
                origin='openstack-origin',
                application='app',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
            mock.call(
                '2',
                origin='openstack-origin',
                application='app',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
            mock.call(
                '0',
                origin='openstack-origin',
                application='app',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
        ])
        mock_post_application_upgrade_functions.assert_called_once_with(None)

    @mock.patch.object(upgrade_utils, 'run_post_application_upgrade_functions')
    @mock.patch.object(
        upgrade_utils.series_upgrade_utils, 'async_prepare_series_upgrade')
    @mock.patch.object(upgrade_utils.series_upgrade_utils, 'async_set_series')
    @mock.patch.object(upgrade_utils, 'maybe_pause_things')
    @mock.patch.object(upgrade_utils, 'series_upgrade_machine')
    async def test_async_serial_series_upgrade(
        self,
        mock_series_upgrade_machine,
        mock_maybe_pause_things,
        mock_async_set_series,
        mock_async_prepare_series_upgrade,
        mock_post_application_upgrade_functions,
    ):
        await upgrade_utils.async_serial_series_upgrade(
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
                origin='openstack-origin',
                application='app',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
            mock.call(
                '1',
                origin='openstack-origin',
                application='app',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
            mock.call(
                '2',
                origin='openstack-origin',
                application='app',
                files=None,
                workaround_script=None,
                post_upgrade_functions=None),
        ])
        mock_post_application_upgrade_functions.assert_called_once_with(None)

    @mock.patch.object(upgrade_utils, 'add_confdef_file')
    @mock.patch.object(upgrade_utils, 'remove_confdef_file')
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
        mock_async_complete_series_upgrade,
        mock_remove_confdef_file,
        mock_add_confdef_file
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
        mock_remove_confdef_file.assert_called_once_with('1')
        mock_add_confdef_file.assert_called_once_with('1')

    @mock.patch.object(upgrade_utils, 'add_confdef_file')
    @mock.patch.object(upgrade_utils, 'remove_confdef_file')
    @mock.patch.object(upgrade_utils.os_utils, 'async_set_origin')
    @mock.patch.object(
        upgrade_utils.series_upgrade_utils, 'async_complete_series_upgrade')
    @mock.patch.object(upgrade_utils, 'reboot')
    @mock.patch.object(upgrade_utils, 'async_do_release_upgrade')
    @mock.patch.object(upgrade_utils, 'async_dist_upgrade')
    async def test_series_upgrade_machine_with_source(
        self,
        mock_async_dist_upgrade,
        mock_async_do_release_upgrade,
        mock_reboot,
        mock_async_complete_series_upgrade,
        mock_async_set_origin,
        mock_remove_confdef_file,
        mock_add_confdef_file
    ):
        await upgrade_utils.series_upgrade_machine(
            '1',
            origin='openstack-origin',
            application='app',
            post_upgrade_functions=None,
            pre_upgrade_functions=None,
            files=None,
            workaround_script=None)
        mock_async_dist_upgrade.assert_called_once_with('1')
        mock_async_do_release_upgrade.assert_called_once_with('1')
        mock_reboot.assert_called_once_with('1')
        mock_async_complete_series_upgrade.assert_called_once_with('1')
        mock_async_set_origin.assert_called_once_with(
            'app', 'openstack-origin')
        mock_remove_confdef_file.assert_called_once_with('1')
        mock_add_confdef_file.assert_called_once_with('1')

    @mock.patch.object(zaza.model, "async_run_action")
    @mock.patch.object(zaza.model, "async_get_application")
    @mock.patch("asyncio.gather")
    async def test_maybe_pause_things_primary(
        self, mock_gather, mock_async_get_application, mock_async_run_action
    ):
        if sys.version_info < (3, 6, 0):
            raise unittest.SkipTest("Can't AsyncMock in py35")

        async def _gather(*args):
            for f in args:
                await f

        mock_app = mock.AsyncMock()
        mock_app.get_actions.return_value = ["pause", "resume"]
        mock_async_get_application.return_value = mock_app

        mock_gather.side_effect = _gather
        await upgrade_utils.maybe_pause_things(
            FAKE_STATUS,
            ['app/1', 'app/2'],
            pause_non_leader_subordinate=False,
            pause_non_leader_primary=True)
        mock_async_run_action.assert_has_calls([
            mock.call('app/1', "pause", action_params={}),
            mock.call('app/2', "pause", action_params={}),
        ])

    @mock.patch.object(zaza.model, "async_run_action")
    @mock.patch.object(zaza.model, "async_get_application")
    @mock.patch("asyncio.gather")
    async def test_maybe_pause_things_subordinates(
        self, mock_gather, mock_async_get_application, mock_async_run_action
    ):
        if sys.version_info < (3, 6, 0):
            raise unittest.SkipTest("Can't AsyncMock in py35")

        async def _gather(*args):
            for f in args:
                await f

        mock_app = mock.AsyncMock()
        mock_app.get_actions.return_value = ["pause", "resume"]
        mock_async_get_application.return_value = mock_app

        mock_gather.side_effect = _gather
        await upgrade_utils.maybe_pause_things(
            FAKE_STATUS,
            ['app/1', 'app/2'],
            pause_non_leader_subordinate=True,
            pause_non_leader_primary=False)
        mock_async_run_action.assert_has_calls([
            mock.call('app-hacluster/1', "pause", action_params={}),
            mock.call('app-hacluster/2', "pause", action_params={}),
        ])

    @mock.patch.object(zaza.model, "async_run_action")
    @mock.patch.object(zaza.model, "async_get_application")
    @mock.patch("asyncio.gather")
    async def test_maybe_pause_things_all(
        self, mock_gather, mock_async_get_application, mock_async_run_action
    ):
        if sys.version_info < (3, 6, 0):
            raise unittest.SkipTest("Can't AsyncMock in py35")

        async def _gather(*args):
            for f in args:
                await f

        mock_app = mock.AsyncMock()
        mock_app.get_actions.return_value = ["pause", "resume"]
        mock_async_get_application.return_value = mock_app

        mock_gather.side_effect = _gather
        await upgrade_utils.maybe_pause_things(
            FAKE_STATUS,
            ['app/1', 'app/2'],
            pause_non_leader_subordinate=True,
            pause_non_leader_primary=True)
        mock_async_run_action.assert_has_calls([
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

    async def test_add_confdef_file(self):
        await upgrade_utils.add_confdef_file('1')
        cmd = (
            """echo """
            """'DPkg::options { "--force-confdef"; "--force-confnew"; }' | """
            """sudo tee /etc/apt/apt.conf.d/local"""
        )
        self.async_run_on_machine.assert_called_once_with(
            '1', cmd
        )

    async def test_remove_confdef_file(self):
        await upgrade_utils.remove_confdef_file('1')
        self.async_run_on_machine.assert_called_once_with(
            '1', 'sudo rm /etc/apt/apt.conf.d/local'
        )

    async def test_async_do_release_upgrade(self):
        await upgrade_utils.async_do_release_upgrade('1')
        do_release_upgrade_cmd = (
            'yes | sudo DEBIAN_FRONTEND=noninteractive '
            'do-release-upgrade -f DistUpgradeViewNonInteractive')
        self.async_run_on_machine.assert_called_once_with(
            '1', do_release_upgrade_cmd, timeout='120m'
        )

    async def test_prepare_series_upgrade(self):
        await upgrade_utils.prepare_series_upgrade(
            '1', to_series='xenial'
        )
        self.async_prepare_series_upgrade.assert_called_once_with(
            '1', to_series='xenial'
        )

    async def test_reboot(self):
        await upgrade_utils.reboot('1')
        self.async_run_on_machine.assert_called_once_with(
            '1', 'sudo init 6 & exit'
        )

    async def test_async_dist_upgrade(self):
        await upgrade_utils.async_dist_upgrade('1')
        apt_update_command = (
            """yes | sudo DEBIAN_FRONTEND=noninteractive """
            """apt-get --assume-yes """
            """-o "Dpkg::Options::=--force-confdef" """
            """-o "Dpkg::Options::=--force-confold" dist-upgrade""")
        self.async_run_on_machine.assert_has_calls([
            mock.call('1', 'sudo apt-get update'),
            mock.call('1', apt_update_command),
        ])
