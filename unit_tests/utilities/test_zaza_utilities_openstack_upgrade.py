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
        self.patch_object(
            openstack_upgrade.zaza.model,
            "block_until_all_units_idle")
        self.patch_object(
            openstack_upgrade,
            "block_until_mysql_innodb_cluster_has_rw")

        def _get_application_config(app, model_name=None):
            app_config = {
                'ceph-mon': {'verbose': {'value': True},
                             'source': {'value': 'old-src'}},
                'neutron-openvswitch': {'verbose': {'value': True}},
                'ntp': {'verbose': {'value': True}},
                'percona-cluster': {'verbose': {'value': True},
                                    'source': {'value': 'old-src'}},
                'cinder': {
                    'verbose': {'value': True},
                    'openstack-origin': {'value': 'old-src'},
                    'action-managed-upgrade': {'value': False}},
                'neutron-api': {
                    'verbose': {'value': True},
                    'openstack-origin': {'value': 'old-src'},
                    'action-managed-upgrade': {'value': False}},
                'nova-compute': {
                    'verbose': {'value': True},
                    'openstack-origin': {'value': 'old-src'},
                    'action-managed-upgrade': {'value': False}},
                'mysql-innodb-cluster': {
                    'verbose': {'value': True},
                    'source': {'value': 'old-src'},
                    'action-managed-upgrade': {'value': True}},
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
            'mysql-innodb-cluster': {
                'charm': 'cs:mysql-innodb-cluster',
                'units': {
                    'mysql-innodb-cluster/0': {}}},
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

    def test_action_upgrade_apps(self):
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
        openstack_upgrade.action_upgrade_apps(['nova-compute', 'cinder'])
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

    def test_action_upgrade_apps_mysql_innodb_cluster(self):
        """Verify that mysql-innodb-cluster is settled before complete."""
        self.patch_object(openstack_upgrade, "pause_units")
        self.patch_object(openstack_upgrade, "action_unit_upgrade")
        self.patch_object(openstack_upgrade, "resume_units")
        mock_mysql_innodb_cluster_0 = mock.MagicMock()
        mock_mysql_innodb_cluster_0.entity_id = 'mysql-innodb-cluster/0'
        units = {'mysql-innodb-cluster': [mock_mysql_innodb_cluster_0]}
        self.get_units.side_effect = lambda app, model_name: units[app]
        openstack_upgrade.action_upgrade_apps(['mysql-innodb-cluster'])
        pause_calls = [
            mock.call(['mysql-innodb-cluster/0'], model_name=None)]
        self.pause_units.assert_has_calls(pause_calls, any_order=False)
        action_unit_upgrade_calls = [
            mock.call(['mysql-innodb-cluster/0'], model_name=None)]
        self.action_unit_upgrade.assert_has_calls(
            action_unit_upgrade_calls,
            any_order=False)
        resume_calls = [
            mock.call(['mysql-innodb-cluster/0'], model_name=None)]
        self.resume_units.assert_has_calls(resume_calls, any_order=False)
        self.block_until_mysql_innodb_cluster_has_rw.assert_called_once_with(
            None)

    def test_upgrade_to_proposed(self):
        self.patch_object(
            openstack_upgrade,
            'get_current_source_config')
        self.patch_object(
            openstack_upgrade.generic_utils,
            "set_origin")
        self.patch_object(
            openstack_upgrade.zaza.model,
            "get_units")
        self.patch_object(
            openstack_upgrade.series_upgrade_utils,
            "dist_upgrade")
        self.get_current_source_config.return_value = 'source', 'old-src'

        mock_nova_compute_0 = mock.MagicMock()
        mock_nova_compute_0.entity_id = 'nova-compute/0'
        mock_ceph_mon_0 = mock.MagicMock()
        mock_ceph_mon_0.entity_id = 'ceph-mon/0'
        units = {
            'nova-compute': [mock_nova_compute_0],
            'ceph-mon': [mock_ceph_mon_0]}
        self.get_units.side_effect = lambda app: units[app]

        openstack_upgrade.upgrade_to_proposed('nova-compute')

        self.set_origin.assert_called_once_with(
            'nova-compute', origin='source', pocket='old-src/proposed')

    def test_upgrade_to_ppa(self):
        self.patch_object(
            openstack_upgrade,
            'get_current_source_config')
        self.patch_object(
            openstack_upgrade.generic_utils,
            "set_origin")
        self.patch_object(
            openstack_upgrade.zaza.model,
            "get_units")
        self.patch_object(
            openstack_upgrade.series_upgrade_utils,
            "dist_upgrade")
        self.get_current_source_config.return_value = 'source', 'old-src'

        mock_nova_compute_0 = mock.MagicMock()
        mock_nova_compute_0.entity_id = 'nova-compute/0'
        mock_ceph_mon_0 = mock.MagicMock()
        mock_ceph_mon_0.entity_id = 'ceph-mon/0'
        units = {
            'nova-compute': [mock_nova_compute_0],
            'ceph-mon': [mock_ceph_mon_0]}
        self.get_units.side_effect = lambda app: units[app]

        openstack_upgrade.upgrade_to_ppa('nova-compute', 'ppa:new-ppa')

        self.set_origin.assert_called_once_with(
            'nova-compute', origin='source', pocket='ppa:new-ppa')

    def test_get_current_source_config(self):
        self.patch_object(
            openstack_upgrade.zaza.model,
            'get_application_config')

        def _get_application_config(app, model_name=None):
            app_config = {
                'ceph-mon': {'source': {'value': 'old-src'}},
                'nova-compute': {'openstack-origin': {'value': 'old-src'}},
            }
            return app_config[app]

        self.get_application_config.side_effect = _get_application_config

        option, value = openstack_upgrade.get_current_source_config('ceph-mon')
        self.assertEqual(option, 'source')
        self.assertEqual(value, 'old-src')

        option, value = openstack_upgrade.get_current_source_config(
            'nova-compute')
        self.assertEqual(option, 'openstack-origin')
        self.assertEqual(value, 'old-src')

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

    def test_is_already_upgraded(self):
        self.assertTrue(
            openstack_upgrade.is_already_upgraded('cinder', 'old-src'))
        self.assertFalse(
            openstack_upgrade.is_already_upgraded('cinder', 'new-src'))

    def test_run_action_upgrade(self):
        self.patch_object(openstack_upgrade, "set_upgrade_application_config")
        self.patch_object(openstack_upgrade, "action_upgrade_apps")
        openstack_upgrade.run_action_upgrades(
            ['cinder', 'neutron-api'],
            'new-src')
        self.set_upgrade_application_config.assert_called_once_with(
            ['cinder', 'neutron-api'],
            'new-src',
            model_name=None)
        self.action_upgrade_apps.assert_called_once_with(
            ['cinder', 'neutron-api'],
            model_name=None)

    def test_run_all_in_one_upgrade(self):
        self.patch_object(openstack_upgrade, "set_upgrade_application_config")
        self.patch_object(
            openstack_upgrade.zaza.model,
            'block_until_all_units_idle')
        openstack_upgrade.run_all_in_one_upgrades(
            ['percona-cluster'],
            'new-src')
        self.set_upgrade_application_config.assert_called_once_with(
            ['percona-cluster'],
            'new-src',
            action_managed=False,
            model_name=None)
        self.block_until_all_units_idle.assert_called_once_with()

    def test_run_upgrade(self):
        self.patch_object(openstack_upgrade, "run_all_in_one_upgrades")
        self.patch_object(openstack_upgrade, "run_action_upgrades")
        openstack_upgrade.run_upgrade_on_apps(
            ['cinder', 'neutron-api', 'ceph-mon'],
            'new-src')
        self.run_all_in_one_upgrades.assert_called_once_with(
            ['ceph-mon'],
            'new-src',
            model_name=None)
        self.run_action_upgrades.assert_called_once_with(
            ['cinder', 'neutron-api'],
            'new-src',
            model_name=None)

    def test_run_upgrade_tests(self):
        self.patch_object(openstack_upgrade, "run_upgrade_on_apps")
        self.patch_object(openstack_upgrade, "get_upgrade_groups")
        self.get_upgrade_groups.return_value = [
            ('Compute', ['nova-compute']),
            ('Control Plane', ['cinder', 'neutron-api']),
            ('Core Identity', ['keystone']),
            ('Storage', ['ceph-mon']),
            ('sweep_up', ['designate'])]
        openstack_upgrade.run_upgrade_tests('new-src', model_name=None)
        run_upgrade_calls = [
            mock.call(['nova-compute'], 'new-src', model_name=None),
            mock.call(['cinder', 'neutron-api'], 'new-src', model_name=None),
            mock.call(['keystone'], 'new-src', model_name=None),
            mock.call(['ceph-mon'], 'new-src', model_name=None),
            mock.call(['designate'], 'new-src', model_name=None),
        ]
        self.run_upgrade_on_apps.assert_has_calls(
            run_upgrade_calls, any_order=False)
