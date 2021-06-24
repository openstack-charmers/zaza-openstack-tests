# Copyright 2021 Canonical Ltd.
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

"""Encapsulating `ceph-dashboard` testing."""

import collections
import os
import requests

import zaza
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.utilities.deployment_env as deployment_env


class CephDashboardTest(test_utils.BaseCharmTest):
    """Class for `ceph-dashboard` tests."""

    REMOTE_CERT_FILE = ('/usr/local/share/ca-certificates/'
                        'vault_ca_cert_dashboard.crt')

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph dashboard tests."""
        super().setUpClass()
        cls.application_name = 'ceph-dashboard'
        cls.local_ca_cert = cls.collect_ca()

    @classmethod
    def collect_ca(cls):
        """Collect CA from ceph-dashboard unit."""
        local_ca_cert = os.path.join(
            deployment_env.get_tmpdir(),
            os.path.basename(cls.REMOTE_CERT_FILE))
        if not os.path.isfile(local_ca_cert):
            units = zaza.model.get_units(cls.application_name)
            zaza.model.scp_from_unit(
                units[0].entity_id,
                cls.REMOTE_CERT_FILE,
                local_ca_cert)
        return local_ca_cert

    def test_dashboard_units(self):
        """Check dashboard units are configured correctly."""
        # XXX: Switch to using CA for verification when
        #      https://bugs.launchpad.net/cloud-archive/+bug/1933410
        #      is fix released.
        # verify = self.local_ca_cert
        verify = False
        units = zaza.model.get_units(self.application_name)
        rcs = collections.defaultdict(list)
        for unit in units:
            r = requests.get(
                'https://{}:8443'.format(unit.public_address),
                verify=verify,
                allow_redirects=False)
            rcs[r.status_code].append(unit.public_address)
        self.assertEqual(len(rcs[requests.codes.ok]), 1)
        self.assertEqual(len(rcs[requests.codes.see_other]), len(units) - 1)

    def create_user(self, username, role='administrator'):
        """Store the model aliases in a global.

        :param username: Username to create.
        :type username: str
        :param role: Role to grant to user.
        :type role: str
        :returns: Results from action.
        :rtype: juju.action.Action
        """
        action = zaza.model.run_action_on_leader(
            'ceph-dashboard',
            'add-user',
            action_params={
                'username': username,
                'role': role})
        return action

    def test_create_user(self):
        """Test create user action."""
        test_user = 'marvin'
        action = self.create_user(test_user)
        self.assertEqual(action.status, "completed")
        self.assertTrue(action.data['results']['password'])
        action = self.create_user(test_user)
        # Action should fail as the user already exists
        self.assertEqual(action.status, "failed")
