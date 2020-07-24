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

import logging
import tempfile

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.generic as generic_utils


class ISCSIConnectorTest(test_utils.BaseCharmTest):
    """Class for iscsi-connector tests."""

    IQN = 'iqn.2020-07.canonical.com:lun1'

    def configure_iscsi_connector(self):
        unit_fqdn = self.get_unit_full_hostname('ubuntu/0')
        target_ip = zaza.model.get_app_ips('ubuntu-target')[0]
        conf = {
            'initiator-dictionary': '{"{unit_fqdn}":"{IQN}"}',
            'target': target_ip,
            'port': '3260',
        }
        zaza.model.set_application_config('iscsi-connector', conf)

    def get_unit_full_hostname(self, unit_name):
        """Retrieve the full hostname of a unit."""
        for unit in zaza.model.get_units(unit_name):
            result = zaza.model.run_on_unit(unit.entity_id, 'hostname -f')
            hostname = result['Stdout'].rstrip()
        return hostname

    def test_iscsi_connector(self):
        self.configure_iscsi_connector()
