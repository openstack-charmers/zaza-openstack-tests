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

"""Encapsulate nova testing."""

import logging
import unittest

import zaza.model
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.configure.guest
import zaza.openstack.utilities.openstack as openstack_utils


class BaseGuestCreateTest(unittest.TestCase):
    """Deprecated: Use zaza.openstack.configure.guest.launch_instance."""

    def launch_instance(self, instance_key):
        """Deprecated: Use zaza.openstack.configure.guest.launch_instance."""
        logging.info('BaseGuestCreateTest.launch_instance is deprecated '
                     'please use '
                     'zaza.openstack.configure.guest.launch_instance')
        zaza.openstack.configure.guest.launch_instance(instance_key)


class CirrosGuestCreateTest(BaseGuestCreateTest):
    """Tests to launch a cirros image."""

    def test_launch_small_instance(self):
        """Launch a cirros instance and test connectivity."""
        zaza.openstack.configure.guest.launch_instance(
            glance_setup.CIRROS_IMAGE_NAME)


class LTSGuestCreateTest(BaseGuestCreateTest):
    """Tests to launch a LTS image."""

    def test_launch_small_instance(self):
        """Launch a Bionic instance and test connectivity."""
        zaza.openstack.configure.guest.launch_instance(
            glance_setup.LTS_IMAGE_NAME)


class NovaCompute(test_utils.OpenStackBaseTest):
    """Run nova-compute specific tests."""

    def test_500_hugepagereport_action(self):
        """Test hugepagereport action."""
        for unit in zaza.model.get_units('nova-compute',
                                         model_name=self.model_name):
            logging.info('Running `hugepagereport` action'
                         ' on  unit {}'.format(unit.entity_id))
            action = zaza.model.run_action(
                unit.entity_id,
                'hugepagereport',
                model_name=self.model_name,
                action_params={})
            if "failed" in action.data["status"]:
                raise Exception(
                    "The action failed: {}".format(action.data["message"]))

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        current_value = zaza.model.get_application_config(
            'nova-compute')['debug']['value']
        new_value = str(not bool(current_value)).title()
        current_value = str(current_value).title()

        set_default = {'debug': current_value}
        set_alternate = {'debug': new_value}
        default_entry = {'DEFAULT': {'debug': [current_value]}}
        alternate_entry = {'DEFAULT': {'debug': [new_value]}}

        # Config file affected by juju set config change
        conf_file = '/etc/nova/nova.conf'

        # Make config change, check for service restarts
        logging.info(
            'Setting verbose on nova-compute {}'.format(set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            ['nova-compute'])

    def test_920_change_aa_profile(self):
        """Test changing the Apparmor profile mode."""
        services = ['nova-compute']

        set_default = {'aa-profile-mode': 'enforce'}
        set_alternate = {'aa-profile-mode': 'complain'}

        mtime = zaza.model.get_unit_time(
            self.lead_unit,
            model_name=self.model_name)
        logging.debug('Remote unit timestamp {}'.format(mtime))

        with self.config_change(set_default, set_alternate):
            logging.info(
                'Waiting for services ({}) to be restarted'.format(services))
            zaza.model.block_until_services_restarted(
                'nova-compute',
                mtime,
                services,
                model_name=self.model_name)
            for unit in zaza.model.get_units('nova-compute',
                                             model_name=self.model_name):
                logging.info('Checking number of profiles in complain '
                             'mode in {}'.format(unit.entity_id))
                run = zaza.model.run_on_unit(
                    unit.entity_id,
                    'aa-status --complaining',
                    model_name=self.model_name)
                output = run['Stdout']
                self.assertTrue(int(output) >= len(services))

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(['nova-compute']):
            logging.info("Testing pause resume")

    def test_930_check_virsh_default_network(self):
        """Test default virt network is not present."""
        for unit in zaza.model.get_units('nova-compute',
                                         model_name=self.model_name):
            logging.info('Checking default network is absent on '
                         'unit {}'.format(unit.entity_id))
            run = zaza.model.run_on_unit(
                unit.entity_id,
                'virsh net-dumpxml default',
                model_name=self.model_name)
            self.assertFalse(int(run['Code']) == 0)


class NovaCloudController(test_utils.OpenStackBaseTest):
    """Run nova-cloud-controller specific tests."""

    XENIAL_MITAKA = openstack_utils.get_os_release('xenial_mitaka')
    XENIAL_NEWTON = openstack_utils.get_os_release('xenial_newton')
    XENIAL_OCATA = openstack_utils.get_os_release('xenial_ocata')
    BIONIC_QUEENS = openstack_utils.get_os_release('bionic_queens')

    @classmethod
    def setUpClass(cls):
        """Run class setup for running nova-cloud-controller tests."""
        super(NovaCloudController, cls).setUpClass()
        cls.current_release = openstack_utils.get_os_release()

    @property
    def services(self):
        """Return a list of services for the selected OpenStack release."""
        services = ['nova-scheduler', 'nova-conductor']
        if self.current_release <= self.BIONIC_QUEENS:
            services.append('nova-api-os-compute')
        if self.current_release <= self.XENIAL_MITAKA:
            services.append('nova-cert')
        if self.current_release >= self.XENIAL_OCATA:
            services.append('apache2')
        return services

    def test_104_compute_api_functionality(self):
        """Verify basic compute API functionality."""
        logging.info('Instantiating nova client...')
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        nova = openstack_utils.get_nova_session_client(keystone_session)

        logging.info('Checking api functionality...')

        actual_service_names = [service.to_dict()['binary'] for service in
                                nova.services.list()]
        for expected_service_name in ('nova-scheduler', 'nova-conductor',
                                      'nova-compute'):
            assert(expected_service_name in actual_service_names)

        # Thanks to setup.create_flavors we should have a few flavors already:
        assert(len(nova.flavors.list()) > 0)

        # Just checking it's not raising and returning an iterable:
        assert(len(nova.servers.list()) >= 0)

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        current_value = zaza.model.get_application_config(
            'nova-cloud-controller')['debug']['value']
        new_value = str(not bool(current_value)).title()
        current_value = str(current_value).title()

        set_default = {'debug': current_value}
        set_alternate = {'debug': new_value}
        default_entry = {'DEFAULT': {'debug': [current_value]}}
        alternate_entry = {'DEFAULT': {'debug': [new_value]}}

        # Config file affected by juju set config change
        conf_file = '/etc/nova/nova.conf'

        # Make config change, check for service restarts
        logging.info(
            'Setting verbose on nova-cloud-controller {}'.format(
                set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            self.services)

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(self.services):
            logging.info("Testing pause resume")


class SecurityTests(test_utils.OpenStackBaseTest):
    """nova-compute and nova-cloud-controller security tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Nova SecurityTests."""
        super(SecurityTests, cls).setUpClass()

    def test_security_checklist(self):
        """Verify expected state with security-checklist."""
        # Changes fixing the below expected failures will be made following
        # this initial work to get validation in. There will be bugs targeted
        # to each one and resolved independently where possible.

        expected_failures = [
            'is-volume-encryption-enabled',
            'validate-uses-tls-for-glance',
            'validate-uses-tls-for-keystone',
        ]
        expected_passes = [
            'validate-file-ownership',
            'validate-file-permissions',
            'validate-uses-keystone',
        ]

        for unit in zaza.model.get_units(self.application_name,
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
