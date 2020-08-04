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

"""Encapsulate iscsi-connector testing."""

import json
import logging

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils


class ISCSIConnectorTest(test_utils.BaseCharmTest):
    """Class for iscsi-connector tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running glance tests."""
        super(ISCSIConnectorTest, cls).setUpClass()

    def configure_iscsi_connector(self):
        """Configure iscsi connector."""
        iqn = 'iqn.2020-07.canonical.com:lun1'
        unit_fqdn = self.get_unit_full_hostname('ubuntu')
        target_ip = zaza.model.get_app_ips('ubuntu-target')[0]
        initiator_dictionary = json.dumps({unit_fqdn: iqn})
        conf = {
            'initiator-dictionary': initiator_dictionary,
            'target': target_ip,
            'port': '3260',
            'iscsi-node-session-auth-authmethod': 'CHAP',
            'iscsi-node-session-auth-username': 'iscsi-user',
            'iscsi-node-session-auth-password': 'password123',
            'iscsi-node-session-auth-username-in': 'iscsi-target',
            'iscsi-node-session-auth-password-in': 'secretpass',
        }
        zaza.model.set_application_config('iscsi-connector', conf)

    def get_unit_full_hostname(self, unit_name):
        """Retrieve the full hostname of a unit."""
        for unit in zaza.model.get_units(unit_name):
            result = zaza.model.run_on_unit(unit.entity_id, 'hostname -f')
            hostname = result['Stdout'].rstrip()
        return hostname

    def test_iscsi_connector(self):
        """Test iscsi configuration and wait for idle status."""
        self.configure_iscsi_connector()
        logging.info('Wait for idle/ready status...')
        zaza.model.wait_for_application_states()

    def test_validate_iscsi_session(self):
        """Validate that the iscsi session is active."""
        unit = zaza.model.get_units('ubuntu')[0]
        logging.info('Checking if iscsi session is active.')
        run = zaza.model.run_on_unit(unit.entity_id, 'iscsiadm -m session')
        logging.info("""iscsiadm -m session: Stdout: {}, Stderr: {}, """
                     """Code: {}""".format(run['Stdout'],
                                           run['Stderr'],
                                           run['Code']))
        assert run['Code'] == '0'
