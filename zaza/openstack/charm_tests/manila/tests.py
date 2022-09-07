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

"""Encapsulate Manila testing."""

import logging
import tenacity

from manilaclient import client as manilaclient

import zaza.model
import zaza.openstack.configure.guest as guest
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.charm_tests.nova.utils as nova_utils
import zaza.openstack.charm_tests.neutron.tests as neutron_tests


def verify_status(stdin, stdout, stderr):
    """Callable to verify the command output.

    It checks if the command successfully executed.

    This is meant to be given as parameter 'verify' to the helper function
    'openstack_utils.ssh_command'.
    """
    status = stdout.channel.recv_exit_status()
    if status:
        logging.info("{}".format(stderr.readlines()[0].strip()))
    assert status == 0


def verify_manila_testing_file(stdin, stdout, stderr):
    """Callable to verify the command output.

    It checks if the command successfully executed, and it validates the
    testing file written on the Manila share.

    This is meant to be given as parameter 'verify' to the helper function
    'openstack_utils.ssh_command'.
    """
    verify_status(stdin, stdout, stderr)
    out = ""
    for line in iter(stdout.readline, ""):
        out += line
    assert out == "test\n"


class ManilaTests(test_utils.OpenStackBaseTest):
    """Encapsulate Manila  tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(ManilaTests, cls).setUpClass()
        cls.manila_client = manilaclient.Client(
            session=cls.keystone_session, client_version='2')

    def test_manila_api(self):
        """Test that the Manila API is working."""
        # The manila charm contains a 'band-aid' for Bug #1706699 which relies
        # on update-status to bring up services if needed. When the tests run
        # an update-status hook might not have run so services may still be
        # stopped so force a hook execution.
        for unit in zaza.model.get_units('manila'):
            zaza.model.run_on_unit(unit.entity_id, "hooks/update-status")
        self.assertEqual([], self._list_shares())

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=3, min=2, max=10))
    def _list_shares(self):
        return self.manila_client.shares.list()

    def test_902_nrpe_service_checks(self):
        """Confirm that the NRPE service check files are created."""
        units = zaza.model.get_units('manila')
        services = ['apache2', 'haproxy', 'manila-scheduler', 'manila-data']

        # Remove check_haproxy if hacluster is present in the bundle
        # See LP Bug#1880601 for details
        try:
            if zaza.model.get_units('hacluster'):
                services.remove("haproxy")
        except KeyError:
            pass

        cmds = []
        for check_name in services:
            cmds.append(
                'egrep -oh /usr/local.* /etc/nagios/nrpe.d/'
                'check_{}.cfg'.format(check_name)
            )

        for attempt in tenacity.Retrying(
            wait=tenacity.wait_fixed(20),
            stop=tenacity.stop_after_attempt(2),
            reraise=True
        ):
            with attempt:
                ret = generic_utils.check_commands_on_units(cmds, units)
                self.assertIsNone(ret, msg=ret)


class ManilaBaseTest(test_utils.OpenStackBaseTest):
    """Encapsulate a Manila basic functionality test."""

    RESOURCE_PREFIX = 'zaza-manilatests'
    INSTANCE_KEY = 'jammy'
    INSTANCE_USERDATA = """#cloud-config
packages:
- nfs-common
"""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(ManilaBaseTest, cls).setUpClass()
        cls.nova_client = openstack_utils.get_nova_session_client(
            session=cls.keystone_session)
        cls.manila_client = manilaclient.Client(
            session=cls.keystone_session, client_version='2')
        cls.share_name = 'test-manila-share'
        cls.share_type_name = 'default_share_type'
        cls.share_protocol = 'nfs'
        cls.mount_dir = '/mnt/manila_share'
        cls.share_network = None

    @classmethod
    def tearDownClass(cls):
        """Run class teardown after tests finished."""
        # Cleanup Nova servers
        logging.info('Cleaning up test Nova servers')
        fips_reservations = []
        for vm in cls.nova_client.servers.list():
            fips_reservations += neutron_tests.floating_ips_from_instance(vm)
            vm.delete()
            openstack_utils.resource_removed(
                cls.nova_client.servers,
                vm.id,
                msg="Waiting for the Nova VM {} to be deleted".format(vm.name))

        # Delete FiPs reservations
        logging.info('Cleaning up test FiPs reservations')
        neutron = openstack_utils.get_neutron_session_client(
            session=cls.keystone_session)
        for fip in neutron.list_floatingips()['floatingips']:
            if fip['floating_ip_address'] in fips_reservations:
                neutron.delete_floatingip(fip['id'])

        # Cleanup Manila shares
        logging.info('Cleaning up test shares')
        for share in cls.manila_client.shares.list():
            share.delete()
            openstack_utils.resource_removed(
                cls.manila_client.shares,
                share.id,
                msg="Waiting for the Manila share {} to be deleted".format(
                    share.name))

        # Cleanup test Manila share servers (spawned by the driver when DHSS
        # is enabled).
        logging.info('Cleaning up test shares servers (if found)')
        for server in cls.manila_client.share_servers.list():
            server.delete()
            openstack_utils.resource_removed(
                cls.manila_client.share_servers,
                server.id,
                msg="Waiting for the share server {} to be deleted".format(
                    server.id))

    def _get_mount_options(self):
        """Get the appropriate mount options used to mount the Manila share.

        :returns: The proper mount options flags for the share protocol.
        :rtype: string
        """
        if self.share_protocol == 'nfs':
            return 'nfsvers=4.1,proto=tcp'
        else:
            raise NotImplementedError(
                'Share protocol not supported yet: {}'.format(
                    self.share_protocol))

    def _mount_share_on_instance(self, instance_ip, ssh_user_name,
                                 ssh_private_key, share_path):
        """Mount a share into a Nova instance.

        The mount command is executed via SSH.

        :param instance_ip: IP of the Nova instance.
        :type instance_ip: string
        :param ssh_user_name: SSH user name.
        :type ssh_user_name: string
        :param ssh_private_key: SSH private key.
        :type ssh_private_key: string
        :param share_path: Share network path.
        :type share_path: string
        """
        ssh_cmd = (
            'sudo mkdir -p {0} && '
            'sudo mount -t {1} -o {2} {3} {0}'.format(
                self.mount_dir,
                self.share_protocol,
                self._get_mount_options(),
                share_path))

        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_attempt(5),
                wait=tenacity.wait_exponential(multiplier=3, min=2, max=10)):
            with attempt:
                openstack_utils.ssh_command(
                    vm_name="instance-{}".format(instance_ip),
                    ip=instance_ip,
                    username=ssh_user_name,
                    privkey=ssh_private_key,
                    command=ssh_cmd,
                    verify=verify_status)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=3, min=2, max=10))
    def _write_testing_file_on_instance(self, instance_ip, ssh_user_name,
                                        ssh_private_key):
        """Write a file on a Manila share mounted into a Nova instance.

        Write a testing file into the already mounted Manila share from the
        given Nova instance (which is meant to be validated from another
        instance). These commands are executed via SSH.

        :param instance_ip: IP of the Nova instance.
        :type instance_ip: string
        :param ssh_user_name: SSH user name.
        :type ssh_user_name: string
        :param ssh_private_key: SSH private key.
        :type ssh_private_key: string
        """
        openstack_utils.ssh_command(
            vm_name="instance-{}".format(instance_ip),
            ip=instance_ip,
            username=ssh_user_name,
            privkey=ssh_private_key,
            command='echo "test" | sudo tee {}/test'.format(
                self.mount_dir),
            verify=verify_status)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=3, min=2, max=10))
    def _clear_testing_file_on_instance(self, instance_ip, ssh_user_name,
                                        ssh_private_key):
        """Clear a file on a Manila share mounted into a Nova instance.

        Remove a testing file into the already mounted Manila share from the
        given Nova instance (which is meant to be validated from another
        instance). These commands are executed via SSH.

        :param instance_ip: IP of the Nova instance.
        :type instance_ip: string
        :param ssh_user_name: SSH user name.
        :type ssh_user_name: string
        :param ssh_private_key: SSH private key.
        :type ssh_private_key: string
        """
        openstack_utils.ssh_command(
            vm_name="instance-{}".format(instance_ip),
            ip=instance_ip,
            username=ssh_user_name,
            privkey=ssh_private_key,
            command='sudo rm {}/test'.format(
                self.mount_dir),
            verify=verify_status)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=3, min=2, max=10))
    def _validate_testing_file_from_instance(self, instance_ip, ssh_user_name,
                                             ssh_private_key):
        """Validate a file from the Manila share mounted into a Nova instance.

        This is meant to run after the testing file was already written into
        another Nova instance. It validates the written file. The commands are
        executed via SSH.

        :param instance_ip: IP of the Nova instance.
        :type instance_ip: string
        :param ssh_user_name: SSH user name.
        :type ssh_user_name: string
        :param ssh_private_key: SSH private key.
        :type ssh_private_key: string
        """
        openstack_utils.ssh_command(
            vm_name="instance-{}".format(instance_ip),
            ip=instance_ip,
            username=ssh_user_name,
            privkey=ssh_private_key,
            command='sudo cat {}/test'.format(self.mount_dir),
            verify=verify_manila_testing_file)

    def _restart_share_instance(self):
        """Restart the share service's provider.

        restart_share_instance is intended to be overridden with driver
        specific implementations that allow verrification that the share is
        still  accessible after the service is restarted.

        :returns bool: If the test should re-validate
        :rtype: bool
        """
        return False

    def test_manila_share(self):
        """Test that a Manila share can be accessed on two instances.

        1. Spawn two servers
        2. Create a share
        3. Mount it on both
        4. Write a file on one
        5. Read it on the other
        6. Profit
        """
        # Spawn Servers
        instance_1 = self.launch_guest(
            guest_name='ins-1',
            userdata=self.INSTANCE_USERDATA,
            instance_key=self.INSTANCE_KEY)
        instance_2 = self.launch_guest(
            guest_name='ins-2',
            userdata=self.INSTANCE_USERDATA,
            instance_key=self.INSTANCE_KEY)

        fip_1 = neutron_tests.floating_ips_from_instance(instance_1)[0]
        fip_2 = neutron_tests.floating_ips_from_instance(instance_2)[0]

        # Create a share
        share = self.manila_client.shares.create(
            share_type=self.share_type_name,
            name=self.share_name,
            share_proto=self.share_protocol,
            share_network=self.share_network,
            size=1)

        # Wait for the created share to become available before it gets used.
        openstack_utils.resource_reaches_status(
            self.manila_client.shares,
            share.id,
            wait_iteration_max_time=120,
            stop_after_attempt=2,
            expected_status="available",
            msg="Waiting for a share to become available")

        # Grant access to the Manila share for both Nova instances.
        share.allow(access_type='ip', access=fip_1, access_level='rw')
        share.allow(access_type='ip', access=fip_2, access_level='rw')

        ssh_user_name = guest.boot_tests[self.INSTANCE_KEY]['username']
        privkey = openstack_utils.get_private_key(nova_utils.KEYPAIR_NAME)
        share_path = share.export_locations[0]

        # Write a testing file on instance #1
        self._mount_share_on_instance(
            fip_1, ssh_user_name, privkey, share_path)
        self._write_testing_file_on_instance(
            fip_1, ssh_user_name, privkey)

        # Validate the testing file from instance #2
        self._mount_share_on_instance(
            fip_2, ssh_user_name, privkey, share_path)
        self._validate_testing_file_from_instance(
            fip_2, ssh_user_name, privkey)

        # Restart the share provider
        if self._restart_share_instance():
            logging.info("Verifying manila after restarting share instance")
            # Read the previous testing file from instance #1
            self._mount_share_on_instance(
                fip_1, ssh_user_name, privkey, share_path)
            self._validate_testing_file_from_instance(
                fip_1, ssh_user_name, privkey)
            #  Read the previous testing file from instance #1
            self._mount_share_on_instance(
                fip_2, ssh_user_name, privkey, share_path)
            # Reset the test!
            self._clear_testing_file_on_instance(
                fip_1, ssh_user_name, privkey
            )
            # Write a testing file on instance #1
            self._write_testing_file_on_instance(
                fip_1, ssh_user_name, privkey)
            # Validate the testing file from instance #2
            self._validate_testing_file_from_instance(
                fip_2, ssh_user_name, privkey)
