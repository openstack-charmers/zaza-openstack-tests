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

"""Encapsulating `neutron-openvswitch` testing."""


import logging
import unittest

import zaza
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.nova.utils as nova_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.configure.guest as guest
import zaza.openstack.utilities.openstack as openstack_utils


class NeutronApiTest(test_utils.OpenStackBaseTest):
    """Test basic Neutron API Charm functionality."""

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change disk format and assert then change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        current_value = zaza.model.get_application_config(
            'neutron-api')['debug']['value']
        new_value = str(not bool(current_value)).title()
        current_value = str(current_value).title()

        set_default = {'debug': current_value}
        set_alternate = {'debug': new_value}
        default_entry = {'DEFAULT': {'debug': [current_value]}}
        alternate_entry = {'DEFAULT': {'debug': [new_value]}}

        # Config file affected by juju set config change
        conf_file = '/etc/neutron/neutron.conf'

        # Make config change, check for service restarts
        logging.info(
            'Setting verbose on neutron-api {}'.format(set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            ['neutron-server'])

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(["neutron-server", "apache2", "haproxy"]):
            logging.info("Testing pause resume")


class SecurityTest(test_utils.OpenStackBaseTest):
    """Neutron APIsecurity tests tests."""

    def test_security_checklist(self):
        """Verify expected state with security-checklist."""
        # Changes fixing the below expected failures will be made following
        # this initial work to get validation in. There will be bugs targeted
        # to each one and resolved independently where possible.

        expected_failures = [
            'validate-enables-tls',
            'validate-uses-tls-for-keystone',
        ]
        expected_passes = [
            'validate-file-ownership',
            'validate-file-permissions',
            'validate-uses-keystone',
        ]

        for unit in zaza.model.get_units('neutron-api',
                                         model_name=self.model_name):
            logging.info('Running `security-checklist` action'
                         ' on  unit {}'.format(unit.entity_id))
            test_utils.audit_assertions(
                zaza.model.run_action(
                    unit.entity_id,
                    'security-checklist',
                    model_name=self.model_name,
                    action_params={}),
                expected_passes,
                expected_failures,
                expected_to_pass=False)


class NeutronNetworkingTest(unittest.TestCase):
    """Ensure that openstack instances have valid networking."""

    RESOURCE_PREFIX = 'zaza-neutrontests'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Neutron API Networking tests."""
        cls.keystone_session = (
            openstack_utils.get_overcloud_keystone_session())
        cls.nova_client = (
            openstack_utils.get_nova_session_client(cls.keystone_session))

    @classmethod
    def tearDown(cls):
        """Remove test resources."""
        logging.info('Running teardown')
        for server in cls.nova_client.servers.list():
            if server.name.startswith(cls.RESOURCE_PREFIX):
                openstack_utils.delete_resource(
                    cls.nova_client.servers,
                    server.id,
                    msg="server")

    def test_instances_have_networking(self):
        """Validate North/South and East/West networking."""
        guest.launch_instance(
            glance_setup.LTS_IMAGE_NAME,
            vm_name='{}-ins-1'.format(self.RESOURCE_PREFIX))
        guest.launch_instance(
            glance_setup.LTS_IMAGE_NAME,
            vm_name='{}-ins-2'.format(self.RESOURCE_PREFIX))

        instance_1 = self.nova_client.servers.find(
            name='{}-ins-1'.format(self.RESOURCE_PREFIX))

        instance_2 = self.nova_client.servers.find(
            name='{}-ins-2'.format(self.RESOURCE_PREFIX))

        def verify(stdin, stdout, stderr):
            """Validate that the SSH command exited 0."""
            self.assertEqual(stdout.channel.recv_exit_status(), 0)

        # Verify network from 1 to 2
        self.validate_instance_can_reach_other(instance_1, instance_2, verify)

        # Verify network from 2 to 1
        self.validate_instance_can_reach_other(instance_2, instance_1, verify)

        # Validate tenant to external network routing
        self.validate_instance_can_reach_router(instance_1, verify)
        self.validate_instance_can_reach_router(instance_2, verify)

    def validate_instance_can_reach_other(self,
                                          instance_1,
                                          instance_2,
                                          verify):
        """
        Validate that an instance can reach a fixed and floating of another.

        :param instance_1: The instance to check networking from
        :type instance_1: nova_client.Server

        :param instance_2: The instance to check networking from
        :type instance_2: nova_client.Server
        """
        floating_1 = floating_ips_from_instance(instance_1)[0]
        floating_2 = floating_ips_from_instance(instance_2)[0]
        address_2 = fixed_ips_from_instance(instance_2)[0]

        username = guest.boot_tests['bionic']['username']
        password = guest.boot_tests['bionic'].get('password')
        privkey = openstack_utils.get_private_key(nova_utils.KEYPAIR_NAME)

        openstack_utils.ssh_command(
            username, floating_1, 'instance-1',
            'ping -c 1 {}'.format(address_2),
            password=password, privkey=privkey, verify=verify)

        openstack_utils.ssh_command(
            username, floating_1, 'instance-1',
            'ping -c 1 {}'.format(floating_2),
            password=password, privkey=privkey, verify=verify)

    def validate_instance_can_reach_router(self, instance, verify):
        """
        Validate that an instance can reach it's primary gateway.

        We make the assumption that the router's IP is 192.168.0.1
        as that's the network that is setup in
        neutron.setup.basic_overcloud_network which is used in all
        Zaza Neutron validations.

        :param instance: The instance to check networking from
        :type instance: nova_client.Server
        """
        address = floating_ips_from_instance(instance)[0]

        username = guest.boot_tests['bionic']['username']
        password = guest.boot_tests['bionic'].get('password')
        privkey = openstack_utils.get_private_key(nova_utils.KEYPAIR_NAME)

        openstack_utils.ssh_command(
            username, address, 'instance', 'ping -c 1 192.168.0.1',
            password=password, privkey=privkey, verify=verify)
        pass


def floating_ips_from_instance(instance):
    """
    Retrieve floating IPs from an instance.

    :param instance: The instance to fetch floating IPs from
    :type instance: nova_client.Server

    :returns: A list of floating IPs for the specified server
    :rtype: list[str]
    """
    return ips_from_instance(instance, 'floating')


def fixed_ips_from_instance(instance):
    """
    Retrieve fixed IPs from an instance.

    :param instance: The instance to fetch fixed IPs from
    :type instance: nova_client.Server

    :returns: A list of fixed IPs for the specified server
    :rtype: list[str]
    """
    return ips_from_instance(instance, 'fixed')


def ips_from_instance(instance, ip_type):
    """
    Retrieve IPs of a certain type from an instance.

    :param instance: The instance to fetch IPs from
    :type instance: nova_client.Server
    :param ip_type: the type of IP to fetch, floating or fixed
    :type ip_type: str

    :returns: A list of IPs for the specified server
    :rtype: list[str]
    """
    if ip_type not in ['floating', 'fixed']:
        raise RuntimeError(
            "Only 'floating' and 'fixed' are valid IP types to search for"
        )
    return list([
        ip['addr'] for ip in instance.addresses['private']
        if ip['OS-EXT-IPS:type'] == ip_type])
