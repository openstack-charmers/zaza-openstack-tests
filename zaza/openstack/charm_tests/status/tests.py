# Copyright 2023 Canonical Ltd.
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

"""Code for running status tests."""

import logging

import zaza
import zaza.openstack.charm_tests.test_utils as test_utils


class ProposedPackageReport(test_utils.OpenStackBaseTest):
    """Proposed packages report status test class."""

    def test_100_report_proposed_packages(self):
        """Report proposed packages installed on each unit."""
        cmd = 'apt list --installed'
        for application in zaza.model.get_status().applications:
            for unit in zaza.model.get_units(application):
                installed = zaza.model.run_on_unit(unit.entity_id, cmd)
                proposed = []
                for pkg in installed['Stdout'].split('\n'):
                    if 'proposed' in pkg:
                        proposed.append(pkg)
            logging.info("\n\nProposed packages installed on {}:\n{}".format(
                unit.entity_id, "\n".join(proposed)))
