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


class HaclusterBaseTest(test_utils.OpenStackBaseTest):
    """Base class for hacluster tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running hacluster tests."""
        super(HaclusterBaseTest, cls).setUpClass()
        cls.vip = os.environ.get("TEST_VIP00")


class HaclusterTest(HaclusterBaseTest):
    """hacluster tests."""

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


class HaclusterScalebackTest(HaclusterBaseTest):
    """hacluster scaleback tests."""

    _PRINCIPLE_APP_NAME = 'keystone'
    _HACLUSTER_APP_NAME = 'hacluster'
    _HACLUSTER_CHARM_NAME = 'hacluster'

    def test_930_scaleback(self):
        """Remove a unit, recalculate quorum and add a new one."""
        principle_units = zaza.model.get_status().applications[
            self._PRINCIPLE_APP_NAME]['units']
        self.assertEqual(len(principle_units), 3)
        doomed_principle = sorted(principle_units.keys())[0]
        doomed_unit = juju_utils.get_subordinate_units(
            [doomed_principle], charm_name=self._HACLUSTER_CHARM_NAME)[0]

        logging.info('Pausing unit {}'.format(doomed_unit))
        zaza.model.run_action(
            doomed_unit,
            'pause',
            raise_on_failure=True)
        logging.info('OK')

        logging.info('Removing {}'.format(doomed_principle))
        zaza.model.destroy_unit(
            self._PRINCIPLE_APP_NAME,
            doomed_principle,
            wait_disappear=True)
        logging.info('OK')

        expected_states = {
            self._HACLUSTER_APP_NAME: {
                "workload-status": "blocked",
                "workload-status-message":
                    "Insufficient peer units for ha cluster (require 3)"
            },
            self._PRINCIPLE_APP_NAME: {
                "workload-status": "blocked",
                "workload-status-message": "Database not initialised",
            },

            # NOTE(lourot): these applications are present in the zaza bundles
            # used to test mysql-router, against which we also run this test:
            'glance': {
                "workload-status": "waiting",
                "workload-status-message": "Incomplete relations: identity",
            },
            'neutron-api': {
                "workload-status": "waiting",
                "workload-status-message": "Incomplete relations: identity",
            },
            'nova-cloud-controller': {
                "workload-status": "waiting",
                "workload-status-message": "Incomplete relations: identity",
            },
        }
        zaza.model.wait_for_application_states(states=expected_states)
        zaza.model.block_until_all_units_idle()
        logging.info('OK')

        logging.info('Adding a hacluster unit')
        zaza.model.add_unit(self._PRINCIPLE_APP_NAME, wait_appear=True)
        expected_states = {
            self._HACLUSTER_APP_NAME: {
                "workload-status": "active",
                "workload-status-message": "Unit is ready and clustered"
            },

            # NOTE(lourot): these applications remain waiting/blocked after
            # scaling back up until lp:1400481 is solved.
            'glance': {
                "workload-status": "waiting",
                "workload-status-message": "Incomplete relations: identity",
            },
            'keystone': {
                "workload-status": "blocked",
                "workload-status-message": "Database not initialised",
            },
            'neutron-api': {
                "workload-status": "waiting",
                "workload-status-message": "Incomplete relations: identity",
            },
            'nova-cloud-controller': {
                "workload-status": "waiting",
                "workload-status-message": "Incomplete relations: identity",
            },
            'placement': {
                "workload-status": "waiting",
                "workload-status-message": "'identity-service' incomplete",
            },
        }
        zaza.model.wait_for_application_states(states=expected_states)
        logging.debug('OK')
