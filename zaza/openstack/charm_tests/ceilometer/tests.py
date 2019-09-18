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

import logging

import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.test_utils as test_utils


class CeilometerTest(test_utils.OpenStackBaseTest):
    """Encapsulate Ceilometer tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Ceilometer tests."""
        super(CeilometerTest, cls).setUpClass()

    # NOTE(beisner): need to add more functional tests

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change."""
        # Expected default and alternate values
        current_value = openstack_utils.get_application_config_option(
            'ceilometer', 'debug'
        )
        assert type(current_value) == bool
        new_value = not current_value

        # Convert bool to str
        current_value = str(current_value)
        new_value = str(new_value)

        set_default = {'debug': current_value}
        set_alternate = {'debug': new_value}
        default_entry = {'DEFAULT': {'debug': [current_value]}}
        alternate_entry = {'DEFAULT': {'debug': [new_value]}}

        # Config file affected by juju set config change
        conf_file = '/etc/ceilometer/ceilometer.conf'
        services = {}
        current_release = openstack_utils.get_os_release()
        xenial_pike = openstack_utils.get_os_release('xenial_pike')
        xenial_ocata = openstack_utils.get_os_release('xenial_ocata')
        xenial_newton = openstack_utils.get_os_release('xenial_newton')
        trusty_mitaka = openstack_utils.get_os_release('trusty_mitaka')
        trusty_liberty = openstack_utils.get_os_release('trusty_liberty')

        if current_release >= xenial_pike:
            services = {
                'ceilometer-polling: AgentManager worker(0)': conf_file,
                'ceilometer-agent-notification: NotificationService worker(0)':
                    conf_file,
            }
        elif current_release >= xenial_ocata:
            services = {
                'ceilometer-collector: CollectorService worker(0)': conf_file,
                'ceilometer-polling: AgentManager worker(0)': conf_file,
                'ceilometer-agent-notification: NotificationService worker(0)':
                    conf_file,
                'apache2': conf_file,
            }
        elif current_release >= xenial_newton:
            services = {
                'ceilometer-collector - CollectorService(0)': conf_file,
                'ceilometer-polling - AgentManager(0)': conf_file,
                'ceilometer-agent-notification - NotificationService(0)':
                    conf_file,
                'ceilometer-api': conf_file,
            }
        else:
            services = {
                'ceilometer-collector': conf_file,
                'ceilometer-api': conf_file,
                'ceilometer-agent-notification': conf_file,
            }

            if current_release < trusty_mitaka:
                services['ceilometer-alarm-notifier'] = conf_file
                services['ceilometer-alarm-evaluator'] = conf_file

            if current_release >= trusty_liberty:
                # Liberty and later
                services['ceilometer-polling'] = conf_file
            else:
                # Juno and earlier
                services['ceilometer-agent-central'] = conf_file

        logging.info('changing config: {}'.format(set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            services)

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started.
        """
        self.pause_resume(['ceilometer'])
