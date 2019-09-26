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

"""Encapsulate Aodh testing."""

import logging

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.configure.telemetry as telemetry_utils


class AodhTest(test_utils.OpenStackBaseTest):
    """Encapsulate Aodh tests."""

    RESOURCE_PREFIX = 'zaza-aodhtests'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(AodhTest, cls).setUpClass()
        cls.xenial_ocata = openstack_utils.get_os_release('xenial_ocata')
        cls.xenial_newton = openstack_utils.get_os_release('xenial_newton')
        cls.bionic_stein = openstack_utils.get_os_release('bionic_stein')
        cls.release = openstack_utils.get_os_release()
        cls.keystone_session = openstack_utils.get_overcloud_keystone_session()
        cls.model_name = zaza.model.get_juju_model()
        cls.aodh_client = openstack_utils.get_aodh_session_client(
            cls.keystone_session)

    @classmethod
    def tearDown(cls):
        """Remove test resources."""
        logging.info('Running teardown')
        cache_wait = False
        for alarm in cls.aodh_client.alarm.list():
            if alarm['name'].startswith(cls.RESOURCE_PREFIX):
                cache_wait = True
                logging.info('Removing Alarm {}'.format(alarm['name']))
                telemetry_utils.delete_alarm(
                    cls.aodh_client,
                    alarm['name'],
                    cache_wait=False)
        if cache_wait:
            logging.info('Waiting for alarm cache to clear')
            telemetry_utils.alarm_cache_wait()

    @property
    def services(self):
        """Return a list of the service that should be running."""
        if self.release >= self.xenial_ocata:
            services = [
                'apache2',
                'aodh-evaluator: AlarmEvaluationService worker(0)',
                'aodh-notifier: AlarmNotifierService worker(0)',
                ('aodh-listener: EventAlarmEvaluationService'
                 ' worker(0)')]
        elif self.release >= self.xenial_newton:
            services = [
                ('/usr/bin/python /usr/bin/aodh-api --port 8032 -- '
                 '--config-file=/etc/aodh/aodh.conf '
                 '--log-file=/var/log/aodh/aodh-api.log'),
                'aodh-evaluator - AlarmEvaluationService(0)',
                'aodh-notifier - AlarmNotifierService(0)',
                'aodh-listener - EventAlarmEvaluationService(0)']
        else:
            services = [
                'aodh-api',
                'aodh-evaluator',
                'aodh-notifier',
                'aodh-listener']
        return services

    def test_100_test_api(self):
        """Check api by creating an alarm."""
        alarm_name = '{}_test_api_alarm'.format(self.RESOURCE_PREFIX)
        logging.info('Creating alarm {}'.format(alarm_name))
        alarm = telemetry_utils.create_server_power_off_alarm(
            self.aodh_client,
            alarm_name,
            'some-uuid')
        alarm_state = telemetry_utils.get_alarm_state(
            self.aodh_client,
            alarm['alarm_id'])
        logging.info('alarm_state: {}'.format(alarm_state))
        # Until data is collected alarm come up in an 'insufficient data'
        # state.
        self.assertEqual(alarm_state, 'insufficient data')

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change disk format and assert then change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        set_default = {'debug': 'False'}
        set_alternate = {'debug': 'True'}

        # Config file affected by juju set config change
        conf_file = '/etc/aodh/aodh.conf'

        # Make config change, check for service restarts
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            {'DEFAULT': {'debug': ['False']}},
            {'DEFAULT': {'debug': ['True']}},
            self.services)

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(
                self.services,
                pgrep_full=False):
            logging.info("Testing pause resume")
