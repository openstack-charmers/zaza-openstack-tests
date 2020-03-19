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

import copy
import mock

import unit_tests.utils as ut_utils
import zaza.openstack.utilities.upgrade_utils as openstack_upgrade


class TestUpgradeUtils(ut_utils.BaseTestCase):
    def setUp(self):
        super(TestUpgradeUtils, self).setUp()
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

    def test_get_upgrade_candidates(self):
        self.maxDiff = None
        expect = copy.deepcopy(self.juju_status.applications)
        self.assertEqual(
            openstack_upgrade.get_upgrade_candidates(),
            expect)

    def test_get_upgrade_groups(self):
        self.assertEqual(
            openstack_upgrade.get_upgrade_groups(),
            {
                'Core Identity': [],
                'Control Plane': ['cinder'],
                'Data Plane': ['nova-compute'],
                'sweep_up': []})

    def test_get_series_upgrade_groups(self):
        self.assertEqual(
            openstack_upgrade.get_series_upgrade_groups(),
            {
                'Core Identity': [],
                'Control Plane': ['cinder'],
                'Data Plane': ['nova-compute'],
                'sweep_up': ['mydb', 'ntp']})

    def test_extract_charm_name_from_url(self):
        self.assertEqual(
            openstack_upgrade.extract_charm_name_from_url(
                'local:bionic/heat-12'),
            'heat')
        self.assertEqual(
            openstack_upgrade.extract_charm_name_from_url(
                'cs:bionic/heat-12'),
            'heat')
        self.assertEqual(
            openstack_upgrade.extract_charm_name_from_url('cs:heat'),
            'heat')
