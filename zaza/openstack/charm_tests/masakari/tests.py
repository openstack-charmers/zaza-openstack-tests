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

"""Encapsulate masakari testing."""

from datetime import datetime
import logging
import unittest
import tenacity

import novaclient

import zaza.model
import zaza.openstack.charm_tests.tempest.tests as tempest_tests
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.juju as juju_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.configure.guest
import zaza.openstack.configure.hacluster
import zaza.openstack.configure.masakari


class MasakariTest(test_utils.OpenStackBaseTest):
    """Encapsulate Masakari tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(MasakariTest, cls).setUpClass(application_name="masakari")
        cls.current_release = openstack_utils.get_os_release()
        cls.keystone_session = openstack_utils.get_overcloud_keystone_session()
        cls.model_name = zaza.model.get_juju_model()
        cls.nova_client = openstack_utils.get_nova_session_client(
            cls.keystone_session)

    @classmethod
    def tearDown(cls):
        """Bring hypervisors and services back up."""
        logging.info('Running teardown')
        for unit in zaza.model.get_units('nova-compute',
                                         model_name=cls.model_name):
            zaza.openstack.configure.masakari.simulate_compute_host_recovery(
                unit.entity_id,
                model_name=cls.model_name)
        openstack_utils.enable_all_nova_services(cls.nova_client)
        zaza.openstack.configure.masakari.enable_hosts()

    def ensure_guest(self, vm_name):
        """Return the existing guest or boot a new one.

        :param vm_name: Name of guest to lookup
        :type vm_name: str
        :returns: Guest matching name.
        :rtype: novaclient.v2.servers.Server
        """
        try:
            guest = self.nova_client.servers.find(name=vm_name)
            logging.info('Found existing guest')
        except novaclient.exceptions.NotFound:
            logging.info('Launching new guest')
            guest = zaza.openstack.configure.guest.launch_instance(
                'jammy',
                use_boot_volume=True,
                meta={'HA_Enabled': 'True'},
                vm_name=vm_name)
        return guest

    def get_guests_compute_info(self, vm_name):
        """Return the hostname & juju unit of compute host hosting vm.

        :param vm_name: Name of guest to lookup
        :type vm_name: str
        :returns: Hypervisor name and juju unit name
        :rtype: (str, str)
        """
        current_hypervisor = openstack_utils.get_hypervisor_for_guest(
            self.nova_client,
            vm_name)
        unit_name = juju_utils.get_unit_name_from_host_name(
            current_hypervisor,
            'nova-compute')
        return current_hypervisor, unit_name

    def get_guest_qemu_pid(self, compute_unit_name, vm_uuid, model_name=None):
        """Return the qemu pid of process running guest.

        :param compute_unit_name: Juju unit name of hypervisor running guest
        :type compute_unit_name: str
        :param vm_uuid: Guests UUID
        :type vm_uuid: str
        :param model_name: Name of model running cloud.
        :type model_name: str
        :returns: PID of qemu process
        :rtype: int
        :raises: ValueError
        """
        pid_find_cmd = 'pgrep -u libvirt-qemu -f {}'.format(vm_uuid)
        out = zaza.model.run_on_unit(
            compute_unit_name,
            pid_find_cmd,
            model_name=self.model_name)
        return int(out['Stdout'].strip())

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=2, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(5),
                    retry=tenacity.retry_if_exception_type(ValueError))
    def wait_for_guest_pid(self, compute_unit_name, vm_uuid, model_name=None):
        """Wait for the qemu process running guest to appear & return its pid.

        :param compute_unit_name: Juju unit name of hypervisor running guest
        :type compute_unit_name: str
        :param vm_uuid: Guests UUID
        :type vm_uuid: str
        :param model_name: Name of model running cloud.
        :type model_name: str
        :returns: PID of qemu process
        :rtype: int
        :raises: ValueError
        """
        return self.get_guest_qemu_pid(
            compute_unit_name,
            vm_uuid,
            model_name=self.model_name)

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=2, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(5),
                    retry=tenacity.retry_if_exception_type(AssertionError))
    def wait_for_guest_ready(self, vm_name):
        """Wait for the guest to be ready.

        :param vm_name: Name of guest to check.
        :type vm_name: str
        """
        guest_ready_attr_checks = [
            ('OS-EXT-STS:task_state', None),
            ('status', 'ACTIVE'),
            ('OS-EXT-STS:power_state', 1),
            ('OS-EXT-STS:vm_state', 'active')]
        guest = self.nova_client.servers.find(name=vm_name)
        logging.info('Checking guest {} attributes'.format(vm_name))
        for (attr, required_state) in guest_ready_attr_checks:
            logging.info('Checking {} is {}'.format(attr, required_state))
            assert getattr(guest, attr) == required_state

    def test_instance_failover(self):
        """Test masakari managed guest migration."""
        # Workaround for Bug #1874719
        zaza.openstack.configure.hacluster.remove_node(
            'masakari',
            'node1')
        # Launch guest
        self.assertTrue(
            zaza.openstack.configure.hacluster.check_all_nodes_online(
                'masakari'))
        vm_name = 'zaza-test-instance-failover'
        self.ensure_guest(vm_name)

        # Locate hypervisor hosting guest and shut it down
        current_hypervisor, unit_name = self.get_guests_compute_info(vm_name)
        zaza.openstack.configure.masakari.simulate_compute_host_failure(
            unit_name,
            model_name=self.model_name)

        # Wait for instance move
        logging.info('Waiting for guest to move away from {}'.format(
            current_hypervisor))
        # wait_for_server_migration will throw an exception if migration fails
        openstack_utils.wait_for_server_migration(
            self.nova_client,
            vm_name,
            current_hypervisor)

        # Bring things back
        zaza.openstack.configure.masakari.simulate_compute_host_recovery(
            unit_name,
            model_name=self.model_name)
        openstack_utils.enable_all_nova_services(self.nova_client)
        zaza.openstack.configure.masakari.enable_hosts()
        self.wait_for_guest_ready(vm_name)

    def test_instance_restart_on_fail(self):
        """Test single guest crash and recovery."""
        if self.current_release < openstack_utils.get_os_release(
                'bionic_ussuri'):
            raise unittest.SkipTest(
                "Not supported on {}. Bug #1866638".format(
                    self.current_release))
        vm_name = 'zaza-test-instance-failover'
        vm = self.ensure_guest(vm_name)
        self.wait_for_guest_ready(vm_name)
        _, unit_name = self.get_guests_compute_info(vm_name)
        logging.info('{} is running on {}'.format(vm_name, unit_name))
        guest_pid = self.get_guest_qemu_pid(
            unit_name,
            vm.id,
            model_name=self.model_name)
        logging.info('{} pid is {}'.format(vm_name, guest_pid))
        inital_update_time = datetime.strptime(
            vm.updated,
            "%Y-%m-%dT%H:%M:%SZ")
        logging.info('Simulating vm crash of {}'.format(vm_name))
        zaza.openstack.configure.masakari.simulate_guest_crash(
            guest_pid,
            unit_name,
            model_name=self.model_name)
        logging.info('Waiting for {} to be updated and become active'.format(
            vm_name))
        openstack_utils.wait_for_server_update_and_active(
            self.nova_client,
            vm_name,
            inital_update_time)
        new_guest_pid = self.wait_for_guest_pid(
            unit_name,
            vm.id,
            model_name=self.model_name)
        logging.info('{} pid is now {}'.format(vm_name, new_guest_pid))
        assert new_guest_pid and new_guest_pid != guest_pid, (
            "Restart failed or never happened")


class MasakariTempestTestK8S(tempest_tests.TempestTestScaleK8SBase):
    """Test masakari-k8s scale out and scale back."""

    application_name = "masakari"
