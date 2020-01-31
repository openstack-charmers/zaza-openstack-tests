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

"""Encapsulate Ceilometer testing."""

import copy
import logging

import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.test_utils as test_utils


class CeilometerTest(test_utils.OpenStackBaseTest):
    """Encapsulate Ceilometer tests."""

    CONF_FILE = '/etc/ceilometer/ceilometer.conf'

    XENIAL_PIKE = openstack_utils.get_os_release('xenial_pike')
    XENIAL_OCATA = openstack_utils.get_os_release('xenial_ocata')
    XENIAL_NEWTON = openstack_utils.get_os_release('xenial_newton')
    XENIAL_MITAKA = openstack_utils.get_os_release('xenial_mitaka')
    TRUSTY_MITAKA = openstack_utils.get_os_release('trusty_mitaka')
    TRUSTY_LIBERTY = openstack_utils.get_os_release('trusty_liberty')

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Ceilometer tests."""
        super(CeilometerTest, cls).setUpClass()

    @property
    def services(self):
        """Return a list services for Openstack Release."""
        self.current_release = openstack_utils.get_os_release()
        services = []

        if self.application_name == 'ceilometer-agent':
            if self.current_release <= CeilometerTest.XENIAL_MITAKA:
                services.append('ceilometer-polling')
            else:
                services.append('ceilometer-polling: AgentManager worker(0)')
            return services

        # Note: disabling ceilometer-polling and ceilometer-agent-central due
        # to bug 1846390: https://bugs.launchpad.net/bugs/1846390
        if self.current_release >= CeilometerTest.XENIAL_PIKE:
            # services.append('ceilometer-polling: AgentManager worker(0)')
            services.append('ceilometer-agent-notification: '
                            'NotificationService worker(0)')
        elif self.current_release >= CeilometerTest.XENIAL_OCATA:
            services.append('ceilometer-collector: CollectorService worker(0)')
            # services.append('ceilometer-polling: AgentManager worker(0)')
            services.append('ceilometer-agent-notification: '
                            'NotificationService worker(0)')
            services.append('apache2')
        elif self.current_release >= CeilometerTest.XENIAL_NEWTON:
            services.append('ceilometer-collector - CollectorService(0)')
            # services.append('ceilometer-polling - AgentManager(0)')
            services.append('ceilometer-agent-notification - '
                            'NotificationService(0)')
            services.append('ceilometer-api')
        else:
            services.append('ceilometer-collector')
            services.append('ceilometer-api')
            services.append('ceilometer-agent-notification')

            if self.current_release < CeilometerTest.TRUSTY_MITAKA:
                services.append('ceilometer-alarm-notifier')
                services.append('ceilometer-alarm-evaluator')

            # if self.current_release >= CeilometerTest.TRUSTY_LIBERTY:
                # Liberty and later
                # services.append('ceilometer-polling')
            # else:
                # Juno and earlier
                # services.append('ceilometer-agent-central')

        return services

    # NOTE(beisner): need to add more functional tests

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change."""
        _services = copy.deepcopy(self.services)

        # Due to Bug #1861321 ceilometer-collector does not reliably
        # restart.
        if self.current_release <= CeilometerTest.TRUSTY_MITAKA:
            try:
                _services.remove('ceilometer-collector')
            except ValueError:
                pass

        config_name = 'debug'

        if self.application_name == 'ceilometer-agent':
            config_name = 'use-internal-endpoints'

        # Expected default and alternate values
        current_value = openstack_utils.get_application_config_option(
            self.application_name, config_name
        )
        assert type(current_value) == bool
        new_value = not current_value

        # Convert bool to str
        current_value = str(current_value)
        new_value = str(new_value)

        set_default = {config_name: current_value}
        set_alternate = {config_name: new_value}

        default_entry = {'DEFAULT': {'debug': [current_value]}}
        alternate_entry = {'DEFAULT': {'debug': [new_value]}}

        if self.application_name == 'ceilometer-agent':
            default_entry = None
            alternate_entry = {
                'service_credentials': {'interface': ['internalURL']}
            }

        logging.info('changing config: {}'.format(set_alternate))
        self.restart_on_changed(
            CeilometerTest.CONF_FILE,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            _services)

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started.
        """
        with self.pause_resume(self.services):
            logging.info("Testing pause and resume")
