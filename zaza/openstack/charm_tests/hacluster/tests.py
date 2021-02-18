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
    """hacluster scaleback tests.

    Use for testing older releases where lp:1400481 wasn't fixed yet.
    Superseded by HaclusterScaleBackAndForthTest.
    """

    @classmethod
    def setUpClass(cls):
        """Run class setup for running hacluster scaleback tests."""
        super(HaclusterScalebackTest, cls).setUpClass()
        test_config = cls.test_config['tests_options']['hacluster']
        cls._principle_app_name = test_config['principle-app-name']
        cls._hacluster_charm_name = test_config['hacluster-charm-name']

    def test_930_scaleback(self):
        """Remove a unit and add a new one."""
        principle_units = sorted(zaza.model.get_status().applications[
            self._principle_app_name]['units'].keys())
        self.assertEqual(len(principle_units), 3)
        doomed_principle_unit = principle_units[0]
        other_principle_unit = principle_units[1]
        doomed_hacluster_unit = juju_utils.get_subordinate_units(
            [doomed_principle_unit], charm_name=self._hacluster_charm_name)[0]
        other_hacluster_unit = juju_utils.get_subordinate_units(
            [other_principle_unit], charm_name=self._hacluster_charm_name)[0]

        logging.info('Pausing unit {}'.format(doomed_hacluster_unit))
        zaza.model.run_action(
            doomed_hacluster_unit,
            'pause',
            raise_on_failure=True)
        logging.info('OK')

        logging.info('Removing {}'.format(doomed_principle_unit))
        zaza.model.destroy_unit(
            self._principle_app_name,
            doomed_principle_unit,
            wait_disappear=True)
        logging.info('OK')

        logging.info('Waiting for model to settle')
        zaza.model.block_until_unit_wl_status(other_hacluster_unit, 'blocked')
        zaza.model.block_until_unit_wl_status(other_principle_unit, 'blocked')
        zaza.model.block_until_all_units_idle()
        logging.info('OK')

        logging.info('Adding an hacluster unit')
        zaza.model.add_unit(self._principle_app_name, wait_appear=True)
        logging.info('OK')

        logging.info('Waiting for model to settle')
        zaza.model.block_until_unit_wl_status(other_hacluster_unit, 'active')
        # NOTE(lourot): the principle application sometimes remain blocked
        # after scaling back up until lp:1400481 is solved.
        # zaza.model.block_until_unit_wl_status(other_principle_unit, 'active')
        zaza.model.block_until_all_units_idle()
        logging.debug('OK')


class HaclusterScaleBackAndForthTest(HaclusterBaseTest):
    """hacluster tests scaling back and forth.

    Supersedes HaclusterScalebackTest.
    """

    @classmethod
    def setUpClass(cls):
        """Run class setup for running hacluster tests."""
        super(HaclusterScaleBackAndForthTest, cls).setUpClass()
        test_config = cls.test_config['tests_options']['hacluster']
        cls._principle_app_name = test_config['principle-app-name']
        cls._hacluster_charm_name = test_config['hacluster-charm-name']

    def test_930_scaleback(self):
        """Remove two units, recalculate quorum and re-add two units.

        NOTE(lourot): before lp:1400481 was fixed, the corosync ring wasn't
        recalculated when removing units. So within a cluster of 3 units,
        removing two units and re-adding them led to a situation where corosync
        considers having 3 nodes online out of 5, instead of just 3 out of 3.
        This test covers this scenario.
        """
        principle_units = sorted(zaza.model.get_status().applications[
            self._principle_app_name]['units'].keys())
        self.assertEqual(len(principle_units), 3)
        doomed_principle_units = principle_units[:2]
        surviving_principle_unit = principle_units[2]
        doomed_hacluster_units = juju_utils.get_subordinate_units(
            doomed_principle_units, charm_name=self._hacluster_charm_name)
        surviving_hacluster_unit = juju_utils.get_subordinate_units(
            [surviving_principle_unit],
            charm_name=self._hacluster_charm_name)[0]

        for doomed_hacluster_unit in doomed_hacluster_units:
            logging.info('Pausing unit {}'.format(doomed_hacluster_unit))
            zaza.model.run_action(
                doomed_hacluster_unit,
                'pause',
                raise_on_failure=True)

        for doomed_principle_unit in doomed_principle_units:
            logging.info('Removing {}'.format(doomed_principle_unit))
            zaza.model.destroy_unit(
                self._principle_app_name,
                doomed_principle_unit,
                wait_disappear=True)

        logging.info('Waiting for model to settle')
        zaza.model.block_until_unit_wl_status(surviving_hacluster_unit,
                                              'blocked')
        # NOTE(lourot): the principle unit (usually a keystone unit) isn't
        # guaranteed to be blocked, so we don't validate that here.
        zaza.model.block_until_all_units_idle()

        logging.info('Updating corosync ring')
        hacluster_app_name = zaza.model.get_unit_from_name(
            surviving_hacluster_unit).application
        # NOTE(lourot): with Juju >= 2.8 this isn't actually necessary as it
        # has already been done in hacluster's hanode departing hook:
        zaza.model.run_action_on_leader(
            hacluster_app_name,
            'update-ring',
            action_params={'i-really-mean-it': True},
            raise_on_failure=True)

        for article in ('an', 'another'):
            logging.info('Re-adding {} hacluster unit'.format(article))
            zaza.model.add_unit(self._principle_app_name, wait_appear=True)

        logging.info('Waiting for model to settle')
        expected_states = {hacluster_app_name: {
            "workload-status": "active",
            "workload-status-message": "Unit is ready and clustered"}}
        zaza.model.wait_for_application_states(states=expected_states)

        # At this point if the corosync ring has been properly updated, there
        # shouldn't be any trace of the deleted units anymore:
        logging.info('Checking that corosync considers all nodes to be online')
        cmd = 'sudo crm status'
        result = zaza.model.run_on_unit(surviving_hacluster_unit, cmd)
        code = result.get('Code')
        if code != '0':
            raise zaza.model.CommandRunFailed(cmd, result)
        output = result.get('Stdout').strip()
        logging.debug('Output received: {}'.format(output))
        self.assertNotIn('OFFLINE', output,
                         "corosync shouldn't list any offline node")
