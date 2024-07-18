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

import json
import logging
import tenacity

from zaza.openstack.charm_tests.manila_ganesha.setup import (
    MANILA_GANESHA_TYPE_NAME,
)

from zaza import sync_wrapper
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
            units = zaza.model.get_units(ganesha)
            ganesha_unit = units[0]
            hacluster_unit = zaza_utils_juju.get_subordinate_units(
                [ganesha_unit.entity_id],
                charm_name='hacluster')
            logging.info('Ganesha in hacluster mode: {}'.format(
                bool(hacluster_unit)))

            for unit in units:
                if hacluster_unit:
                    # While we really only need to run this on the machine
                    # hosting # nfs-ganesha and manila-share, running it
                    # everywhere isn't harmful. Pacemaker handles restarting
                    # the services
                    logging.info(
                        "For %s, running systemctl stop manila-share, "
                        "kill -HUP pidof ganesha.nfsd", unit.entity_id)
                    zaza.model.run_on_unit(
                        unit.entity_id,
                        "systemctl stop manila-share")
                    zaza.model.run_on_unit(
                        unit.entity_id,
                        'pidof ganesha.nfsd && '
                        'kill -HUP $(pidof ganesha.nfsd)')
                else:
                    logging.info(
                        "For %s, running systemctl restart manila-share "
                        "nfs-ganesha", unit.entity_id)
                    zaza.model.run_on_unit(
                        unit.entity_id,
                        "systemctl restart manila-share nfs-ganesha")

            if hacluster_unit:
                # now ensure that at least one manila-share and nfs-ganesha is
                # at least running.
                unit_names = [unit.entity_id for unit in units]
                logging.info(
                    "Blocking until at least one manila-share is running")
                self._block_until_at_least_one_unit_running_services(
                    unit_names, ['manila-share'])
            else:
                # block until they are all running.
                for unit in units:
                    zaza.model.block_until_service_status(
                        unit_name=unit.entity_id,
                        services=['manila-share'],
                        target_status='running'
                    )

        return True

    @staticmethod
    def _block_until_at_least_one_unit_running_services(
            units, services, model_name=None, timeout=None):
        """Block until at least one unit is running the provided services.

        :param units: List of names of unit to run action on
        :type units: List[str]
        :param services: List of services to check
        :type services: List[str]
        """
        async def _check_services():
            for unit_name in units:
                running_services = {}
                for service in services:
                    command = r"pidof -x '{}'".format(service)
                    out = await zaza.model.async_run_on_unit(
                        unit_name,
                        command,
                        model_name=model_name,
                        timeout=timeout)
                    response_size = len(out['Stdout'].strip())
                    # response_size == 0 means NOT running.
                    running_services[service] = (response_size > 0)
                states = ', '.join('{}: {}'.format(k, v)
                                   for k, v in
                                   running_services.items())
                # Note this blocks the async call, but we don't really care as
                # it should only be a short time.
                logging.info('For unit {unit}, services: {states}'
                             .format(unit=unit_name, states=states))
                active_services = [
                    service
                    for service, running in running_services.items()
                    if running]
                if len(active_services) == len(services):
                    # all services are running
                    return True
            # No unit has all services running
            return False

        async def _await_block():
            await zaza.model.async_block_until(
                _check_services, timeout=timeout)

        sync_wrapper(_await_block)()

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

    def _make_ceph_healthy(self, model_name=None):
        """Force ceph into a healthy status."""
        # wait for 30 seconds for self to get healthy
        healthy, ceph_status = self._wait_for_ceph_fs_healthy(
            repeat=6, interval=5, model_name=None)
        if healthy:
            return
        logging.info("Ceph is not healthy: %s", ceph_status)
        # evict any clients.
        self._evict_ceph_mds_clients(model_name)
        self._restart_share_instance()
        healthy, ceph_status = self._wait_for_ceph_fs_healthy(
            repeat=10, interval=15, model_name=None)

    def _wait_for_ceph_fs_healthy(
            self, repeat=30, interval=20, model_name=None):
        """Wait until the ceph health is healthy."""
        logging.info("Waiting for ceph to be healthy ...")
        try:
            for attempt in tenacity.Retrying(
                wait=tenacity.wait_fixed(interval),
                stop=tenacity.stop_after_attempt(repeat),
                reraise=True,
            ):
                logging.info("... checking Ceph")
                with attempt:
                    healthy, ceph_status = self._check_ceph_fs_health(
                        model_name)
                    if not healthy:
                        raise RuntimeError("Ceph was unhealthy: {}"
                                           .format(ceph_status))
        except RuntimeError:
            # we are only retrying for the retries, not to raise an exception.
            pass
        if healthy:
            logging.info("...Ceph is healthy")
        else:
            logging.info("...Ceph is not healthy %s", ceph_status)
        return healthy, ceph_status

    @staticmethod
    def _check_ceph_fs_health(model_name=None):
        """Check to see if the ceph fs system is healthy."""
        cmd_result = zaza.model.run_on_leader(
            "ceph-mon",
            "sudo ceph status --format=json",
            model_name=model_name)
        status = json.loads(cmd_result['Stdout'])
        ceph_status = status['health']['status']
        return (ceph_status == "HEALTH_OK"), ceph_status

    @staticmethod
    def _evict_ceph_mds_clients(model_name=None):
        """Evict and ceph mds clients present.

        Essentially work around a manila-ganesha deployment bug:
        https://bugs.launchpad.net/charm-manila-ganesha/+bug/2073498
        """
        # NOTE:evicting a client adds them to the mds blocklist; this shouldn't
        # matter for the ephemeral nature of the test.
        # get the list of clients.
        cmd_results = zaza.model.run_on_leader(
            "ceph-mon", "sudo ceph tell mds.0 client ls",
            model_name=model_name)
        result = json.loads(cmd_results['Stdout'])
        client_ids = [client['id'] for client in result]
        logging.info("Evicting clients %s", ", ".join(
            str(c) for c in client_ids))
        # now evict the clients.
        for client in client_ids:
            logging.info("Evicting client %s", client)
            zaza.model.run_on_leader(
                "ceph-mon",
                "sudo ceph tell mds.0 client evict id={}".format(client),
                model_name=model_name)

    def test_manila_share(self):
        """Test that a manila-ganesha share can be accessed on two instances.

        This overrides the base manila test by prefixing a make ceph healthy
        stage.
        """
        # force a restart to clear out any clients that may be hanging around
        # due to restarts on manila-ganesha during deployment; this also forces
        # an HA manila into a stable state.
        self._restart_share_instance()
        # Clean out any old clients causes by restarting manila-ganesha shares
        # and ganesha.nfsd daemons.
        self._make_ceph_healthy()
        super().test_manila_share()
