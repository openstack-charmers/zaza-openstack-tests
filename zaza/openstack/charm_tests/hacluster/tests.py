#!/usr/bin/env python3

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

"""HACluster testing."""

import logging
import os

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.configure.hacluster


class HaclusterTest(test_utils.OpenStackBaseTest):
    """hacluster tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running hacluster tests."""
        super(HaclusterTest, cls).setUpClass()
        cls.vip = os.environ.get("TEST_VIP00")

    def test_900_action_cleanup(self):
        """The services can be cleaned up."""
        zaza.model.run_action_on_leader(
            self.application_name,
            'cleanup',
            raise_on_failure=True)

    def test_910_pause_and_resume(self):
        """The services can be paused and resumed."""
        with self.pause_resume([]):
            logging.info("Testing pause resume")

    def _toggle_maintenance_and_wait(self, expected):
        """Configure cluster maintenance-mode.

        :param expected: expected value to set maintenance-mode
        """
        config = {"maintenance-mode": expected}
        logging.info("Setting config to {}".format(config))
        zaza.model.set_application_config(self.application_name, config)
        if expected == 'true':
            _states = {"hacluster": {
                "workload-status": "maintenance",
                "workload-status-message": "Pacemaker in maintenance mode"}}
        else:
            _states = {"hacluster": {
                "workload-status": "active",
                "workload-status-message": "Unit is ready and clustered"}}
        zaza.model.wait_for_application_states(states=_states)
        logging.debug('OK')

    def test_920_put_in_maintenance(self):
        """Put pacemaker in maintenance mode."""
        logging.debug('Setting cluster in maintenance mode')

        self._toggle_maintenance_and_wait('true')
        self._toggle_maintenance_and_wait('false')
