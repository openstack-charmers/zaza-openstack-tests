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
import zaza.utilities.juju as juju_utils


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

    def test_930_scaleback_bionic(self):
        """Remove a unit, recalculate quorum and add a new one."""
        principle_app = 'keystone'
        principle_units = zaza.model.get_status().applications[
            principle_app]['units']
        self.assertEqual(len(principle_units), 3)
        doomed_principle = sorted(principle_units.keys())[0]
        series = juju_utils.get_machine_series(
            principle_units[doomed_principle].machine)
        if series != 'bionic':
            logging.debug("noop - only run test in bionic")
            logging.info('SKIP')
            return

        doomed_unit = juju_utils.get_subordinate_units(
            [doomed_principle], charm_name='hac')[0]

        logging.info('Pausing unit {}'.format(doomed_unit))
        zaza.model.run_action(
            doomed_unit,
            'pause',
            raise_on_failure=True)
        logging.info('OK')

        logging.info('Resuming unit {}'.format(doomed_unit))
        zaza.model.run_action(
            doomed_unit,
            'resume',
            raise_on_failure=True)
        logging.info('OK')

        logging.info('Removing {}'.format(doomed_principle))
        zaza.model.destroy_unit(
            principle_app,
            doomed_principle,
            wait_disappear=True)
        logging.info('OK')

        logging.info('Updating corosync ring')
        zaza.model.run_action_on_leader(
            self.application_name,
            'update-ring',
            action_params={'i-really-mean-it': True},
            raise_on_failure=True)

        _states = {
            self.application_name: {
                "workload-status": "blocked",
                "workload-status-message":
                    "Insufficient peer units for ha cluster (require 3)"
            },
            'keystone': {
                "workload-status": "blocked",
                "workload-status-message": "Database not initialised",
            },
        }
        zaza.model.wait_for_application_states(states=_states)
        zaza.model.block_until_all_units_idle()
        logging.info('OK')

        logging.info('Adding a hacluster unit')
        zaza.model.add_unit(principle_app, wait_appear=True)
        _states = {self.application_name: {
            "workload-status": "active",
            "workload-status-message": "Unit is ready and clustered"}}
        zaza.model.wait_for_application_states(states=_states)
        logging.debug('OK')
