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

"""Encapsulate Manila Ganesha testing."""

import logging
import tenacity

from zaza.openstack.charm_tests.manila_ganesha.setup import (
    MANILA_GANESHA_TYPE_NAME,
)

import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.charm_tests.manila.tests as manila_tests
import zaza.model
import zaza.utilities.juju as zaza_utils_juju


class ManilaGaneshaTests(manila_tests.ManilaBaseTest):
    """Encapsulate Manila Ganesha tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(ManilaGaneshaTests, cls).setUpClass()
        cls.share_name = 'cephnfsshare1'
        cls.share_type_name = MANILA_GANESHA_TYPE_NAME
        cls.share_protocol = 'nfs'

    def _restart_share_instance(self):
        logging.info('Restarting manila-share and nfs-ganesha')
        # It would be better for this to derive the application name,
        # manila-ganesha-az1, from deployed instances of the manila-ganesha
        # charm; however, that functionality isn't present yet in zaza, so
        # this is a best-guestimate arrived at by looking for applications
        # with the word 'ganesha' in their names.
        ganeshas = [
            app for app in zaza.model.sync_deployed(model_name=self.model_name)
            if 'ganesha' in app and 'mysql' not in app]
        logging.info('Found ganeshas in model {}: {}'.format(
            self.model_name,
            ganeshas))
        for ganesha in ganeshas:
            ganesha_unit = zaza.model.get_units(ganesha)[0]
            hacluster_unit = zaza_utils_juju.get_subordinate_units(
                [ganesha_unit.entity_id],
                charm_name='hacluster')
            logging.info('Ganesha in hacluster mode: {}'.format(
                bool(hacluster_unit)))

            for unit in zaza.model.get_units(ganesha):
                if hacluster_unit:
                    # While we really only need to run this on the machine
                    # hosting # nfs-ganesha and manila-share, running it
                    # everywhere isn't harmful. Pacemaker handles restarting
                    # the services
                    zaza.model.run_on_unit(
                        unit.entity_id,
                        "systemctl stop manila-share nfs-ganesha")
                else:
                    zaza.model.run_on_unit(
                        unit.entity_id,
                        "systemctl restart manila-share nfs-ganesha")

        return True

    def _run_nrpe_check_command(self, commands):
        try:
            zaza.model.get_application("nrpe")
        except KeyError:
            self.skipTest("Skipped NRPE checks since nrpe is not deployed.")

        units = []
        try:
            units = zaza.model.get_units("manila-ganesha-az1")
        except KeyError:
            self.skipTest("Skipped NRPE checks since"
                          "manila-ganesha-az1 is not deployed.")

        for attempt in tenacity.Retrying(
            wait=tenacity.wait_fixed(20),
            stop=tenacity.stop_after_attempt(2),
            reraise=True,
        ):
            with attempt:
                ret = generic_utils.check_commands_on_units(commands, units)
                self.assertIsNone(ret, msg=ret)

    def test_903_nrpe_custom_plugin_checks(self):
        """Confirm that the NRPE custom plugin files are created."""
        plugins = [
            "check_nfs_conn",
            "check_nfs_exports",
            "check_nfs_services",
        ]

        commands = [
            "ls /usr/local/lib/nagios/plugins/{}".format(plugin)
            for plugin in plugins
        ]

        self._run_nrpe_check_command(commands)

    def test_904_nrpe_custom_cronjob_checks(self):
        """Confirm that the NRPE custom cron job files are created."""
        cronjobs = [
            "nfs_conn",
            "nfs_exports",
            "nfs_services",
        ]

        commands = [
            "ls /etc/cron.d/nagios-check_{}".format(cronjob)
            for cronjob in cronjobs
        ]

        self._run_nrpe_check_command(commands)

    def test_905_nrpe_custom_service_checks(self):
        """Confirm that the NRPE custom service files are created."""
        services = [
            "nfs_conn",
            "nfs_exports",
            "nfs_services",
        ]

        commands = [
            "egrep -oh "
            "/usr/local.* /etc/nagios/nrpe.d/check_{}.cfg".format(service)
            for service in services
        ]

        self._run_nrpe_check_command(commands)
