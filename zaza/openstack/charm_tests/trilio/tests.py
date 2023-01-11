#!/usr/bin/env python3

# Copyright 2018 Canonical Ltd.
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

"""Collection of tests for vault."""

import logging
import tenacity
import unittest

import zaza.model as zaza_model

import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.configure.guest as guest_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.utilities.generic as generic_utils
from zaza.utilities import juju as juju_utils


def _resource_reaches_status(
    unit, auth_args, status_command, full_status_command, resource_id,
    target_status
):
    """Wait for a workload resource to reach a status.

    :param unit: unit to run cli commands on
    :type unit: zaza_model.Unit
    :param auth_args: authentication arguments for command
    :type auth_args: str
    :param status_command: command to execute to get the resource status that
                           is expected to reach target_status
    :type status_command: str
    :param full_status_command: command to execute to get insights on why the
                                resource failed to reach target_status
    :type full_status_command: str
    :param resource_id: resource ID to monitor
    :type resource_id: str
    :param target_status: status to monitor for
    :type target_status: str
    """
    resource_status = (
        juju_utils.remote_run(
            unit,
            remote_cmd=status_command.format(
                auth_args=auth_args, resource_id=resource_id
            ),
            timeout=180,
            fatal=True,
        )
        .strip()
        .split("\n")[-1]
    )
    logging.info(
        "Checking resource ({}) status: {}".format(
            resource_id, resource_status
        )
    )
    if resource_status == target_status:
        return

    full_resource_status = (
        juju_utils.remote_run(
            unit,
            remote_cmd=full_status_command.format(
                auth_args=auth_args, resource_id=resource_id
            ),
            timeout=180,
            fatal=True,
        )
        .strip()
    )

    raise Exception("Resource not ready:\n{}".format(full_resource_status))


class WorkloadmgrCLIHelper(object):
    """Helper for working with workloadmgrcli."""

    WORKLOAD_CREATE_CMD = (
        "openstack {auth_args} workload create "
        "--instance instance-id={instance_id} "
        "-f value -c ID"
    )

    WORKLOAD_STATUS_CMD = (
        "openstack {auth_args} workload show "
        "-f value -c status "
        "{resource_id}"
    )

    WORKLOAD_FULL_STATUS_CMD = (
        "openstack {auth_args} workload show "
        "{resource_id}"
    )

    SNAPSHOT_CMD = (
        "openstack {auth_args} workload snapshot --full {workload_id}"
    )

    SNAPSHOT_ID_CMD = (
        "openstack {auth_args} workload snapshot list "
        "--workload_id {workload_id} "
        "-f value -c ID"
    )

    SNAPSHOT_STATUS_CMD = (
        "openstack {auth_args} workload snapshot show "
        "-f value -c status "
        "{resource_id}"
    )

    SNAPSHOT_FULL_STATUS_CMD = (
        "openstack {auth_args} workload snapshot show "
        "{resource_id}"
    )

    ONECLICK_RESTORE_CMD = (
        "openstack {auth_args} workload snapshot oneclick-restore "
        "{snapshot_id} "
    )

    RESTORE_LIST_CMD = (
        "openstack {auth_args} workloadmgr restore list "
        "--snapshot_id {snapshot_id} "
        "-f value -c ID"
    )

    RESTORE_STATUS_CMD = (
        "openstack {auth_args} workloadmgr restore show "
        "-f value -c status "
        "{resource_id}"
    )

    RESTORE_FULL_STATUS_CMD = (
        "openstack {auth_args} workloadmgr restore show "
        "{resource_id}"
    )

    def __init__(self, keystone_client):
        """Initialise helper.

        :param keystone_client: keystone client
        :type keystone_client: keystoneclient.v3
        """
        self.trilio_wlm_unit = zaza_model.get_first_unit_name(
            "trilio-wlm"
        )
        self.auth_args = openstack_utils.get_cli_auth_args(keystone_client)

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(zaza_model.CommandRunFailed),
        wait=tenacity.wait_fixed(10),  # interval between retries
        stop=tenacity.stop_after_attempt(5))  # retry 10 times
    def wlm_run_cmd(self, remote_cmd):
        """Run command on unit and return the output.

        :param remote_cmd: Command to execute on unit
        :type remote_cmd: string
        :returns: Juju run output
        :rtype: string
        :raises: model.CommandRunFailed
        """
        logging.info("Running {}".format(remote_cmd))
        return juju_utils.remote_run(
            self.trilio_wlm_unit,
            remote_cmd,
            timeout=180,
            fatal=True,
        ).strip()

    def create_workload(self, instance_id):
        """Create a new workload.

        :param instance_id: instance ID to create workload from
        :type instance_id: str
        :returns: workload ID
        :rtype: str
        """
        workload_id = self.wlm_run_cmd(
            self.WORKLOAD_CREATE_CMD.format(
                auth_args=self.auth_args,
                instance_id=instance_id
            )
        )

        retryer = tenacity.Retrying(
            wait=tenacity.wait_exponential(multiplier=1, max=30),
            stop=tenacity.stop_after_delay(180),
            reraise=True,
        )
        retryer(
            _resource_reaches_status,
            self.trilio_wlm_unit,
            self.auth_args,
            self.WORKLOAD_STATUS_CMD,
            self.WORKLOAD_FULL_STATUS_CMD,
            workload_id,
            "available",
        )

        return workload_id

    def create_snapshot(self, workload_id):
        """Create a new snapshot.

        :param workload_id: workload ID to create snapshot from
        :type workload_id: str
        :returns: snapshot ID
        :rtype: str
        """
        self.wlm_run_cmd(
            self.SNAPSHOT_CMD.format(
                auth_args=self.auth_args,
                workload_id=workload_id
            )
        )
        snapshot_id = self.wlm_run_cmd(
            self.SNAPSHOT_ID_CMD.format(
                auth_args=self.auth_args,
                workload_id=workload_id
            )
        )

        retryer = tenacity.Retrying(
            wait=tenacity.wait_exponential(multiplier=1, max=30),
            stop=tenacity.stop_after_delay(1200),
            reraise=True,
        )

        retryer(
            _resource_reaches_status,
            self.trilio_wlm_unit,
            self.auth_args,
            self.SNAPSHOT_STATUS_CMD,
            self.SNAPSHOT_FULL_STATUS_CMD,
            snapshot_id,
            "available",
        )

        return snapshot_id

    def oneclick_restore(self, snapshot_id):
        """Restore a workload from a snapshot.

        :param snapshot_id: snapshot ID to restore
        :type snapshot_id: str
        """
        self.wlm_run_cmd(
            self.ONECLICK_RESTORE_CMD.format(
                auth_args=self.auth_args,
                snapshot_id=snapshot_id
            )
        )
        restore_id = self.wlm_run_cmd(
            self.RESTORE_LIST_CMD.format(
                auth_args=self.auth_args,
                snapshot_id=snapshot_id
            )
        )

        retryer = tenacity.Retrying(
            wait=tenacity.wait_exponential(multiplier=1, max=30),
            stop=tenacity.stop_after_delay(720),
            reraise=True,
        )

        retryer(
            _resource_reaches_status,
            self.trilio_wlm_unit,
            self.auth_args,
            self.RESTORE_STATUS_CMD,
            self.RESTORE_FULL_STATUS_CMD,
            restore_id,
            "available",
        )

        return restore_id


class TrilioBaseTest(test_utils.OpenStackBaseTest):
    """Base test class for charms."""

    RESOURCE_PREFIX = "zaza-triliovault-tests"
    conf_file = None

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super().setUpClass(application_name=cls.application_name)
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session
        )
        cls.nova_client = openstack_utils.get_nova_session_client(
            cls.keystone_session
        )
        cls.keystone_client = openstack_utils.get_keystone_session_client(
            cls.keystone_session
        )

    def test_restart_on_config_change(self):
        """Check restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        set_default = {"debug": False}
        set_alternate = {"debug": True}

        # Make config change, check for service restarts
        self.restart_on_changed(
            self.conf_file,
            set_default,
            set_alternate,
            {"DEFAULT": {"debug": ["False"]}},
            {"DEFAULT": {"debug": ["True"]}},
            self.services,
        )

    def test_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(self.services, pgrep_full=False):
            logging.info("Testing pause resume")

    def test_snapshot_workload(self):
        """Ensure that a workload can be created and snapshot'ed."""
        # Setup volume and instance and attach one to the other
        volume = openstack_utils.create_volume(
            self.cinder_client,
            size="1",
            name="{}-100-vol".format(self.RESOURCE_PREFIX),
        )

        instance = guest_utils.launch_instance_retryer(
            glance_setup.CIRROS_IMAGE_NAME,
            vm_name="{}-server".format(self.RESOURCE_PREFIX),
        )

        # Trilio need direct access to ceph - OMG
        openstack_utils.attach_volume(
            self.nova_client, volume.id, instance.id
        )

        workloadmgrcli = WorkloadmgrCLIHelper(self.keystone_client)

        # Create workload using instance
        logging.info("Creating workload configuration")
        workload_id = workloadmgrcli.create_workload(instance.id)
        logging.info("Created workload: {}".format(workload_id))

        logging.info("Initiating snapshot")
        snapshot_id = workloadmgrcli.create_snapshot(workload_id)
        logging.info(
            "Snapshot of workload {} created: {}".format(
                workload_id, snapshot_id
            )
        )

        logging.info("Deleting server and volume ready for restore")
        openstack_utils.delete_resource(
            self.nova_client.servers, instance.id, "deleting instance"
        )
        # NOTE: Trilio leaves a snapshot in place -
        #       drop before volume deletion.
        for (
            volume_snapshot
        ) in self.cinder_client.volume_snapshots.list():
            openstack_utils.delete_resource(
                self.cinder_client.volume_snapshots,
                volume_snapshot.id,
                "deleting snapshot",
            )
        openstack_utils.delete_resource(
            self.cinder_client.volumes, volume.id, "deleting volume"
        )

        logging.info("Initiating restore")
        workloadmgrcli.oneclick_restore(snapshot_id)

    def test_update_trilio_action(self):
        """Test that the action runs successfully."""
        action_name = 'update-trilio'
        actions = zaza_model.get_actions(
            self.application_name)
        if action_name not in actions:
            raise unittest.SkipTest(
                'Action {} not defined'.format(action_name))

        generic_utils.assertActionRanOK(zaza_model.run_action(
            self.lead_unit,
            action_name,
            action_params={},
            model_name=self.model_name)
        )


class TrilioGhostNFSShareTest(TrilioBaseTest):
    """Tests for Trilio charms providing the ghost-share action."""

    def test_ghost_nfs_share(self):
        """Ensure ghost-share action bind mounts NFS share."""
        generic_utils.assertActionRanOK(zaza_model.run_action(
            self.lead_unit,
            'ghost-share',
            action_params={
                'nfs-shares': '10.20.0.1:/srv/ghost-testing'
            },
            model_name=self.model_name)
        )


class TrilioWLMBaseTest(TrilioBaseTest):
    """Tests for Trilio Workload Manager charm."""

    conf_file = "/etc/workloadmgr/workloadmgr.conf"
    application_name = "trilio-wlm"

    services = [
        "workloadmgr-api",
        "workloadmgr-scheduler",
        "workloadmgr-workloads",
        "workloadmgr-cron",
    ]


class TrilioDMAPITest(TrilioBaseTest):
    """Tests for Trilio Data Mover API charm."""

    conf_file = "/etc/dmapi/dmapi.conf"
    application_name = "trilio-dm-api"

    services = ["dmapi-api"]


class TrilioDataMoverBaseTest(TrilioBaseTest):
    """Tests for Trilio Data Mover charm."""

    conf_file = "/etc/tvault-contego/tvault-contego.conf"
    application_name = "trilio-data-mover"

    services = ["tvault-contego"]


class TrilioDataMoverNFSTest(TrilioDataMoverBaseTest, TrilioGhostNFSShareTest):
    """Tests for Trilio Data Mover charm backed by NFS."""

    application_name = "trilio-data-mover"


class TrilioDataMoverS3Test(TrilioDataMoverBaseTest):
    """Tests for Trilio Data Mover charm backed by S3."""

    application_name = "trilio-data-mover"


class TrilioWLMNFSTest(TrilioWLMBaseTest, TrilioGhostNFSShareTest):
    """Tests for Trilio WLM charm backed by NFS."""

    application_name = "trilio-wlm"


class TrilioWLMS3Test(TrilioWLMBaseTest):
    """Tests for Trilio WLM charm backed by S3."""

    application_name = "trilio-wlm"


class TrilioHorizonPluginTest(test_utils.OpenStackBaseTest):
    """Tests for Trilio Horizon Plugin charm."""

    application_name = "trilio-horizon-plugin"
    local_settings_file = '/etc/openstack-dashboard/local_settings.py'

    def installed_trilio_version(self):
        """Get the Trilio version from the installed package."""
        action_out = zaza_model.run_on_leader(
            self.application_name,
            ("dpkg-query --showformat='${Version}' "
             "--show python3-tvault-horizon-plugin"))
        if 'no packages found' in action_out['stderr']:
            action_out = zaza_model.run_on_leader(
                self.application_name,
                ("dpkg-query --showformat='${Version}' "
                 "--show tvault-horizon-plugin"))
        return float('.'.join(action_out['stdout'].split('.')[:2]))

    def set_openstack_encryption_support(self, os_enc_support):
        """Set the openstack-encryption-support option."""
        zaza_model.set_application_config(
            self.application_name,
            {'openstack-encryption-support': str(os_enc_support)})
        logging.info(
            "Checking openstack encryption support is set to {}".format(
                os_enc_support))
        zaza_model.block_until_file_has_contents(
            self.application_name,
            self.local_settings_file,
            'OPENSTACK_ENCRYPTION_SUPPORT = {}'.format(os_enc_support))

    def test_encryption_settings(self):
        """Test trilio encryption options."""
        expect = self.installed_trilio_version() >= 4.2
        logging.info(
            "Checking Trilio encryption support is set to {}".format(expect))
        zaza_model.block_until_file_has_contents(
            self.application_name,
            self.local_settings_file,
            'TRILIO_ENCRYPTION_SUPPORT = {}'.format(expect))
        expect = zaza_model.get_application_config(
            self.application_name)['openstack-encryption-support']['value']
        self.set_openstack_encryption_support(
            expect)
        expect = not expect
        self.set_openstack_encryption_support(
            expect)
        # Put config back to original setting
        expect = not expect
        self.set_openstack_encryption_support(
            expect)
