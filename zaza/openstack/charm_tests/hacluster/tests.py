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
import zaza.openstack.utilities.juju as juju_utils
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
        status = zaza.model.get_status().applications[self.application_name]

        # libjuju juju status no longer has units for subordinate charms
        # Use the application it is subordinate-to to check workload status
        if status.get("units") is None and status.get("subordinate-to"):
            primary_status = juju_utils.get_application_status(
                status.get("subordinate-to")[0])
            leader = None
            for unit in primary_status["units"]:
                if primary_status["units"][unit].get('leader'):
                    leader = unit

        if primary_status["units"][leader].get("subordinates"):
            for subordinate in primary_status["units"][leader]["subordinates"]:
                logging.info("Cleaning {}".format(subordinate))
                _action = "cleanup"
                action_id = zaza.model.run_action(subordinate, "cleanup")
                assert "success" in action_id.data["results"]["result"], (
                    "Set hacluster action {} failed: {}"
                    .format(_action, action_id.data))

                logging.info("Cleaning action w/resource {}"
                             .format(subordinate))
                params = {'resource': 'res_ks_haproxy'}
                _action = "cleanup res_ks_haproxy"
                zaza.model.run_action(subordinate, "cleanup",
                                      action_params=params)
                assert "success" in action_id.data["results"]["result"], (
                    "Set hacluster action {} failed: {}"
                    .format(_action, action_id.data))

    def test_910_pause_and_resume(self):
        """The services can be paused and resumed."""
        logging.debug('Checking pause and resume actions...')

        status = zaza.model.get_status().applications[self.application_name]

        # libjuju juju status no longer has units for subordinate charms
        # Use the application it is subordinate-to to check workload status
        if status.get("units") is None and status.get("subordinate-to"):
            primary_status = juju_utils.get_application_status(
                status.get("subordinate-to")[0])
            leader = None
            for unit in primary_status["units"]:
                if primary_status["units"][unit].get('leader'):
                    leader = unit

        if primary_status["units"][leader].get("subordinates"):
            for subordinate in primary_status["units"][leader]["subordinates"]:
                logging.info("Pausing {}".format(subordinate))
                zaza.model.run_action(subordinate, "pause")
                zaza.model.block_until_unit_wl_status(leader, "blocked")

                logging.info("Resuming {}".format(subordinate))
                zaza.model.run_action(subordinate, "resume")
                zaza.model.block_until_unit_wl_status(leader, "active")

        _states = {"hacluster": {
            "workload-status": "active",
            "workload-status-message": "Unit is ready and clustered"}}
        zaza.model.wait_for_application_states(states=_states)
        logging.debug('OK')

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
