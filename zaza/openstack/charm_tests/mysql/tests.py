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

"""MySQL/Percona Cluster Testing."""

import json
import logging
import os
import re
import tempfile
import time

import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.juju as juju_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.utilities.generic as generic_utils


PXC_SEEDED_FILE = "/var/lib/percona-xtradb-cluster/seeded"


class MySQLBaseTest(test_utils.OpenStackBaseTest):
    """Base for mysql charm tests."""

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running mysql tests."""
        super().setUpClass(application_name=application_name)
        cls.application = "mysql"
        cls.services = ["mysqld"]
        # Config file affected by juju set config change
        cls.conf_file = "/etc/mysql/mysql.conf.d/mysqld.cnf"

    def get_root_password(self):
        """Get the MySQL root password.

        :returns: Password
        :rtype: str
        """
        return zaza.model.run_on_leader(
            self.application,
            "leader-get root-password")["Stdout"].strip()

    def get_leaders_and_non_leaders(self):
        """Get leader node and non-leader nodes of percona.

        Update and set on the object the leader node and list of non-leader
        nodes.

        :returns: None
        :rtype: None
        """
        status = zaza.model.get_status().applications[self.application]
        # Reset
        self.leader = None
        self.non_leaders = []
        for unit in status["units"]:
            if status["units"][unit].get("leader"):
                self.leader = unit
            else:
                self.non_leaders.append(unit)
        return self.leader, self.non_leaders

    def get_cluster_status(self):
        """Get cluster status.

        Return cluster status dict from the cluster-status action or raise
        assertion error.

        :returns: Dictionary of cluster status
        :rtype: dict
        """
        logging.info("Running cluster-status action")
        action = zaza.model.run_action_on_leader(
            self.application,
            "cluster-status",
            action_params={})
        assert action.data.get("results") is not None, (
            "Cluster status action failed: No results: {}"
            .format(action.data))
        assert action.data["results"].get("cluster-status") is not None, (
            "Cluster status action failed: No cluster-status: {}"
            .format(action.data))
        return json.loads(action.data["results"]["cluster-status"])

    def get_rw_primary_node(self):
        """Get RW primary node.

        Return RW primary node unit.

        :returns: Unit object of primary node
        :rtype: Union[Unit, None]
        """
        _status = self.get_cluster_status()
        _primary_ip = _status['groupInformationSourceMember']
        if ":" in _primary_ip:
            _primary_ip = _primary_ip.split(':')[0]
        units = zaza.model.get_units(self.application_name)
        for unit in units:
            if _primary_ip in unit.public_address:
                return unit


class MySQLCommonTests(MySQLBaseTest):
    """Common mysql charm tests."""

    def test_110_mysqldump(self):
        """Backup mysql.

        Run the mysqldump action.
        """
        _db = "keystone"
        _file_key = "mysqldump-file"
        logging.info("Execute mysqldump action")
        # Need to change strict mode to be able to dump database
        if self.application_name == "percona-cluster":
            action = zaza.model.run_action_on_leader(
                self.application_name,
                "set-pxc-strict-mode",
                action_params={"mode": "MASTER"})

        action = zaza.model.run_action_on_leader(
            self.application,
            "mysqldump",
            action_params={"databases": _db})
        _results = action.data["results"]
        assert _db in _results[_file_key], (
            "Mysqldump action failed: {}".format(action.data))
        logging.info("Passed mysqldump action test.")

    def test_910_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change max connections and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        set_default = {"max-connections": "600"}
        set_alternate = {"max-connections": "1000"}

        # Make config change, check for service restarts
        logging.info("Setting max connections ...")
        self.restart_on_changed(
            self.conf_file,
            set_default,
            set_alternate,
            {}, {},
            self.services)
        logging.info("Passed restart on changed test.")

    def test_920_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(self.services):
            logging.info("Testing pause resume")
        logging.info("Passed pause and resume test.")


class PerconaClusterBaseTest(MySQLBaseTest):
    """Base for percona-cluster charm tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running percona-cluster tests."""
        super().setUpClass()
        cls.application = "percona-cluster"
        # This is the service pidof will attempt to find
        # rather than what systemctl uses
        cls.services = ["mysqld"]
        cls.vip = os.environ.get("TEST_VIP00")
        # Config file affected by juju set config change
        cls.conf_file = "/etc/mysql/percona-xtradb-cluster.conf.d/mysqld.cnf"

    def get_wsrep_value(self, attr):
        """Get wsrrep value from the DB.

        :param attr: Attribute to query
        :type attr: str
        :returns: wsrep value
        :rtype: str
        """
        root_password = self.get_root_password()
        cmd = ("mysql -uroot -p{} -e\"show status like '{}';\"| "
               "grep {}".format(root_password, attr, attr))
        output = zaza.model.run_on_leader(
            self.application, cmd)["Stdout"].strip()
        value = re.search(r"^.+?\s+(.+)", output).group(1)
        logging.info("%s = %s" % (attr, value))
        return value

    def is_pxc_bootstrapped(self):
        """Determine if the cluster is bootstrapped.

        Query the wsrep_ready status in the DB.

        :returns: True if bootstrapped
        :rtype: boolean
        """
        value = self.get_wsrep_value("wsrep_ready")
        return value.lower() in ["on", "ready"]

    def get_cluster_size(self):
        """Determine the cluster size.

        Query the wsrep_cluster size in the DB.

        :returns: Numeric cluster size
        :rtype: str
        """
        return self.get_wsrep_value("wsrep_cluster_size")

    def get_crm_master(self):
        """Determine CRM master for the VIP.

        Query CRM to determine which node hosts the VIP.

        :returns: Unit name
        :rtype: str
        """
        for unit in zaza.model.get_units(self.application):
            logging.info("Checking {}".format(unit.entity_id))
            # is the vip running here?
            cmd = "ip -br addr"
            result = zaza.model.run_on_unit(unit.entity_id, cmd)
            output = result.get("Stdout").strip()
            logging.info(output)
            if self.vip in output:
                logging.info("vip ({}) running in {}".format(
                    self.vip,
                    unit.entity_id)
                )
                return unit.entity_id


class PerconaClusterCharmTests(MySQLCommonTests, PerconaClusterBaseTest):
    """Percona-cluster charm tests.

    .. note:: these have tests have been ported from amulet tests
    """

    def test_100_bootstrapped_and_clustered(self):
        """Ensure PXC is bootstrapped and that peer units are clustered."""
        self.units = zaza.model.get_application_config(
            self.application)["min-cluster-size"]["value"]
        logging.info("Ensuring PXC is bootstrapped")
        msg = "Percona cluster failed to bootstrap"
        assert self.is_pxc_bootstrapped(), msg

        logging.info("Checking PXC cluster size >= {}".format(self.units))
        cluster_size = int(self.get_cluster_size())
        msg = ("Percona cluster unexpected size"
               " (wanted=%s, cluster_size=%s)" % (self.units, cluster_size))
        assert cluster_size >= self.units, msg

        logging.info("Ensuring PXC seeded file is present")
        zaza.model.block_until_file_has_contents(self.application,
                                                 PXC_SEEDED_FILE, "done")

    def test_130_change_root_password(self):
        """Change root password.

        Change the root password and verify the change was effectively applied.
        """
        new_root_passwd = "openstack"

        cmd = ("mysql -uroot -p{} -e\"select 1;\""
               .format(self.get_root_password()))
        result = zaza.model.run_on_leader(self.application, cmd)
        code = result.get("Code")
        output = result.get("Stdout").strip()

        assert code == "0", output

        with self.config_change(
                {"root-password": new_root_passwd},
                {"root-password": new_root_passwd}):

            logging.info("Wait till model is idle ...")
            zaza.model.block_until_all_units_idle()
            # try to connect using the new root password
            cmd = "mysql -uroot -p{} -e\"select 1;\" ".format(new_root_passwd)
            result = zaza.model.run_on_leader(self.application, cmd)
            code = result.get("Code")
            output = result.get("Stdout").strip()

            assert code == "0", output


class PerconaClusterColdStartTest(PerconaClusterBaseTest):
    """Percona Cluster cold start tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running percona-cluster cold start tests."""
        super(PerconaClusterColdStartTest, cls).setUpClass()
        cls.overcloud_keystone_session = (
            openstack_utils.get_undercloud_keystone_session())
        cls.nova_client = openstack_utils.get_nova_session_client(
            cls.overcloud_keystone_session)

    def resolve_update_status_errors(self):
        """Resolve update-status hooks error.

        This should *only* be used after an instance hard reboot to handle the
        situation where a update-status hook was running when the unit was
        rebooted.
        """
        zaza.model.resolve_units(
            application_name='percona-cluster',
            erred_hook='update-status',
            wait=True)
        zaza.model.resolve_units(
            application_name='hacluster',
            erred_hook='update-status',
            wait=True)

    def test_100_cold_start_bootstrap(self):
        """Bootstrap a non-leader node.

        After bootstrapping a non-leader node, notify bootstrapped on the
        leader node.
        """
        _machines = sorted(
            juju_utils.get_machine_uuids_for_application(self.application))
        # Stop Nodes
        # Avoid hitting an update-status hook
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()
        logging.info("Stopping instances: {}".format(_machines))
        for uuid in _machines:
            self.nova_client.servers.stop(uuid)
        logging.info("Wait till all machines are shutoff ...")
        for uuid in _machines:
            openstack_utils.resource_reaches_status(self.nova_client.servers,
                                                    uuid,
                                                    expected_status='SHUTOFF',
                                                    stop_after_attempt=16)

        # Start nodes
        _machines.sort(reverse=True)
        logging.info("Starting instances: {}".format(_machines))
        for uuid in _machines:
            self.nova_client.servers.start(uuid)

        for unit in zaza.model.get_units(self.application):
            zaza.model.block_until_unit_wl_status(
                unit.entity_id,
                'unknown',
                negate_match=True)

        logging.info("Wait till model is idle ...")
        # XXX If a hook was executing on a unit when it was powered off
        #     it comes back in an error state.
        try:
            zaza.model.block_until_all_units_idle()
        except zaza.model.UnitError:
            self.resolve_update_status_errors()
            zaza.model.block_until_all_units_idle()

        logging.info("Wait for application states ...")
        for unit in zaza.model.get_units(self.application):
            try:
                zaza.model.run_on_unit(unit.entity_id, "hooks/update-status")
            except zaza.model.UnitError:
                self.resolve_update_status_errors()
                zaza.model.run_on_unit(unit.entity_id, "hooks/update-status")
        states = {"percona-cluster": {
            "workload-status": "blocked",
            "workload-status-message": "MySQL is down"}}
        zaza.model.wait_for_application_states(states=states)

        # Update which node is the leader and which are not
        _leader, _non_leaders = self.get_leaders_and_non_leaders()
        # We want to test the worst possible scenario which is the
        # non-leader with the highest sequence number. We will use the leader
        # for the notify-bootstrapped after. They just need to be different
        # units.
        logging.info("Execute bootstrap-pxc action after cold boot ...")
        zaza.model.run_action(
            _non_leaders[0],
            "bootstrap-pxc",
            action_params={})
        logging.info("Wait for application states ...")
        for unit in zaza.model.get_units(self.application):
            zaza.model.run_on_unit(unit.entity_id, "hooks/update-status")
        states = {"percona-cluster": {
            "workload-status": "waiting",
            "workload-status-message": "Unit waiting for cluster bootstrap"}}
        zaza.model.wait_for_application_states(
            states=states)
        logging.info("Execute notify-bootstrapped action after cold boot on "
                     "the leader node ...")
        zaza.model.run_action_on_leader(
            self.application,
            "notify-bootstrapped",
            action_params={})
        logging.info("Wait for application states ...")
        for unit in zaza.model.get_units(self.application):
            zaza.model.run_on_unit(unit.entity_id, "hooks/update-status")
        test_config = lifecycle_utils.get_charm_config(fatal=False)
        zaza.model.wait_for_application_states(
            states=test_config.get("target_deploy_status", {}))


class PerconaClusterScaleTests(PerconaClusterBaseTest):
    """Percona Cluster scale tests."""

    def test_100_kill_crm_master(self):
        """Ensure VIP failover.

        When killing the mysqld on the crm_master unit verify the VIP fails
        over.
        """
        logging.info("Testing failover of crm_master unit on mysqld failure")
        # we are going to kill the crm_master
        old_crm_master = self.get_crm_master()
        logging.info(
            "kill -9 mysqld on {}".format(old_crm_master)
        )
        cmd = "sudo killall -9 mysqld"
        zaza.model.run_on_unit(old_crm_master, cmd)

        logging.info("looking for the new crm_master")
        i = 0
        while i < 10:
            i += 1
            # XXX time.sleep roundup
            # https://github.com/openstack-charmers/zaza-openstack-tests/issues/46
            time.sleep(5)  # give some time to pacemaker to react
            new_crm_master = self.get_crm_master()

            if (new_crm_master and new_crm_master != old_crm_master):
                logging.info(
                    "New crm_master unit detected"
                    " on {}".format(new_crm_master)
                )
                break
        else:
            assert False, "The crm_master didn't change"

        # Check connectivity on the VIP
        # \ is required due to pep8 and parenthesis would make the assertion
        # always true.
        assert generic_utils.is_port_open("3306", self.vip), \
            "Cannot connect to vip"


class MySQLInnoDBClusterTests(MySQLCommonTests):
    """Mysql-innodb-cluster charm tests.

    Note: The restart on changed and pause/resume tests also validate the
    changing of the R/W primary. On each mysqld shutodown a new R/W primary is
    elected automatically by MySQL.
    """

    @classmethod
    def setUpClass(cls):
        """Run class setup for running mysql-innodb-cluster tests."""
        super().setUpClass()
        cls.application = "mysql-innodb-cluster"

    def test_100_cluster_status(self):
        """Checking cluster status.

        Run the cluster-status action.
        """
        logging.info("Execute cluster-status action")
        cluster_status = self.get_cluster_status()
        assert "OK" in cluster_status["defaultReplicaSet"]["status"], (
            "Cluster status is not OK: {}"
            .format(cluster_status))
        logging.info("Passed cluster-status action test.")

    def test_120_set_cluster_option(self):
        """Set cluster option.

        Run the set-cluster-option action.
        """
        _key = "autoRejoinTries"
        _value = "500"
        logging.info("Set cluster option {}={}".format(_key, _value))
        action = zaza.model.run_action_on_leader(
            self.application,
            "set-cluster-option",
            action_params={"key": _key, "value": _value})
        assert "Success" in action.data["results"]["outcome"], (
            "Set cluster option {}={} action failed: {}"
            .format(_key, _value, action.data))
        logging.info("Passed set cluster option action test.")


class MySQLInnoDBClusterColdStartTest(MySQLBaseTest):
    """Percona Cluster cold start tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running percona-cluster cold start tests."""
        super().setUpClass()
        cls.application = "mysql-innodb-cluster"
        cls.overcloud_keystone_session = (
            openstack_utils.get_undercloud_keystone_session())
        cls.nova_client = openstack_utils.get_nova_session_client(
            cls.overcloud_keystone_session)

    def resolve_update_status_errors(self):
        """Resolve update-status hooks error.

        This should *only* be used after an instance hard reboot to handle the
        situation where a update-status hook was running when the unit was
        rebooted.
        """
        zaza.model.resolve_units(
            application_name=self.application,
            erred_hook='update-status',
            wait=True, timeout=180)

    def test_100_reboot_cluster_from_complete_outage(self):
        """Reboot cluster from complete outage.

        After a cold start, reboot cluster from complete outage.
        """
        _machines = sorted(
            juju_utils.get_machine_uuids_for_application(self.application))
        # Stop Nodes
        # Avoid hitting an update-status hook
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()
        logging.info("Stopping instances: {}".format(_machines))
        for uuid in _machines:
            self.nova_client.servers.stop(uuid)
        logging.info("Wait till all machines are shutoff ...")
        for uuid in _machines:
            openstack_utils.resource_reaches_status(self.nova_client.servers,
                                                    uuid,
                                                    expected_status='SHUTOFF',
                                                    stop_after_attempt=16)

        # Start nodes
        _machines.sort(reverse=True)
        logging.info("Starting instances: {}".format(_machines))
        for uuid in _machines:
            self.nova_client.servers.start(uuid)

        logging.info(
            "Wait till all {} units are in state 'unkown' ..."
            .format(self.application))
        for unit in zaza.model.get_units(self.application):
            zaza.model.block_until_unit_wl_status(
                unit.entity_id,
                'unknown',
                negate_match=True)

        logging.info("Wait till model is idle ...")
        try:
            zaza.model.block_until_all_units_idle()
        except zaza.model.UnitError:
            self.resolve_update_status_errors()
            zaza.model.block_until_all_units_idle()

        logging.info("Clear error hooks after reboot ...")
        for unit in zaza.model.get_units(self.application):
            try:
                zaza.model.run_on_unit(unit.entity_id, "hooks/update-status")
            except zaza.model.UnitError:
                self.resolve_update_status_errors()
                zaza.model.run_on_unit(unit.entity_id, "hooks/update-status")

        logging.info(
            "Wait till all {} units are in state 'blocked' ..."
            .format(self.application))
        for unit in zaza.model.get_units(self.application):
            zaza.model.block_until_unit_wl_status(
                unit.entity_id,
                'blocked')

        # Wait until update-status hooks have completed
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()

        logging.info("Execute reboot-cluster-from-complete-outage "
                     "action after cold boot ...")
        # We do not know which unit has the most up to date data
        # run reboot-cluster-from-complete-outage until we get a success.
        for unit in zaza.model.get_units(self.application):
            action = zaza.model.run_action(
                unit.entity_id,
                "reboot-cluster-from-complete-outage",
                action_params={})
            if "Success" in action.data.get("results", {}).get("outcome", ""):
                break
            else:
                logging.info(action.data.get("results", {}).get("output", ""))

        assert "Success" in action.data["results"]["outcome"], (
            "Reboot cluster from complete outage action failed: {}"
            .format(action.data))
        logging.info("Wait for application states ...")
        for unit in zaza.model.get_units(self.application):
            zaza.model.run_on_unit(unit.entity_id, "hooks/update-status")
        test_config = lifecycle_utils.get_charm_config(fatal=False)
        zaza.model.wait_for_application_states(
            states=test_config.get("target_deploy_status", {}))

    def test_110_force_quorum_using_partition_of(self):
        """Force quorum using partition of instance with given address.

        After outage, cluster can end up without quorum. Force it.
        """
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()

        # Block all traffic across mysql instances: 0<-1, 1<-2 and 2<-0
        mysql_units = [unit for unit in zaza.model.get_units(self.application)]
        no_of_units = len(mysql_units)
        for index, unit in enumerate(mysql_units):
            next_unit = mysql_units[(index+1) % no_of_units]
            ip_address = next_unit.public_address
            cmd = "sudo iptables -A INPUT -s {} -j DROP".format(ip_address)
            zaza.model.async_run_on_unit(unit, cmd)

        logging.info(
            "Wait till all {} units are in state 'blocked' ..."
            .format(self.application))
        for unit in zaza.model.get_units(self.application):
            zaza.model.block_until_unit_wl_status(
                unit.entity_id,
                'blocked',
                negate_match=True)

        logging.info("Wait till model is idle ...")
        try:
            zaza.model.block_until_all_units_idle()
        except zaza.model.UnitError:
            self.resolve_update_status_errors()
            zaza.model.block_until_all_units_idle()

        logging.info("Execute force-quorum-using-partition-of action ...")

        # Select "quorum leader" unit
        leader_unit = mysql_units[0]
        action = zaza.model.run_action(
            leader_unit.entity_id,
            "force-quorum-using-partition-of",
            action_params={
                "address": leader_unit.public_address,
                'i-really-mean-it': True
            })

        assert "Success" in action.data["results"]["outcome"], (
            "Force quorum using partition of action failed: {}"
            .format(action.data))

        # Unblock all traffic across mysql instances
        for unit in zaza.model.get_units(self.application):
            cmd = "sudo iptables -F"
            zaza.model.async_run_on_unit(unit, cmd)

        logging.info("Wait for application states ...")
        for unit in zaza.model.get_units(self.application):
            zaza.model.run_on_unit(unit.entity_id, "hooks/update-status")
        test_config = lifecycle_utils.get_charm_config(fatal=False)
        zaza.model.wait_for_application_states(
            states=test_config.get("target_deploy_status", {}))


class MySQL8MigrationTests(MySQLBaseTest):
    """Percona Cluster to MySQL InnoDB Cluster Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running migration tests."""
        # Having application_name set avoids breakage in the
        # OpenStackBaseTest class when running bundle tests without
        # charm_name specified
        super().setUpClass(application_name="mysql-innodb-cluster")

    def test_999_migrate_percona_to_mysql(self):
        """Migrate DBs from percona-cluster to mysql-innodb-cluster.

        Do not rely on self.application_name or other pre-set class values as
        we will be pointing to both percona-cluster and mysql-innodb-cluster.
        """
        # Map application name to db name
        apps_to_dbs = {
            "keystone": ["keystone"],
            "glance": ["glance"],
            "cinder": ["cinder"],
            "nova-cloud-controller": ["nova", "nova_api", "nova_cell0"],
            "neutron-api": ["neutron"],
            "openstack-dashboard": ["horizon"],
            "placement": ["placement"],
            "vault": ["vault"]}
        # TODO: This could do an automated check of what is actually deployed
        dbs = [db for mapped_dbs in apps_to_dbs.values() for db in mapped_dbs]
        percona_application = "percona-cluster"
        mysql_application = "mysql-innodb-cluster"
        percona_leader = zaza.model.get_unit_from_name(
            zaza.model.get_lead_unit_name(percona_application))
        mysql_leader = zaza.model.get_unit_from_name(
            zaza.model.get_lead_unit_name(mysql_application))
        logging.info("Remove percona-cluster:shared-db relations ...")
        for app in apps_to_dbs.keys():
            # Remove relations
            zaza.model.remove_relation(
                percona_application,
                "{}:shared-db".format(percona_application),
                "{}:shared-db".format(app))
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()
        # Set PXC Strict Mode to MASTER
        logging.info("Set PXC Strict Mode MASTER ...")
        action = zaza.model.run_action_on_leader(
            percona_application,
            "set-pxc-strict-mode",
            action_params={"mode": "MASTER"})
        assert "failed" not in action.data["status"], (
            "Set PXC Strict Mode MASTER action failed: {}"
            .format(action.data))
        # Dump the percona db
        logging.info("mysqldump percona-cluster DBs ...")
        action = zaza.model.run_action_on_leader(
            percona_application,
            "mysqldump",
            action_params={
                "databases": ",".join(dbs)})
        assert "failed" not in action.data["status"], (
            "mysqldump action failed: {}"
            .format(action.data))
        remote_file = action.data["results"]["mysqldump-file"]
        remote_backup_dir = "/var/backups/mysql"
        # Permissions for ubuntu user to read
        logging.info("Set permissions to read percona-cluster:{} ..."
                     .format(remote_backup_dir))
        zaza.model.run_on_leader(
            percona_application,
            "chmod 755 {}".format(remote_backup_dir))

        # SCP back and forth
        dump_file = "dump.sql.gz"
        logging.info("SCP percona-cluster:{} to mysql-innodb-cluster:{} ..."
                     .format(remote_file, dump_file))
        with tempfile.TemporaryDirectory() as tmpdirname:
            tmp_file = "{}/{}".format(tmpdirname, dump_file)
            zaza.model.scp_from_unit(
                percona_leader.name,
                remote_file,
                tmp_file)
            zaza.model.scp_to_unit(
                mysql_leader.name,
                tmp_file,
                dump_file)
        # Restore mysqldump to mysql-innodb-cluster
        logging.info("restore-mysqldump DBs onto mysql-innodb-cluster ...")
        action = zaza.model.run_action_on_leader(
            mysql_application,
            "restore-mysqldump",
            action_params={
                "dump-file": "/home/ubuntu/{}".format(dump_file)})
        assert "failed" not in action.data["status"], (
            "restore-mysqldump action failed: {}"
            .format(action.data))
        # Add db router relations
        logging.info("Add mysql-router:shared-db relations ...")
        for app in apps_to_dbs.keys():
            # add relations
            zaza.model.add_relation(
                mysql_application,
                "{}:shared-db".format(app),
                "{}-mysql-router:shared-db".format(app))
        # Set PXC Strict Mode back to ENFORCING
        logging.info("Set PXC Strict Mode ENFORCING ...")
        action = zaza.model.run_action_on_leader(
            percona_application,
            "set-pxc-strict-mode",
            action_params={"mode": "ENFORCING"})
        assert "failed" not in action.data["status"], (
            "Set PXC Strict Mode ENFORCING action failed: {}"
            .format(action.data))
        logging.info("Wait for application states ...")
        test_config = lifecycle_utils.get_charm_config(fatal=False)
        zaza.model.wait_for_application_states(
            states=test_config.get("target_deploy_status", {}))


class MySQLInnoDBClusterScaleTest(MySQLBaseTest):
    """Percona Cluster cold start tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running mysql-innodb-cluster scale tests."""
        super().setUpClass()
        cls.application = "mysql-innodb-cluster"
        cls.test_config = lifecycle_utils.get_charm_config(fatal=False)
        cls.states = cls.test_config.get("target_deploy_status", {})

    def test_800_remove_leader(self):
        """Remove leader node.

        We start with a three node cluster, remove one, down to two.
        The cluster will be in waiting state.
        """
        logging.info("Scale in test: remove leader")
        leader, nons = self.get_leaders_and_non_leaders()
        leader_unit = zaza.model.get_unit_from_name(leader)

        # Wait until we are idle in the hopes clients are not running
        # update-status hooks
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()
        zaza.model.destroy_unit(self.application_name, leader)

        logging.info("Wait until all only 2 units ...")
        zaza.model.block_until_unit_count(self.application, 2)

        logging.info("Wait until all units are cluster incomplete ...")
        zaza.model.block_until_wl_status_info_starts_with(
            self.application, "'cluster' incomplete")

        # Show status
        logging.info(self.get_cluster_status())

        logging.info(
            "Removing old unit from cluster: {} "
            .format(leader_unit.public_address))
        action = zaza.model.run_action(
            nons[0],
            "remove-instance",
            action_params={
                "address": leader_unit.public_address,
                "force": True})
        assert action.data.get("results") is not None, (
            "Remove instance action failed: No results: {}"
            .format(action.data))

    def test_801_add_unit(self):
        """Add mysql-innodb-cluster node.

        We start with two node cluster in waiting, add one, back to a full
        cluster of three.
        """
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()

        logging.info("Adding unit after removed unit ...")
        zaza.model.add_unit(self.application_name)

        logging.info("Wait until 3 units ...")
        zaza.model.block_until_unit_count(self.application, 3)

        logging.info("Wait for application states ...")
        zaza.model.wait_for_application_states(states=self.states)

    def test_802_add_unit(self):
        """Add another mysql-innodb-cluster node.

        We start with a three node full cluster, add another, up to a four node
        cluster.
        """
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()

        logging.info("Adding unit after full cluster ...")
        zaza.model.add_unit(self.application_name)

        logging.info("Wait until 4 units ...")
        zaza.model.block_until_unit_count(self.application, 4)

        logging.info("Wait for application states ...")
        zaza.model.wait_for_application_states(states=self.states)

    def test_803_remove_fourth(self):
        """Remove mysql-innodb-cluster node.

        We start with a four node full cluster, remove one, down to a three
        node full cluster.
        """
        leader, nons = self.get_leaders_and_non_leaders()
        non_leader_unit = zaza.model.get_unit_from_name(nons[0])

        # Wait until we are idle in the hopes clients are not running
        # update-status hooks
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()

        zaza.model.destroy_unit(self.application_name, nons[0])

        logging.info("Scale in test: back down to three")
        logging.info("Wait until 3 units ...")
        zaza.model.block_until_unit_count(self.application, 3)

        logging.info("Wait for status ready ...")
        zaza.model.wait_for_application_states(states=self.states)

        # Show status
        logging.info(self.get_cluster_status())

        logging.info(
            "Removing old unit from cluster: {} "
            .format(non_leader_unit.public_address))
        action = zaza.model.run_action(
            leader,
            "remove-instance",
            action_params={
                "address": non_leader_unit.public_address,
                "force": True})
        assert action.data.get("results") is not None, (
            "Remove instance action failed: No results: {}"
            .format(action.data))


class MySQLRouterTests(test_utils.OpenStackBaseTest):
    """MySQL Router Tests."""

    @classmethod
    def setUpClass(cls, application_name="keystone-mysql-router"):
        """Run class setup for running mysql-router tests."""
        super().setUpClass(application_name=application_name)
        cls.application = application_name
        cls.services = ["mysqlrouter"]
        # Config file affected by juju set config change
        cls.conf_file = (
            "/var/lib/mysql/{}-mysql-router/mysqlrouter.conf"
            .format(application_name))

    def test_910_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change max connections and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        set_default = {"ttl": ".5"}
        set_alternate = {"ttl": "7"}

        # Make config change, check for service restarts
        logging.info("Setting TTL ...")
        self.restart_on_changed(
            self.conf_file,
            set_default,
            set_alternate,
            {}, {},
            self.services)
        logging.info("Passed restart on changed test.")
