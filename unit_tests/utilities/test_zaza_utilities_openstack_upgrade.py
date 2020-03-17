# Copyright 2019 Canonical Ltd.
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

import copy
import mock

import unit_tests.utils as ut_utils
import zaza.openstack.utilities.openstack_upgrade as openstack_upgrade


class TestOpenStackUpgradeUtils(ut_utils.BaseTestCase):

    async def _arun_action_on_units(self, units, cmd, model_name=None,
                                    raise_on_failure=True):
        pass

    def setUp(self):
        super(TestOpenStackUpgradeUtils, self).setUp()
        self.patch_object(
            openstack_upgrade.zaza.model,
            "async_run_action_on_units")
        self.async_run_action_on_units.side_effect = self._arun_action_on_units
        self.patch_object(
            openstack_upgrade.zaza.model,
            "get_units")
        self.juju_status = mock.MagicMock()
        self.patch_object(
            openstack_upgrade.zaza.model,
            "get_status",
            return_value=self.juju_status)
        self.patch_object(
            openstack_upgrade.zaza.model,
            "set_application_config")
        self.patch_object(
            openstack_upgrade.zaza.model,
            "get_application_config")

        def _get_application_config(app, model_name=None):
            app_config = {
                'ceph-mon': {'verbose': True, 'source': 'old-src'},
                'neutron-openvswitch': {'verbose': True},
                'ntp': {'verbose': True},
                'percona-cluster': {'verbose': True, 'source': 'old-src'},
                'cinder': {
                    'verbose': True,
                    'openstack-origin': 'old-src',
                    'action-managed-upgrade': False},
                'neutron-api': {
                    'verbose': True,
                    'openstack-origin': 'old-src',
                    'action-managed-upgrade': False},
                'nova-compute': {
                    'verbose': True,
                    'openstack-origin': 'old-src',
                    'action-managed-upgrade': False},
            }
            return app_config[app]
        self.get_application_config.side_effect = _get_application_config
        self.juju_status.applications = {
            'mydb': {  # Filter as it is on UPGRADE_EXCLUDE_LIST
                'charm': 'cs:percona-cluster'},
            'neutron-openvswitch': {  # Filter as it is a subordinates
                'charm': 'cs:neutron-openvswitch',
                'subordinate-to': 'nova-compute'},
            'ntp': {  # Filter as it has no source option
                'charm': 'cs:ntp'},
            'nova-compute': {
                'charm': 'cs:nova-compute',
                'units': {
                    'nova-compute/0': {
                        'subordinates': {
                            'neutron-openvswitch/2': {
                                'charm': 'cs:neutron-openvswitch-22'}}}}},
            'cinder': {
                'charm': 'cs:cinder-23',
                'units': {
                    'cinder/1': {
                        'subordinates': {
                            'cinder-hacluster/0': {
                                'charm': 'cs:hacluster-42'},
                            'cinder-ceph/3': {
                                'charm': 'cs:cinder-ceph-2'}}}}}}

    def test_pause_units(self):
        openstack_upgrade.pause_units(['cinder/1', 'glance/2'])
        self.async_run_action_on_units.assert_called_once_with(
            ['cinder/1', 'glance/2'],
            'pause',
            model_name=None,
            raise_on_failure=True)

    def test_resume_units(self):
        openstack_upgrade.resume_units(['cinder/1', 'glance/2'])
        self.async_run_action_on_units.assert_called_once_with(
            ['cinder/1', 'glance/2'],
            'resume',
            model_name=None,
            raise_on_failure=True)

    def test_action_unit_upgrade(self):
        openstack_upgrade.action_unit_upgrade(['cinder/1', 'glance/2'])
        self.async_run_action_on_units.assert_called_once_with(
            ['cinder/1', 'glance/2'],
            'openstack-upgrade',
            model_name=None,
            raise_on_failure=True)

    def test_action_upgrade_group(self):
        self.patch_object(openstack_upgrade, "pause_units")
        self.patch_object(openstack_upgrade, "action_unit_upgrade")
        self.patch_object(openstack_upgrade, "resume_units")
        mock_nova_compute_0 = mock.MagicMock()
        mock_nova_compute_0.entity_id = 'nova-compute/0'
        mock_cinder_1 = mock.MagicMock()
        mock_cinder_1.entity_id = 'cinder/1'
        units = {
            'nova-compute': [mock_nova_compute_0],
            'cinder': [mock_cinder_1]}
        self.get_units.side_effect = lambda app, model_name: units[app]
        openstack_upgrade.action_upgrade_group(['nova-compute', 'cinder'])
        pause_calls = [
            mock.call(['cinder-hacluster/0'], model_name=None),
            mock.call(['nova-compute/0', 'cinder/1'], model_name=None)]
        self.pause_units.assert_has_calls(pause_calls, any_order=False)
        action_unit_upgrade_calls = [
            mock.call(['nova-compute/0', 'cinder/1'], model_name=None)]
        self.action_unit_upgrade.assert_has_calls(
            action_unit_upgrade_calls,
            any_order=False)
        resume_calls = [
            mock.call(['nova-compute/0', 'cinder/1'], model_name=None),
            mock.call(['cinder-hacluster/0'], model_name=None)]
        self.resume_units.assert_has_calls(resume_calls, any_order=False)

    def test_set_upgrade_application_config(self):
        openstack_upgrade.set_upgrade_application_config(
            ['neutron-api', 'cinder'],
            'new-src')
        set_app_calls = [
            mock.call(
                'neutron-api',
                {
                    'openstack-origin': 'new-src',
                    'action-managed-upgrade': 'True'},
                model_name=None),
            mock.call(
                'cinder',
                {
                    'openstack-origin': 'new-src',
                    'action-managed-upgrade': 'True'},
                model_name=None)]
        self.set_application_config.assert_has_calls(set_app_calls)

        self.set_application_config.reset_mock()
        openstack_upgrade.set_upgrade_application_config(
            ['percona-cluster'],
            'new-src',
            action_managed=False)
        self.set_application_config.assert_called_once_with(
            'percona-cluster',
            {'source': 'new-src'},
            model_name=None)

    def test_is_action_upgradable(self):
        self.assertTrue(
            openstack_upgrade.is_action_upgradable('cinder'))
        self.assertFalse(
            openstack_upgrade.is_action_upgradable('percona-cluster'))

    def test_run_action_upgrade(self):
        self.patch_object(openstack_upgrade, "set_upgrade_application_config")
        self.patch_object(openstack_upgrade, "action_upgrade_group")
        openstack_upgrade.run_action_upgrade(
            ['cinder', 'neutron-api'],
            'new-src')
        self.set_upgrade_application_config.assert_called_once_with(
            ['cinder', 'neutron-api'],
            'new-src',
            model_name=None)
        self.action_upgrade_group.assert_called_once_with(
            ['cinder', 'neutron-api'],
            model_name=None)

    def test_run_all_in_one_upgrade(self):
        self.patch_object(openstack_upgrade, "set_upgrade_application_config")
        self.patch_object(
            openstack_upgrade.zaza.model,
            'block_until_all_units_idle')
        openstack_upgrade.run_all_in_one_upgrade(
            ['percona-cluster'],
            'new-src')
        self.set_upgrade_application_config.assert_called_once_with(
            ['percona-cluster'],
            'new-src',
            action_managed=False,
            model_name=None)
        self.block_until_all_units_idle.assert_called_once_with()

    def test_run_upgrade(self):
        self.patch_object(openstack_upgrade, "run_all_in_one_upgrade")
        self.patch_object(openstack_upgrade, "run_action_upgrade")
        openstack_upgrade.run_upgrade(
            ['cinder', 'neutron-api', 'ceph-mon'],
            'new-src')
        self.run_all_in_one_upgrade.assert_called_once_with(
            ['ceph-mon'],
            'new-src',
            model_name=None)
        self.run_action_upgrade.assert_called_once_with(
            ['cinder', 'neutron-api'],
            'new-src',
            model_name=None)

    def test_run_upgrade_tests(self):
        self.patch_object(openstack_upgrade, "run_upgrade")
        self.patch_object(openstack_upgrade, "get_upgrade_groups")
        self.get_upgrade_groups.return_value = {
            'Compute': ['nova-compute'],
            'Control Plane': ['cinder', 'neutron-api'],
            'Core Identity': ['keystone'],
            'Storage': ['ceph-mon'],
            'sweep_up': ['designate']}
        openstack_upgrade.run_upgrade_tests('new-src', model_name=None)
        run_upgrade_calls = [
            mock.call(['keystone'], 'new-src', model_name=None),
            mock.call(['ceph-mon'], 'new-src', model_name=None),
            mock.call(['cinder', 'neutron-api'], 'new-src', model_name=None),
            mock.call(['nova-compute'], 'new-src', model_name=None),
            mock.call(['designate'], 'new-src', model_name=None)]
        self.run_upgrade.assert_has_calls(run_upgrade_calls, any_order=False)
