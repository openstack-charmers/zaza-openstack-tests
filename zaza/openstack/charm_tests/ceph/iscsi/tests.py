# Copyright 2020 Canonical Ltd.
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

"""Encapsulating `ceph-iscsi` testing."""

import logging
import tempfile

import zaza
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.generic as generic_utils


class CephISCSIGatewayTest(test_utils.BaseCharmTest):
    """Class for `ceph-iscsi` tests."""

    GW_IQN = "iqn.2003-03.com.canonical.iscsi-gw:iscsi-igw"
    DATA_POOL_NAME = 'zaza_rep_pool'
    EC_PROFILE_NAME = 'zaza_iscsi'
    EC_DATA_POOL = 'zaza_ec_data_pool'
    EC_METADATA_POOL = 'zaza_ec_metadata_pool'

    def get_client_initiatorname(self, unit):
        """Return the initiatorname for the given unit.

        :param unit_name: Name of unit to match
        :type unit: str
        :returns: Initiator name
        :rtype: str
        """
        generic_utils.assertRemoteRunOK(zaza.model.run_on_unit(
            unit,
            ('cp /etc/iscsi/initiatorname.iscsi /tmp; '
             'chmod 644 /tmp/initiatorname.iscsi')))
        with tempfile.TemporaryDirectory() as tmpdirname:
            tmp_file = '{}/{}'.format(tmpdirname, 'initiatorname.iscsi')
            zaza.model.scp_from_unit(
                unit,
                '/tmp/initiatorname.iscsi',
                tmp_file)
            with open(tmp_file, 'r') as stream:
                contents = stream.readlines()
        initiatorname = None
        for line in contents:
            if line.startswith('InitiatorName'):
                initiatorname = line.split('=')[1].rstrip()
        return initiatorname

    def get_base_ctxt(self):
        """Generate a context for running gwcli commands to create a target.

        :returns: Base gateway context
        :rtype: Dict
        """
        gw_units = zaza.model.get_units('ceph-iscsi')
        host_names = generic_utils.get_unit_hostnames(gw_units, fqdn=True)
        client_entity_ids = [
            u.entity_id for u in zaza.model.get_units('ubuntu')]
        ctxt = {
            'client_entity_ids': sorted(client_entity_ids),
            'gw_iqn': self.GW_IQN,
            'chap_creds': 'username={chap_username} password={chap_password}',
            'gwcli_gw_dir': '/iscsi-targets/{gw_iqn}/gateways',
            'gwcli_hosts_dir': '/iscsi-targets/{gw_iqn}/hosts',
            'gwcli_disk_dir': '/disks',
            'gwcli_client_dir': '{gwcli_hosts_dir}/{client_initiatorname}',
        }
        ctxt['gateway_units'] = [
            {
                'entity_id': u.entity_id,
                'ip': zaza.model.get_unit_public_address(u),
                'hostname': host_names[u.entity_id]}
            for u in zaza.model.get_units('ceph-iscsi')]
        ctxt['gw_ip'] = sorted([g['ip'] for g in ctxt['gateway_units']])[0]
        return ctxt

    def run_commands(self, unit_name, commands, ctxt):
        """Run commands on unit.

        Iterate over each command and apply the context to the command, then
        run the command on the supplied unit.

        :param unit_name: Name of unit to match
        :type unit: str
        :param commands: List of commands to run.
        :type commands: List[str]
        :param ctxt: Context to apply to each command.
        :type ctxt: Dict
        :raises: AssertionError
        """
        for _cmd in commands:
            cmd = _cmd.format(**ctxt)
            generic_utils.assertRemoteRunOK(zaza.model.run_on_unit(
                unit_name,
                cmd))

    def create_iscsi_target(self, ctxt):
        """Create target on gateway.

        :param ctxt: Base gateway context
        :type ctxt: Dict
        """
        generic_utils.assertActionRanOK(zaza.model.run_action_on_leader(
            'ceph-iscsi',
            'create-target',
            action_params={
                'gateway-units': ' '.join([g['entity_id']
                                           for g in ctxt['gateway_units']]),
                'iqn': self.GW_IQN,
                'rbd-pool-name': ctxt.get('pool_name', ''),
                'ec-rbd-metadata-pool': ctxt.get('ec_meta_pool_name', ''),
                'image-size': ctxt['img_size'],
                'image-name': ctxt['img_name'],
                'client-initiatorname': ctxt['client_initiatorname'],
                'client-username': ctxt['chap_username'],
                'client-password': ctxt['chap_password']
            }))

    def login_iscsi_target(self, ctxt):
        """Login to the iscsi target on client.

        :param ctxt: Base gateway context
        :type ctxt: Dict
        """
        logging.info("Logging in to iscsi target")
        base_op_cmd = ('iscsiadm --mode node --targetname {gw_iqn} '
                       '--op=update ').format(**ctxt)
        setup_cmds = [
            'iscsiadm -m discovery -t st -p {gw_ip}',
            base_op_cmd + '-n node.session.auth.authmethod -v CHAP',
            base_op_cmd + '-n node.session.auth.username -v {chap_username}',
            base_op_cmd + '-n node.session.auth.password -v {chap_password}',
            'iscsiadm --mode node --targetname {gw_iqn} --login']
        self.run_commands(ctxt['client_entity_id'], setup_cmds, ctxt)

    def logout_iscsi_targets(self, ctxt):
        """Logout of iscsi target on client.

        :param ctxt: Base gateway context
        :type ctxt: Dict
        """
        logging.info("Logging out of iscsi target")
        logout_cmds = [
            'iscsiadm --mode node --logoutall=all']
        self.run_commands(ctxt['client_entity_id'], logout_cmds, ctxt)

    def check_client_device(self, ctxt, init_client=True):
        """Wait for multipath device to appear on client and test access.

        :param ctxt: Base gateway context
        :type ctxt: Dict
        :param init_client: Initialise client if this is the first time it has
                            been used.
        :type init_client: bool
        """
        logging.info("Checking multipath device is present.")
        device_ctxt = {
            'bdevice': '/dev/dm-0',
            'mount_point': '/mnt/iscsi',
            'test_file': '/mnt/iscsi/test.data'}
        ls_bdevice_cmd = 'ls -l {bdevice}'
        mkfs_cmd = 'mke2fs {bdevice}'
        mkdir_cmd = 'mkdir {mount_point}'
        mount_cmd = 'mount {bdevice} {mount_point}'
        umount_cmd = 'umount {mount_point}'
        check_mounted_cmd = 'mountpoint {mount_point}'
        write_cmd = 'truncate -s 1M {test_file}'
        check_file = 'ls -l {test_file}'
        if init_client:
            commands = [
                mkfs_cmd,
                mkdir_cmd,
                mount_cmd,
                check_mounted_cmd,
                write_cmd,
                check_file,
                umount_cmd]
        else:
            commands = [
                mount_cmd,
                check_mounted_cmd,
                check_file,
                umount_cmd]

        async def check_device_present():
            run = await zaza.model.async_run_on_unit(
                ctxt['client_entity_id'],
                ls_bdevice_cmd.format(bdevice=device_ctxt['bdevice']))
            return device_ctxt['bdevice'] in run['stdout']

        logging.info("Checking {} is present on {}".format(
            device_ctxt['bdevice'],
            ctxt['client_entity_id']))
        zaza.model.block_until(check_device_present)
        logging.info("Checking mounting device and access")
        self.run_commands(ctxt['client_entity_id'], commands, device_ctxt)

    def create_data_pool(self):
        """Create data pool to back iscsi targets."""
        generic_utils.assertActionRanOK(zaza.model.run_action_on_leader(
            'ceph-mon',
            'create-pool',
            action_params={
                'name': self.DATA_POOL_NAME}))

    def create_ec_data_pool(self):
        """Create data pool to back iscsi targets."""
        generic_utils.assertActionRanOK(zaza.model.run_action_on_leader(
            'ceph-mon',
            'create-erasure-profile',
            action_params={
                'name': self.EC_PROFILE_NAME,
                'coding-chunks': 2,
                'data-chunks': 4,
                'plugin': 'jerasure'}))
        generic_utils.assertActionRanOK(zaza.model.run_action_on_leader(
            'ceph-mon',
            'create-pool',
            action_params={
                'name': self.EC_DATA_POOL,
                'pool-type': 'erasure-coded',
                'allow-ec-overwrites': True,
                'erasure-profile-name': self.EC_PROFILE_NAME}))
        generic_utils.assertActionRanOK(zaza.model.run_action_on_leader(
            'ceph-mon',
            'create-pool',
            action_params={
                'name': self.EC_METADATA_POOL}))

    def refresh_partitions(self, ctxt):
        """Refresh kernel partition tables in client."""
        self.run_commands(ctxt['client_entity_id'], ('partprobe', ), ctxt)

    def run_client_checks(self, test_ctxt):
        """Check access to mulipath device.

        Write a filesystem to device, mount it and write data. Then unmount
        and logout the iscsi target, finally reconnect and remount checking
        data is still present.

        :param test_ctxt: Test context.
        :type test_ctxt: Dict
        """
        self.create_iscsi_target(test_ctxt)
        self.login_iscsi_target(test_ctxt)
        self.refresh_partitions(test_ctxt)
        self.check_client_device(test_ctxt, init_client=True)
        self.logout_iscsi_targets(test_ctxt)
        self.login_iscsi_target(test_ctxt)
        self.refresh_partitions(test_ctxt)
        self.check_client_device(test_ctxt, init_client=False)

    def test_create_and_mount_volume(self):
        """Test creating a target and mounting it on a client."""
        self.create_data_pool()
        ctxt = self.get_base_ctxt()
        client_entity_id = ctxt['client_entity_ids'][0]
        ctxt.update({
            'client_entity_id': client_entity_id,
            'client_initiatorname': self.get_client_initiatorname(
                client_entity_id),
            'pool_name': self.DATA_POOL_NAME,
            'chap_username': 'myiscsiusername1',
            'chap_password': 'myiscsipassword1',
            'img_size': '1G',
            'img_name': 'disk_rep_1'})
        self.run_client_checks(ctxt)

    def test_create_and_mount_ec_backed_volume(self):
        """Test creating an EC backed target and mounting it on a client."""
        self.create_ec_data_pool()
        ctxt = self.get_base_ctxt()
        client_entity_id = ctxt['client_entity_ids'][1]
        ctxt.update({
            'client_entity_id': client_entity_id,
            'client_initiatorname': self.get_client_initiatorname(
                client_entity_id),
            'pool_name': self.EC_DATA_POOL,
            'ec_meta_pool_name': self.EC_METADATA_POOL,
            'chap_username': 'myiscsiusername2',
            'chap_password': 'myiscsipassword2',
            'img_size': '2G',
            'img_name': 'disk_ec_1'})
        self.run_client_checks(ctxt)

    def test_create_and_mount_volume_default_pool(self):
        """Test creating a target and mounting it on a client."""
        self.create_data_pool()
        ctxt = self.get_base_ctxt()
        client_entity_id = ctxt['client_entity_ids'][2]
        ctxt.update({
            'client_entity_id': client_entity_id,
            'client_initiatorname': self.get_client_initiatorname(
                client_entity_id),
            'chap_username': 'myiscsiusername3',
            'chap_password': 'myiscsipassword3',
            'img_size': '3G',
            'img_name': 'disk_default_1'})
        self.run_client_checks(ctxt)

    def test_pause_resume(self):
        """Test pausing and resuming a unit."""
        with self.pause_resume(
                ['rbd-target-api', 'rbd-target-gw'],
                pgrep_full=True):
            logging.info("Testing pause resume")
