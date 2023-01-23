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
import sys
import unittest
import unit_tests.utils as ut_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.utilities.series_upgrade as series_upgrade_utils

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


class TestSeriesUpgrade(ut_utils.BaseTestCase):
    def setUp(self):
        super(TestSeriesUpgrade, self).setUp()
        # Patch all subprocess calls
        self.patch(
            'zaza.openstack.utilities.generic.subprocess',
            new_callable=mock.MagicMock(),
            name='subprocess'
        )
        self.patch_object(generic_utils, "run_via_ssh")
        # Juju Status Object and data
        self.juju_status = mock.MagicMock()
        self.juju_status.applications.__getitem__.return_value = FAKE_STATUS
        self.patch_object(series_upgrade_utils, "model")
        self.model.get_status.return_value = self.juju_status

    def test_series_upgrade(self):
        self.patch_object(
            series_upgrade_utils.model, "block_until_all_units_idle")
        self.patch_object(
            series_upgrade_utils.model, "block_until_unit_wl_status")
        self.patch_object(series_upgrade_utils.model, "prepare_series_upgrade")
        self.patch_object(
            series_upgrade_utils.model, "complete_series_upgrade")
        self.patch_object(series_upgrade_utils.model, "set_series")
        self.patch_object(generic_utils, "set_origin")
        self.patch_object(series_upgrade_utils, "wrap_do_release_upgrade")
        self.patch_object(generic_utils, "reboot")
        _unit = "app/2"
        _application = "app"
        _machine_num = "4"
        _from_series = "xenial"
        _to_series = "bionic"
        _origin = "source"
        _files = ["filename", "scriptname"]
        _workaround_script = "scriptname"
        series_upgrade_utils.series_upgrade(
            _unit, _machine_num, origin=_origin,
            to_series=_to_series, from_series=_from_series,
            workaround_script=_workaround_script, files=_files)
        self.block_until_all_units_idle.assert_called()
        self.prepare_series_upgrade.assert_called_once_with(
            _machine_num, to_series=_to_series)
        self.wrap_do_release_upgrade.assert_called_once_with(
            _unit, to_series=_to_series, from_series=_from_series,
            workaround_script=_workaround_script, files=_files)
        self.complete_series_upgrade.assert_called_once_with(_machine_num)
        self.set_series.assert_called_once_with(_application, _to_series)
        self.set_origin.assert_called_once_with(_application, _origin)
        self.reboot.assert_called_once_with(_unit)

    def _mock_app(self):
        if sys.version_info < (3, 6, 0):
            raise unittest.SkipTest("Can't AsyncMock in py35")
        mock_get_action = mock.AsyncMock()
        mock_get_action.get_actions.return_value = ["pause", "resume"]
        mock_app = asyncio.Future()
        mock_app.set_result(mock_get_action)
        return mock_app

    def test_series_upgrade_application_pause_peers_and_subordinates(self):
        self.patch_object(series_upgrade_utils.model, "async_run_action")
        self.patch_object(series_upgrade_utils, "series_upgrade")
        self.patch_object(series_upgrade_utils.model, "async_get_application")
        _application = "app"
        _from_series = "xenial"
        _to_series = "bionic"
        _origin = "source"
        _files = ["filename", "scriptname"]
        _workaround_script = "scriptname"
        _completed_machines = []
        # Peers and Subordinates
        _run_action_calls = [
            mock.call("{}-hacluster/1".format(_application),
                      "pause", action_params={}),
            mock.call("{}/1".format(_application), "pause", action_params={}),
            mock.call("{}-hacluster/2".format(_application),
                      "pause", action_params={}),
            mock.call("{}/2".format(_application), "pause", action_params={}),
        ]
        _series_upgrade_calls = []
        self.async_get_application.return_value = self._mock_app()
        self.async_run_action.return_value = self._mock_app()
        for machine_num in ("0", "1", "2"):
            _series_upgrade_calls.append(
                mock.call("{}/{}".format(_application, machine_num),
                          machine_num, origin=_origin,
                          from_series=_from_series, to_series=_to_series,
                          workaround_script=_workaround_script, files=_files,
                          post_upgrade_functions=None),
            )

        # Pause primary peers and subordinates
        series_upgrade_utils.series_upgrade_application(
            _application, origin=_origin,
            to_series=_to_series, from_series=_from_series,
            pause_non_leader_primary=True,
            pause_non_leader_subordinate=True,
            completed_machines=_completed_machines,
            workaround_script=_workaround_script, files=_files),
        self.async_run_action.assert_has_calls(_run_action_calls)
        self.series_upgrade.assert_has_calls(_series_upgrade_calls)

    def test_series_upgrade_application_pause_subordinates(self):
        self.patch_object(series_upgrade_utils.model, "async_run_action")
        self.patch_object(series_upgrade_utils, "series_upgrade")
        self.patch_object(series_upgrade_utils.model, "async_get_application")
        _application = "app"
        _from_series = "xenial"
        _to_series = "bionic"
        _origin = "source"
        _files = ["filename", "scriptname"]
        _workaround_script = "scriptname"
        _completed_machines = []
        # Subordinates only
        _run_action_calls = [
            mock.call("{}-hacluster/1".format(_application),
                      "pause", action_params={}),
            mock.call("{}-hacluster/2".format(_application),
                      "pause", action_params={}),
        ]
        _series_upgrade_calls = []
        self.async_get_application.return_value = self._mock_app()
        self.async_run_action.return_value = self._mock_app()
        for machine_num in ("0", "1", "2"):
            _series_upgrade_calls.append(
                mock.call("{}/{}".format(_application, machine_num),
                          machine_num, origin=_origin,
                          from_series=_from_series, to_series=_to_series,
                          workaround_script=_workaround_script, files=_files,
                          post_upgrade_functions=None),
            )

        # Pause subordinates
        series_upgrade_utils.series_upgrade_application(
            _application, origin=_origin,
            to_series=_to_series, from_series=_from_series,
            pause_non_leader_primary=False,
            pause_non_leader_subordinate=True,
            completed_machines=_completed_machines,
            workaround_script=_workaround_script, files=_files),
        self.async_run_action.assert_has_calls(_run_action_calls)
        self.series_upgrade.assert_has_calls(_series_upgrade_calls)

    def test_series_upgrade_application_no_pause(self):
        self.patch_object(series_upgrade_utils.model, "run_action")
        self.patch_object(series_upgrade_utils, "series_upgrade")
        _application = "app"
        _from_series = "xenial"
        _to_series = "bionic"
        _origin = "source"
        _series_upgrade_calls = []
        _files = ["filename", "scriptname"]
        _workaround_script = "scriptname"
        _completed_machines = []

        for machine_num in ("0", "1", "2"):
            _series_upgrade_calls.append(
                mock.call("{}/{}".format(_application, machine_num),
                          machine_num, origin=_origin,
                          from_series=_from_series, to_series=_to_series,
                          workaround_script=_workaround_script, files=_files,
                          post_upgrade_functions=None),
            )

        # No Pausiing
        series_upgrade_utils.series_upgrade_application(
            _application, origin=_origin,
            to_series=_to_series, from_series=_from_series,
            pause_non_leader_primary=False,
            pause_non_leader_subordinate=False,
            completed_machines=_completed_machines,
            workaround_script=_workaround_script, files=_files)
        self.run_action.assert_not_called()
        self.series_upgrade.assert_has_calls(_series_upgrade_calls)

    def test_dist_upgrade(self):
        _unit = "app/2"
        series_upgrade_utils.dist_upgrade(_unit)
        dist_upgrade_cmd = (
            """sudo DEBIAN_FRONTEND=noninteractive apt --assume-yes """
            """-o "Dpkg::Options::=--force-confdef" """
            """-o "Dpkg::Options::=--force-confold" dist-upgrade""")
        self.model.run_on_unit.assert_has_calls([
            mock.call(_unit, 'sudo apt update'),
            mock.call(_unit, dist_upgrade_cmd)])

    def test_do_release_upgrade(self):
        _unit = "app/2"
        series_upgrade_utils.do_release_upgrade(_unit)
        self.run_via_ssh.assert_called_once_with(
            _unit,
            'DEBIAN_FRONTEND=noninteractive do-release-upgrade '
            '-f DistUpgradeViewNonInteractive')

    def test_wrap_do_release_upgrade(self):
        self.patch_object(series_upgrade_utils, "do_release_upgrade")
        self.patch_object(series_upgrade_utils.model, "scp_to_unit")
        _unit = "app/2"
        _from_series = "xenial"
        _to_series = "bionic"
        _workaround_script = "scriptname"
        _files = ["filename", _workaround_script]
        _scp_calls = []
        _run_calls = [
            mock.call(_unit, _workaround_script)]
        for filename in _files:
            _scp_calls.append(mock.call(_unit, filename, filename))
        series_upgrade_utils.wrap_do_release_upgrade(
            _unit, to_series=_to_series, from_series=_from_series,
            workaround_script=_workaround_script, files=_files)
        self.scp_to_unit.assert_has_calls(_scp_calls)
        self.run_via_ssh.assert_has_calls(_run_calls)
        self.do_release_upgrade.assert_called_once_with(_unit)

    def test_app_config_openstack_charm(self):
        upgrade = series_upgrade_utils.async_series_upgrade_application
        expected = {
            'origin': 'openstack-origin',
            'pause_non_leader_subordinate': True,
            'pause_non_leader_primary': True,
            'upgrade_function': upgrade,
            'post_upgrade_functions': [],
        }
        config = series_upgrade_utils.app_config('keystone')
        self.assertEqual(expected, config)

    def test_app_config_mongo(self):
        upgrade = series_upgrade_utils.async_series_upgrade_non_leaders_first
        expected = {
            'origin': None,
            'pause_non_leader_subordinate': True,
            'pause_non_leader_primary': True,
            'upgrade_function': upgrade,
            'post_upgrade_functions': [],
        }
        config = series_upgrade_utils.app_config('mongodb')
        self.assertEqual(expected, config)

    def test_app_config_ceph(self):
        upgrade = series_upgrade_utils.async_series_upgrade_application
        expected = {
            'origin': 'source',
            'pause_non_leader_subordinate': False,
            'pause_non_leader_primary': False,
            'upgrade_function': upgrade,
            'post_upgrade_functions': [],
        }
        config = series_upgrade_utils.app_config('ceph-mon')
        self.assertEqual(expected, config)
