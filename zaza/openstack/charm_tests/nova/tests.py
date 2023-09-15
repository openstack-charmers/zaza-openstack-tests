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

import json
import logging
import os
import tempfile
import tenacity
import unittest
import urllib
from configparser import ConfigParser
from time import sleep

import novaclient.exceptions

import zaza.model
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.neutron.tests as neutron_tests
import zaza.openstack.charm_tests.nova.utils as nova_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.configure.guest as guest
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.tempest.tests as tempest_tests
from zaza.utilities import juju as juju_utils


class BaseGuestCreateTest(unittest.TestCase):
    """Deprecated: Use zaza.openstack.configure.guest.launch_instance."""

    def launch_instance(self, instance_key):
        """Deprecated: Use zaza.openstack.configure.guest.launch_instance."""
        logging.info('BaseGuestCreateTest.launch_instance is deprecated '
                     'please use '
                     'zaza.openstack.configure.guest.launch_instance')
        guest.launch_instance(instance_key)


class CirrosGuestCreateTest(test_utils.OpenStackBaseTest):
    """Tests to launch a cirros image."""

    def test_launch_small_instance(self):
        """Launch a cirros instance and test connectivity."""
        self.RESOURCE_PREFIX = 'zaza-nova'
        self.launch_guest(
            'cirros', instance_key=glance_setup.CIRROS_IMAGE_NAME)

    def tearDown(self):
        """Cleanup of VM guests."""
        self.resource_cleanup()


class LTSGuestCreateTest(test_utils.OpenStackBaseTest):
    """Tests to launch a LTS image."""

    def test_launch_small_instance(self):
        """Launch a Bionic instance and test connectivity."""
        self.RESOURCE_PREFIX = 'zaza-nova'
        self.launch_guest(
            'ubuntu', instance_key=glance_setup.LTS_IMAGE_NAME)

    def tearDown(self):
        """Cleanup of VM guests."""
        self.resource_cleanup()


class LTSGuestCreateVolumeBackedTest(test_utils.OpenStackBaseTest):
    """Tests to launch a LTS image."""

    def test_launch_small_instance(self):
        """Launch a Bionic instance and test connectivity."""
        self.RESOURCE_PREFIX = 'zaza-nova'
        self.launch_guest(
            'volume-backed-ubuntu', instance_key=glance_setup.LTS_IMAGE_NAME,
            use_boot_volume=True)

    def tearDown(self):
        """Cleanup of VM guests."""
        self.resource_cleanup()


class VTPMGuestCreateTest(test_utils.OpenStackBaseTest):
    """Tests launching a guest with vTPM Support.

    These tests are only run for focal-wallaby and newer.
    Base version in Wallaby is 23.0.0.
    """

    def _check_tpm_device(self, instance, *devices):
        """Check that the instance has TPM devices available.

        :param instance: the instance to determine if TPM devices are available
        :type instance: nova_client.Server instance
        :param devices: the devices to look for that are present in the guest
        :type devices: list of strings
        :return: True if the instance has TPM devices, False otherwise
        :rtype: bool
        """
        fip = neutron_tests.floating_ips_from_instance(instance)[0]
        username = guest.boot_tests['focal']['username']
        password = guest.boot_tests['focal'].get('password')
        privkey = openstack_utils.get_private_key(nova_utils.KEYPAIR_NAME)

        def check_tpm(stdin, stdout, stderr):
            devs = [line.strip() for line in stdout.readlines()]
            for expected in devices:
                self.assertIn(expected, devs)

        logging.info('Validating TPM devices are present')
        openstack_utils.ssh_command(username, ip=fip, vm_name=instance.name,
                                    command='sudo ls -1 /dev/tpm*',
                                    password=password, privkey=privkey,
                                    verify=check_tpm)

    @test_utils.skipUntilVersion('nova-compute', 'nova-common', '3:23.0.0')
    def test_launch_vtpm_1_2_instance(self):
        """Launch an instance using TPM 1.2."""
        self.RESOURCE_PREFIX = 'zaza-nova'
        instance = guest.launch_instance(
            'focal', image_name='focal', flavor_name='vtpm-1.2',
            vm_name='zaza-nova-vtpm-1-2',
        )
        # Note: TPM 1.2 presents tpm0 as a device
        self._check_tpm_device(instance, '/dev/tpm0')

    @test_utils.skipUntilVersion('nova-compute', 'nova-common', '3:23.0.0')
    def test_launch_vtpm_2_instance(self):
        """Launch an instance using TPM 2.0."""
        self.RESOURCE_PREFIX = 'zaza-nova'
        instance = guest.launch_instance(
            'focal', image_name='focal', flavor_name='vtpm-2',
            vm_name='zaza-nova-vtpm-2',
        )
        # Note: TPM 1.2 and 2.0 both present tpm0 as a device. TPM 2.0
        # devices also include a tpmrm0 device.
        self._check_tpm_device(instance, '/dev/tpm0', '/dev/tpmrm0')

    def tearDown(self):
        """Cleanup of VM guests."""
        self.resource_cleanup()


class NovaCommonTests(test_utils.OpenStackBaseTest):
    """nova-compute and nova-cloud-controller common tests."""

    XENIAL_MITAKA = openstack_utils.get_os_release('xenial_mitaka')
    XENIAL_OCATA = openstack_utils.get_os_release('xenial_ocata')
    XENIAL_QUEENS = openstack_utils.get_os_release('xenial_queens')
    BIONIC_QUEENS = openstack_utils.get_os_release('bionic_queens')
    BIONIC_ROCKY = openstack_utils.get_os_release('bionic_rocky')
    BIONIC_TRAIN = openstack_utils.get_os_release('bionic_train')

    @classmethod
    def setUpClass(cls):
        """Run class setup for running nova-cloud-controller tests."""
        super(NovaCommonTests, cls).setUpClass()
        cls.current_release = openstack_utils.get_os_release()

    def _test_pci_alias_config(self, app_name, service_list):
        logging.info('Checking pci aliases in nova config...')

        # Expected default and alternate values
        current_value = zaza.model.get_application_config(
            app_name)['pci-alias']
        try:
            current_value = current_value['value']
        except KeyError:
            current_value = None
        new_value = '[{}, {}]'.format(
            json.dumps({
                'name': 'IntelNIC',
                'capability_type': 'pci',
                'product_id': '1111',
                'vendor_id': '8086',
                'device_type': 'type-PF'
            }, sort_keys=True),
            json.dumps({
                'name': ' Cirrus Logic ',
                'capability_type': 'pci',
                'product_id': '0ff2',
                'vendor_id': '10de',
                'device_type': 'type-PCI'
            }, sort_keys=True))

        set_default = {'pci-alias': current_value}
        set_alternate = {'pci-alias': new_value}

        expected_conf_section = 'pci'
        expected_conf_key = 'alias'

        default_entry = {expected_conf_section: {}}
        alternate_entry = {expected_conf_section: {
            expected_conf_key: [
                ('{"capability_type": "pci", "device_type": "type-PF", '
                 '"name": "IntelNIC", "product_id": "1111", '
                 '"vendor_id": "8086"}'),
                ('{"capability_type": "pci", "device_type": "type-PCI", '
                 '"name": " Cirrus Logic ", "product_id": "0ff2", '
                 '"vendor_id": "10de"}')]}}

        # Config file affected by juju set config change
        conf_file = '/etc/nova/nova.conf'

        # Make config change, check for service restarts
        logging.info(
            'Setting config on {} to {}'.format(app_name, set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            service_list)


class CloudActions(test_utils.OpenStackBaseTest):
    """Test actions from actions/cloud.py."""

    def fetch_nova_service_hostname(self, unit_name):
        """
        Fetch hostname used to register with nova-cloud-controller.

        When nova-compute registers with nova-cloud-controller it uses either
        config variable from '/etc/nova/nova.conf` or host's hostname to
        identify itself. We need to fetch this value directly from the unit,
        otherwise it's not possible to correlate entries from
        `nova service-list` with nova-compute units.

        :param unit_name: nova-compute unit name.
        :return: hostname used when registering to cloud-controller
        """
        nova_cfg = ConfigParser()

        result = zaza.model.run_on_unit(unit_name,
                                        'cat /etc/nova/nova.conf')
        nova_cfg.read_string(result['Stdout'])

        try:
            nova_service_name = nova_cfg['DEFAULT']['host']
        except KeyError:
            # Fallback to hostname if 'host' variable is not present in the
            # config
            result = zaza.model.run_on_unit(unit_name, 'hostname')
            nova_service_name = result['Stdout'].rstrip('\n')

        if not nova_service_name:
            self.fail("Failed to fetch nova service name from"
                      " nova-compute unit.")
        return nova_service_name

    def test_940_enable_disable_actions(self):
        """Test disable/enable actions on nova-compute units."""
        nova_units = zaza.model.get_units('nova-compute',
                                          model_name=self.model_name)

        # Check that nova-compute services are enabled before testing
        for service in self.nova_client.services.list(binary='nova-compute'):
            self.assertEqual(service.status, 'enabled')

        # Run 'disable' action on units
        zaza.model.run_action_on_units([unit.name for unit in nova_units],
                                       'disable')

        # Check action results via nova API
        for service in self.nova_client.services.list(binary='nova-compute'):
            self.assertEqual(service.status, 'disabled')

        # Run 'enable' action on units
        zaza.model.run_action_on_units([unit.name for unit in nova_units],
                                       'enable')

        # Check action results via nova API
        for service in self.nova_client.services.list(binary='nova-compute'):
            self.assertEqual(service.status, 'enabled')

    def test_950_instance_count_action(self):
        """Test that action 'instance-count' returns expected values."""
        def check_instance_count(expect_count, unit_name):
            """Assert that unit with 'unit_name' has 'expect_count' of VMs.

            :param expect_count: How many VMs are expected to be running
            :param unit_name: Name of the target nova-compute unit
            :return: None
            :raises AssertionError: If result of the 'instance-count' action
                                    does not match 'expect_count'.
            """
            logging.debug('Running "instance-count" action on unit "{}".'
                          'Expecting result: {}'.format(unit_name,
                                                        expect_count))
            result = zaza.model.run_action(unit_name, 'instance-count')
            self.assertEqual(result.status, 'completed')
            instances = result.data.get('results', {}).get('instance-count')
            self.assertEqual(instances, str(expect_count))

        nova_unit = zaza.model.get_units('nova-compute',
                                         model_name=self.model_name)[0]

        check_instance_count(0, nova_unit.entity_id)

        self.RESOURCE_PREFIX = 'zaza-nova'
        self.launch_guest(
            'ubuntu', instance_key=glance_setup.LTS_IMAGE_NAME)

        check_instance_count(1, nova_unit.entity_id)

        self.resource_cleanup()

    def test_960_remove_from_cloud_actions(self):
        """Test actions remove-from-cloud and register-to-cloud.

        Note (martin-kalcok): This test requires that nova-compute unit is not
        running any VMs. If there are any leftover VMs from previous tests,
        action `remove-from-cloud` will fail.
        """
        def wait_for_nova_compute_count(expected_count):
            """Wait for expected number of nova compute services to be present.

            Returns True or False based on whether the expected number of nova
            compute services was reached within the timeout. Checks are
            performed every 10 second in the span of maximum 5 minutes.
            """
            sleep_timeout = 1  # don't waste 10 seconds on the first run

            for _ in range(31):
                sleep(sleep_timeout)
                service_list = self.nova_client.services.list(
                    host=service_name, binary='nova-compute')
                if len(service_list) == expected_count:
                    return True
                sleep_timeout = 10
            return False

        all_units = zaza.model.get_units('nova-compute',
                                         model_name=self.model_name)

        unit_to_remove = all_units[0]

        service_name = self.fetch_nova_service_hostname(unit_to_remove.name)

        registered_nova_services = self.nova_client.services.list(
            host=service_name, binary='nova-compute')

        service_count = len(registered_nova_services)
        if service_count < 1:
            self.fail("Unit '{}' has no nova-compute services registered in"
                      " nova-cloud-controller".format(unit_to_remove.name))
        elif service_count > 1:
            self.fail("Unexpected number of nova-compute services registered"
                      " in nova-cloud controller. Expecting: 1, found: "
                      "{}".format(service_count))

        # run action remove-from-cloud and wait for the results in
        # nova-cloud-controller
        zaza.model.run_action_on_units([unit_to_remove.name],
                                       'remove-from-cloud',
                                       raise_on_failure=True)

        # Wait for nova-compute service to be removed from the
        # nova-cloud-controller
        if not wait_for_nova_compute_count(0):
            self.fail("nova-compute service was not unregistered from the "
                      "nova-cloud-controller as expected.")

        # run action register-to-cloud to revert previous action
        # and wait for the results in nova-cloud-controller
        zaza.model.run_action_on_units([unit_to_remove.name],
                                       'register-to-cloud',
                                       raise_on_failure=True)

        if not wait_for_nova_compute_count(1):
            self.fail("nova-compute service was not re-registered to the "
                      "nova-cloud-controller as expected.")


class NovaCompute(NovaCommonTests):
    """Run nova-compute specific tests."""

    def test_311_pci_alias_config_compute(self):
        """Verify that the pci alias data is rendered properly.

        Change pci-alias and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # We are not touching the behavior of anything older than QUEENS
        if self.current_release >= self.XENIAL_QUEENS:
            self._test_pci_alias_config("nova-compute", ['nova-compute'])

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
        # Config file affected by juju set config change
        conf_file = '/etc/nova/nova.conf'

        # Make config change, check for service restarts
        logging.info('Changing the debug config on nova-compute')
        self.restart_on_changed_debug_oslo_config_file(
            conf_file,
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


class NovaComputeActionTest(test_utils.OpenStackBaseTest):
    """Run nova-compute specific tests.

    Add this test class for new nova-compute action
    to avoid breaking older version
    """

    def test_virsh_audit_action(self):
        """Test virsh-audit action."""
        for unit in zaza.model.get_units('nova-compute',
                                         model_name=self.model_name):
            logging.info('Running `virsh-audit` action'
                         ' on  unit {}'.format(unit.entity_id))
            action = zaza.model.run_action(
                unit.entity_id,
                'virsh-audit',
                model_name=self.model_name,
                action_params={})
            if "failed" in action.data["status"]:
                raise Exception(
                    "The action failed: {}".format(action.data["message"]))


class NovaComputeNvidiaVgpuTest(test_utils.OpenStackBaseTest):
    """Run nova-compute-nvidia-vgpu specific tests.

    These tests should also turn green if the deployment under test doesn't
    have GPU hardware.
    """

    def test_vgpu_in_nova_conf(self):
        """Test that nova.conf contains vGPU-related settings.

        This test assumes that nova-compute-nvidia-vgpu's config option
        vgpu-device-mappings has been set to something not empty like
        "{'nvidia-108': ['0000:c1:00.0']}".
        """
        for unit in zaza.model.get_units('nova-compute',
                                         model_name=self.model_name):
            nova_conf_file = '/etc/nova/nova.conf'
            nova_conf = str(generic_utils.get_file_contents(unit,
                                                            nova_conf_file))

            # See
            # https://docs.openstack.org/nova/queens/admin/virtual-gpu.html
            # https://docs.openstack.org/nova/ussuri/admin/virtual-gpu.html
            # https://docs.openstack.org/releasenotes/nova/xena.html#deprecation-notes
            self.assertTrue(('enabled_vgpu_types' in nova_conf) or
                            ('enabled_mdev_types' in nova_conf))


class NovaComputeNvidiaVgpuWithHardwareTest(test_utils.OpenStackBaseTest):
    """Run nova-compute-nvidia-vgpu specific tests.

    These tests require real GPU hardware.
    """

    def setUp(self):
        """Declare variables that will be used both in tests and tearDown."""
        self.RESOURCE_PREFIX = 'zaza-nova'
        self.keystone_client = openstack_utils.get_keystone_session_client(
            self.keystone_session)
        self.trait_name = 'CUSTOM_ZAZA_VGPU'
        self.flavor_id = 42

    def tearDown(self):
        """Cleanup all created resources."""
        self.resource_cleanup()  # cleans up the create guests
        self._cleanup_vgpu_flavor()
        self._cleanup_vgpu_trait()

    def test_guest_using_vgpu(self):
        """Test the creation of a guest with a vGPU.

        This test assumes that nova-compute-nvidia-vgpu's config option
        vgpu-device-mappings has been set to something not empty like
        "{'nvidia-108': ['0000:c1:00.0']}".

        This test requires OpenStack Stein or newer.

        This test performs the following steps:
        1.  Download the proprietary NVIDIA software.
        2.  Attach it to the nova-compute-nvidia-vgpu charm as a resource.
        3.  Reboot the compute nodes.
        4.  List the available vGPU types.
        5.  Select a vGPU type via juju config option on the charm.
        6.  Check the amount of used vGPUs.
        7.  Create a vGPU trait.
        8.  Create a flavor with this trait.
        9.  Create a guest with this flavor.
        10. Check the amount of used vGPUs.
        """
        package_local_path = self._download_nvidia_package()

        self._attach_nvidia_package_as_resource(package_local_path)
        self._reboot_vgpu_units()

        wanted_vgpu_type = 'nvidia-108'
        wanted_gpu_address = '0000:c1:00.0'
        self._assert_vgpu_type_available(wanted_vgpu_type, wanted_gpu_address)

        logging.info('Selecting vGPU type {} on GPU {} ...'.format(
            wanted_vgpu_type, wanted_gpu_address))
        alternate_config = {
            "vgpu-device-mappings": ("{'" + wanted_vgpu_type + "': ['" +
                                     wanted_gpu_address + "']}")
        }
        with self.config_change({}, alternate_config, self.application_name,
                                reset_to_charm_default=True):
            self._install_openstack_cli_on_vgpu_units()

            resource_provider_id = self._get_vgpu_resource_provider_id(
                wanted_gpu_address)
            num_vgpu_used_before = self._get_num_vgpu_used(
                resource_provider_id)

            self._create_vgpu_trait(resource_provider_id)
            flavor_name = 'm1.small.vgpu'
            self._create_vgpu_flavor(flavor_name)
            self._assign_vgpu_trait_to_flavor(flavor_name)

            self.launch_guest(
                'vgpu', instance_key=glance_setup.LTS_IMAGE_NAME,
                flavor_name=flavor_name)

            num_vgpu_used_after = self._get_num_vgpu_used(resource_provider_id)
            self.assertEqual(num_vgpu_used_after, num_vgpu_used_before + 1)

    def _download_nvidia_package(self):
        package_cache_dir = tempfile.gettempdir()
        package_url = os.environ['TEST_NVIDIA_VGPU_HOST_SW']
        package_name = os.path.basename(urllib.parse.urlparse(
            package_url).path)
        package_local_path = os.path.join(package_cache_dir, package_name)
        if not os.path.exists(package_local_path):
            logging.info('Downloading {} to {} ...'.format(
                package_url, package_local_path))
            openstack_utils.download_image(package_url, package_local_path)
        else:
            logging.info(
                'Cached package found at {} - Skipping download'.format(
                    package_local_path))
        return package_local_path

    def _get_vgpu_unit_names(self):
        vgpu_unit_names = [unit.name for unit in
                           zaza.model.get_units(self.application_name)]
        self.assertGreater(len(vgpu_unit_names), 0, 'No vGPU unit found')
        return vgpu_unit_names

    def _attach_nvidia_package_as_resource(self, package_local_path):
        logging.info('Attaching {} as a resource...'.format(
            package_local_path))
        zaza.model.attach_resource(self.application_name,
                                   'nvidia-vgpu-software',
                                   package_local_path)
        for vgpu_unit_name in self._get_vgpu_unit_names():
            zaza.model.block_until_unit_wl_message_match(
                vgpu_unit_name, '.*installed NVIDIA software.*')
        zaza.model.block_until_all_units_idle()

    def _reboot_vgpu_units(self):
        vgpu_unit_names = self._get_vgpu_unit_names()
        for vgpu_unit_name in vgpu_unit_names:
            logging.info('Rebooting {} ...'.format(vgpu_unit_name))
            generic_utils.reboot(vgpu_unit_name)
            zaza.model.block_until_unit_wl_status(vgpu_unit_name, "unknown")
        for vgpu_unit_name in vgpu_unit_names:
            zaza.model.block_until_unit_wl_status(vgpu_unit_name, "active")
        zaza.model.block_until_all_units_idle()

    def _assert_vgpu_type_available(self, wanted_vgpu_type,
                                    wanted_gpu_address):
        logging.info(
            'Checking that the vGPU type {} is available on GPU {} ...'.format(
                wanted_vgpu_type, wanted_gpu_address))
        available_vgpu_types = zaza.model.run_action_on_leader(
            self.application_name, 'list-vgpu-types',
            raise_on_failure=True).results['output']
        self.assertIn('{}, {}'.format(wanted_vgpu_type, wanted_gpu_address),
                      available_vgpu_types)

    def _install_openstack_cli_on_vgpu_units(self):
        command = 'snap install openstackclients'
        for vgpu_unit_name in self._get_vgpu_unit_names():
            juju_utils.remote_run(vgpu_unit_name, remote_cmd=command,
                                  timeout=180, fatal=True)

    def _get_vgpu_resource_provider_id(self, wanted_gpu_address):
        logging.info('Querying resource providers...')
        command = (
            'openstack {} resource provider list -f value -c uuid -c name')
        command = command.format(openstack_utils.get_cli_auth_args(
            self.keystone_client))
        resource_providers = juju_utils.remote_run(
            self._get_vgpu_unit_names()[0], remote_cmd=command, timeout=180,
            fatal=True).strip().split('\n')

        # At this point resource_providers should look like
        # ['0e1379b8-7bd1-40e6-9f41-93cb5b95e38b node-sparky.maas',
        #  '1bb845a4-cf21-44c2-896e-e877760ad39b \
        #   node-sparky.maas_pci_0000_c1_00_0']
        resource_provider_id = None
        wanted_resource_provider_substring = 'pci_{}'.format(
            wanted_gpu_address.replace(':', '_').replace('.', '_'))
        for resource_provider in resource_providers:
            if wanted_resource_provider_substring in resource_provider:
                resource_provider_id = resource_provider.split()[0]
        self.assertIsNotNone(resource_provider_id)
        return resource_provider_id

    def _get_num_vgpu_used(self, resource_provider_id):
        logging.info('Querying resource provider inventory...')
        command = (
            'openstack {} resource provider inventory list {} '
            '-f value -c used')
        command = command.format(openstack_utils.get_cli_auth_args(
            self.keystone_client), resource_provider_id)
        num_vgpu_used = juju_utils.remote_run(
            self._get_vgpu_unit_names()[0], remote_cmd=command, timeout=180,
            fatal=True).strip()
        return int(num_vgpu_used)

    def _create_vgpu_trait(self, resource_provider_id):
        logging.info('Creating trait {}...'.format(self.trait_name))
        command = (
            'openstack {} --os-placement-api-version 1.6 trait create {}')
        command = command.format(openstack_utils.get_cli_auth_args(
            self.keystone_client), self.trait_name)
        first_unit_name = self._get_vgpu_unit_names()[0]
        juju_utils.remote_run(first_unit_name, remote_cmd=command, timeout=180,
                              fatal=True)
        command = (
            'openstack {} --os-placement-api-version 1.6 resource provider '
            'trait set --trait {} {}')
        command = command.format(openstack_utils.get_cli_auth_args(
            self.keystone_client), self.trait_name, resource_provider_id)
        juju_utils.remote_run(first_unit_name, remote_cmd=command, timeout=180,
                              fatal=True)

    def _cleanup_vgpu_trait(self):
        logging.info('Cleaning up trait {}...'.format(self.trait_name))
        command = (
            'openstack {} --os-placement-api-version 1.6 trait delete {}')
        command = command.format(openstack_utils.get_cli_auth_args(
            self.keystone_client), self.trait_name)
        juju_utils.remote_run(
            self._get_vgpu_unit_names()[0], remote_cmd=command, timeout=180,
            fatal=False)

    def _create_vgpu_flavor(self, flavor_name):
        logging.info('Creating flavor {}...'.format(flavor_name))
        nova_client = openstack_utils.get_nova_session_client(
            self.keystone_session)
        nova_client.flavors.create(name=flavor_name, ram=2048, vcpus=1,
                                   disk=20, flavorid=self.flavor_id)

    def _cleanup_vgpu_flavor(self):
        logging.info('Cleaning up created flavor...')
        nova_client = openstack_utils.get_nova_session_client(
            self.keystone_session)
        try:
            flavor = nova_client.flavors.get(self.flavor_id)
        except novaclient.exceptions.NotFound:
            return
        nova_client.flavors.delete(flavor)

    def _assign_vgpu_trait_to_flavor(self, flavor_name):
        logging.info('Assigning trait {} to flavor {} ...'.format(
            self.trait_name, flavor_name))
        command = (
            'openstack {} flavor set {} --property resources:VGPU=1 '
            '--property trait:{}=required')
        command = command.format(openstack_utils.get_cli_auth_args(
            self.keystone_client), flavor_name, self.trait_name)
        juju_utils.remote_run(
            self._get_vgpu_unit_names()[0], remote_cmd=command, timeout=180,
            fatal=True)


class NovaCloudControllerActionTest(test_utils.OpenStackBaseTest):
    """Run nova-cloud-controller specific tests.

    Add this test class for new nova-cloud-controller action
    to avoid breaking older version.
    """

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(4))
    def test_sync_compute_az_action(self):
        """Test sync-compute-availability-zones action."""
        juju_units_az_map = {}
        compute_config = zaza.model.get_application_config('nova-compute')
        default_az = compute_config['default-availability-zone']['value']
        use_juju_az = compute_config['customize-failure-domain']['value']

        for unit in zaza.model.get_units('nova-compute',
                                         model_name=self.model_name):
            zone = default_az
            if use_juju_az:
                result = zaza.model.run_on_unit(unit.name,
                                                'echo $JUJU_AVAILABILITY_ZONE',
                                                model_name=self.model_name,
                                                timeout=60)
                self.assertEqual(int(result['Code']), 0)
                juju_az = result['Stdout'].strip()
                if juju_az:
                    zone = juju_az

            juju_units_az_map[zaza.model.get_unit_public_address(unit)] = zone
            continue

        session = openstack_utils.get_overcloud_keystone_session()
        nova = openstack_utils.get_nova_session_client(session)

        result = zaza.model.run_action_on_leader(
            'nova-cloud-controller',
            'sync-compute-availability-zones',
            model_name=self.model_name)

        # For validating the action results, we simply want to validate that
        # the action was completed and we have something in the output. The
        # functional validation really occurs below, in that the hosts are
        # checked to be in the appropriate host aggregates.
        self.assertEqual(result.status, 'completed')
        self.assertNotEqual('', result.results['output'])

        unique_az_list = list(set(juju_units_az_map.values()))
        aggregates = nova.aggregates.list()
        self.assertEqual(len(aggregates), len(unique_az_list))
        for unit_address in juju_units_az_map:
            az = juju_units_az_map[unit_address]
            aggregate = nova.aggregates.find(
                name='{}_az'.format(az), availability_zone=az)
            hypervisor = nova.hypervisors.find(host_ip=unit_address)
            self.assertIn(hypervisor.hypervisor_hostname, aggregate.hosts)


class NovaCloudController(NovaCommonTests):
    """Run nova-cloud-controller specific tests."""

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
            assert expected_service_name in actual_service_names

        # Thanks to setup.create_flavors we should have a few flavors already:
        assert len(nova.flavors.list()) > 0

        # Just checking it's not raising and returning an iterable:
        assert len(nova.servers.list()) >= 0

    def test_106_compute_catalog_endpoints(self):
        """Verify that the compute endpoints are present in the catalog."""
        overcloud_auth = openstack_utils.get_overcloud_auth()
        keystone_client = openstack_utils.get_keystone_client(
            overcloud_auth)
        actual_endpoints = keystone_client.service_catalog.get_endpoints()

        logging.info('Checking compute endpoints...')

        if self.current_release < self.XENIAL_QUEENS:
            actual_compute_endpoints = actual_endpoints['compute'][0]
            for expected_url in ('internalURL', 'adminURL', 'publicURL'):
                assert expected_url in actual_compute_endpoints
        else:
            actual_compute_interfaces = [endpoint['interface'] for endpoint in
                                         actual_endpoints['compute']]
            for expected_interface in ('internal', 'admin', 'public'):
                assert expected_interface in actual_compute_interfaces

    def test_220_nova_metadata_propagate(self):
        """Verify that the vendor-data settings are propagated.

        Change vendor-data-url and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        if self.current_release < self.BIONIC_ROCKY:
            logging.info("Feature didn't exist before Rocky. Nothing to test")
            return

        # Expected default and alternate values
        current_value = zaza.model.get_application_config(
            'nova-cloud-controller')['vendor-data-url']['value']
        new_value = 'http://some-other.url/vdata'

        set_default = {'vendor-data-url': current_value}
        set_alternate = {'vendor-data-url': new_value}
        default_entry = {'api': {
            'vendordata_dynamic_targets': [current_value]}}
        alternate_entry = {'api': {'vendordata_dynamic_targets': [new_value]}}

        # Config file affected by juju set config change
        conf_file = '/etc/nova/nova.conf'

        # Make config change, check for service restarts
        logging.info(
            'Setting config on nova-cloud-controller to {}'.format(
                set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            self.services)

    def test_230_resize_to_the_same_host(self):
        """Verify that the allow-resize-to-same-host setting is propagated.

        Change allow-resize-to-same-host and assert that change propagates to
        the correct file on nova-cloud-controller units and that services are
        restarted as a result. Also verify that the setting is propagated to
        the nova-compute units.
        """
        services = ['nova-compute']
        nova_config_key = 'allow_resize_to_same_host'
        juju_config_key = 'allow-resize-to-same-host'
        try:
            current_value = zaza.model.get_application_config(
                'nova-cloud-controller')[juju_config_key]['value']
        except KeyError:
            logging.info('This version of nova-cloud-controller charm does '
                         'not suport {} config option. '
                         'Nothing to test.'.format(juju_config_key))
            return

        new_value = 'True'
        set_default = {juju_config_key: current_value}
        set_alternate = {juju_config_key: new_value}

        mtime = zaza.model.get_unit_time(
            self.lead_unit,
            model_name=self.model_name)
        logging.debug('Remote unit timestamp {}'.format(mtime))

        # Make config change, wait for the services restart on
        # nova-cloud-controller
        with self.config_change(set_default, set_alternate):
            # The config change should propagate to nova-cmopute units
            # Wait for them to get settled after relation data has changed
            logging.info(
                'Waiting for services ({}) to be restarted'.format(services))
            zaza.model.block_until_services_restarted(
                'nova-compute',
                mtime,
                services,
                model_name=self.model_name)

            # Get config value form nova-compute units and verify that
            # it's changed
            nova_cfg = ConfigParser()

            for unit in zaza.model.get_units('nova-compute',
                                             model_name=self.model_name):
                logging.info('Checking value of {} in {}'.format(
                    nova_config_key, unit.entity_id))
                result = zaza.model.run_on_unit(
                    unit.entity_id,
                    'cat /etc/nova/nova.conf')
                nova_cfg.read_string(result['Stdout'])

                try:
                    allow_resize_to_same_host =\
                        nova_cfg['DEFAULT'][nova_config_key]
                    logging.debug('Unit {}; value of {} is: {}'.format(
                        unit.entity_id,
                        nova_config_key,
                        allow_resize_to_same_host))
                except KeyError:
                    logging.error('Key {} not found for unit {}'.format(
                        nova_config_key, unit.entity_id))
                    allow_resize_to_same_host = None

                self.assertEqual(new_value, allow_resize_to_same_host)

    def test_302_api_rate_limiting_is_enabled(self):
        """Check that API rate limiting is enabled."""
        logging.info('Checking api-paste config file data...')
        zaza.model.block_until_oslo_config_entries_match(
            'nova-cloud-controller', '/etc/nova/api-paste.ini', {
                'filter:legacy_ratelimit': {
                    'limits': ["( POST, '*', .*, 9999, MINUTE );"]}})

    def test_310_pci_alias_config_ncc(self):
        """Verify that the pci alias data is rendered properly.

        Change pci-alias and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        self._test_pci_alias_config("nova-cloud-controller", self.services)

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Config file affected by juju set config change
        conf_file = '/etc/nova/nova.conf'

        # Make config change, check for service restarts
        logging.info('Changing debug config on nova-cloud-controller')
        self.restart_on_changed_debug_oslo_config_file(
            conf_file,
            self.services)

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(self.services):
            logging.info("Testing pause resume")

    def test_902_quota_settings(self):
        """Verify that the quota settings are propagated.

        Change quota-instances and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        current_value = zaza.model.get_application_config(
            'nova-cloud-controller')['quota-instances']
        try:
            current_value = current_value['value']
        except KeyError:
            current_value = 0
        new_value = '20'

        set_default = {'quota-instances': current_value}
        set_alternate = {'quota-instances': new_value}

        expected_conf_section = 'DEFAULT'
        expected_conf_key = 'quota_instances'
        if self.current_release >= self.XENIAL_OCATA:
            expected_conf_section = 'quota'
            expected_conf_key = 'instances'

        default_entry = {expected_conf_section: {}}
        alternate_entry = {expected_conf_section: {
            expected_conf_key: [new_value]}}

        # Config file affected by juju set config change
        conf_file = '/etc/nova/nova.conf'

        # Make config change, check for service restarts
        logging.info(
            'Setting config on nova-cloud-controller to {}'.format(
                set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            self.services)

    def test_903_enable_quota_count_usage_from_placement(self):
        """Verify that quota-count-usage-from-placement is propagated.

        Change quota-count-usage-from-placement and assert that nova
        configuration file is updated and the services are restarted.
        This parameter is not supported for releases<Train. In those
        cases assert that nova configuration file is not updated.
        """
        # Expected default and alternate values
        current_value = zaza.model.get_application_config(
            'nova-cloud-controller')['quota-count-usage-from-placement']
        try:
            current_value = current_value['value']
        except KeyError:
            current_value = False

        new_value = not current_value
        new_value_str = str(new_value).title()
        current_value_str = str(current_value).title()

        set_default = {'quota-count-usage-from-placement': current_value}
        set_alternate = {'quota-count-usage-from-placement': new_value}

        expected_conf_section = 'quota'
        expected_conf_key = 'count_usage_from_placement'

        # In case quota-count-usage-from-placement is False, the quota
        # section  in nova conf file is empty
        if current_value:
            default_entry = {expected_conf_section: {
                expected_conf_key: [current_value_str]}}
            alternate_entry = {expected_conf_section: {}}
        else:
            default_entry = {expected_conf_section: {}}
            alternate_entry = {expected_conf_section: {
                expected_conf_key: [new_value_str]}}

        # Config file affected by juju set config change
        conf_file = '/etc/nova/nova.conf'

        if self.current_release < self.BIONIC_TRAIN:
            # Configuration is not supported in releases<Train
            default_entry = {expected_conf_section: {}}
            alternate_entry = {expected_conf_section: {}}
            services = {}
        else:
            services = self.services

        # Make config change, check for service restarts
        logging.info(
            'Setting config on nova-cloud-controller to {}'.format(
                set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            services)


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
        ]
        expected_passes = [
            'validate-file-ownership',
            'validate-file-permissions',
            'validate-uses-keystone',
        ]
        tls_checks = [
            'validate-uses-tls-for-glance',
            'validate-uses-tls-for-keystone',
        ]
        if zaza.model.get_relation_id(
                'nova-cloud-controller',
                'vault',
                remote_interface_name='certificates'):
            expected_passes.extend(tls_checks)
        else:
            expected_failures.extend(tls_checks)

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
                expected_to_pass=not len(expected_failures))


class NovaTempestTestK8S(tempest_tests.TempestTestScaleK8SBase):
    """Test nova k8s scale out and scale back."""

    application_name = "nova"
