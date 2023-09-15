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

"""Encapsulate Cinder testing."""

import logging
import time

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.neutron.tests as neutron_tests
import zaza.openstack.configure.guest as guest
import zaza.openstack.charm_tests.nova.utils as nova_utils
import zaza.openstack.charm_tests.tempest.tests as tempest_tests

from tenacity import (
    Retrying,
    stop_after_attempt,
    wait_exponential,
)


class CinderTests(test_utils.OpenStackBaseTest):
    """Encapsulate Cinder tests."""

    RESOURCE_PREFIX = 'zaza-cindertests'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(CinderTests, cls).setUpClass(application_name='cinder')
        cls.application_name = 'cinder'
        cls.lead_unit = zaza.model.get_lead_unit_name(
            "cinder", model_name=cls.model_name)
        # version 3.42 is required for in-use (online) resizing lvm volumes
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session, version=3.42)
        cls.nova_client = openstack_utils.get_nova_session_client(
            cls.keystone_session)

    @classmethod
    def tearDown(cls):
        """Remove test resources."""
        logging.info('Running teardown')
        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                volumes = list(cls.cinder_client.volumes.list())
                snapped_volumes = [v for v in volumes
                                   if v.name.endswith("-from-snap")]
                if snapped_volumes:
                    logging.info("Removing volumes from snapshot")
                    cls._remove_volumes(snapped_volumes)
                    volumes = list(cls.cinder_client.volumes.list())

                snapshots = list(cls.cinder_client.volume_snapshots.list())
                if snapshots:
                    logging.info("tearDown - snapshots: {}".format(
                        ", ".join(s.name for s in snapshots)))
                    cls._remove_snapshots(snapshots)

                if volumes:
                    logging.info("tearDown - volumes: {}".format(
                        ", ".join(v.name for v in volumes)))
                    cls._remove_volumes(volumes)

                fips_reservations = []
                for vm in cls.nova_client.servers.list():
                    if vm.name.startswith(cls.RESOURCE_PREFIX):
                        fips_reservations += (
                            neutron_tests.floating_ips_from_instance(vm)
                        )
                        vm.delete()
                        openstack_utils.resource_removed(
                            cls.nova_client.servers,
                            vm.id,
                            msg=(
                                "Waiting for the Nova VM {} "
                                "to be deleted".format(vm.name)
                            ),
                        )

                if fips_reservations:
                    logging.info('Cleaning up test FiPs reservations')
                    neutron = openstack_utils.get_neutron_session_client(
                        session=cls.keystone_session)
                    for fip in neutron.list_floatingips()['floatingips']:
                        if fip['floating_ip_address'] in fips_reservations:
                            neutron.delete_floatingip(fip['id'])

    @classmethod
    def _remove_snapshots(cls, snapshots):
        """Remove snapshots passed as param.

        :param volumes: the snapshots to delete
        :type volumes: List[snapshot objects]
        """
        for snapshot in snapshots:
            if snapshot.name.startswith(cls.RESOURCE_PREFIX):
                logging.info("removing snapshot: {}".format(snapshot.name))
                try:
                    openstack_utils.delete_resource(
                        cls.cinder_client.volume_snapshots,
                        snapshot.id,
                        msg="snapshot")
                except Exception as e:
                    logging.error("error removing snapshot: {}".format(str(e)))
                    raise

    @classmethod
    def _remove_volumes(cls, volumes):
        """Remove volumes passed as param.

        :param volumes: the volumes to delete
        :type volumes: List[volume objects]
        """
        for volume in volumes:
            if volume.name.startswith(cls.RESOURCE_PREFIX):
                for attachment in volume.attachments:
                    instance_id = attachment['server_id']
                    logging.info("detaching volume: {}".format(volume.name))
                    openstack_utils.detach_volume(cls.nova_client,
                                                  volume.id, instance_id)
                logging.info("removing volume: {}".format(volume.name))
                try:
                    openstack_utils.delete_resource(
                        cls.cinder_client.volumes,
                        volume.id,
                        msg="volume")
                except Exception as e:
                    logging.error("error removing volume: {}".format(str(e)))
                    raise

    def test_100_volume_create_extend_delete(self):
        """Test creating, extending a volume."""
        vol_new = self.cinder_client.volumes.create(
            name='{}-100-vol'.format(self.RESOURCE_PREFIX),
            size='1')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            wait_iteration_max_time=1200,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")
        self.cinder_client.volumes.extend(
            vol_new.id,
            '2')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            wait_iteration_max_time=1200,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

    def test_105_volume_create_from_img(self):
        """Test creating a volume from an image."""
        logging.debug("finding image {} ..."
                      .format(glance_setup.LTS_IMAGE_NAME))
        image = self.nova_client.glance.find_image(
            glance_setup.LTS_IMAGE_NAME)
        logging.debug("using cinder_client to create volume from image {}"
                      .format(image.id))
        vol_img = self.cinder_client.volumes.create(
            name='{}-105-vol-from-img'.format(self.RESOURCE_PREFIX),
            size=3,
            imageRef=image.id)
        logging.debug("now waiting for volume {} to reach available"
                      .format(vol_img.id))
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_img.id,
            wait_iteration_max_time=1200,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

    def test_110_volume_snap_clone(self):
        """Test creating snapshot and build a volume from it."""
        # Create a 1GB
        vol_new = self.cinder_client.volumes.create(
            name='{}-110-vol'.format(self.RESOURCE_PREFIX),
            size='1')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            wait_iteration_max_time=1200,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

        # Snapshot the volume
        snap_new = self.cinder_client.volume_snapshots.create(
            volume_id=vol_new.id,
            name='{}-110-snap'.format(self.RESOURCE_PREFIX))
        openstack_utils.resource_reaches_status(
            self.cinder_client.volume_snapshots,
            snap_new.id,
            wait_iteration_max_time=1200,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

        # Create a volume from the snapshot
        vol_from_snap = self.cinder_client.volumes.create(
            name='{}-110-vol-from-snap'.format(self.RESOURCE_PREFIX),
            size=snap_new.size,
            snapshot_id=snap_new.id)
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_from_snap.id,
            wait_iteration_max_time=1200,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

    def test_120_volume_force_delete(self):
        """Test force deleting a volume."""
        vol_new = self.cinder_client.volumes.create(
            name='{}-120-vol'.format(self.RESOURCE_PREFIX),
            size='1')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            wait_iteration_max_time=1200,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")
        vol_new.force_delete()
        openstack_utils.resource_removed(
            self.cinder_client.volumes,
            vol_new.id,
            msg="Volume")

    def test_200_online_extend_volume(self):
        """Test extending a volume while attached to an instance."""
        test_vol = self.cinder_client.volumes.create(
            name='{}-200-vol'.format(self.RESOURCE_PREFIX),
            size='1')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            test_vol.id,
            wait_iteration_max_time=1200,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

        instance_name = '{}-200'.format(self.RESOURCE_PREFIX)
        instance = self.launch_guest(
            instance_name,
            instance_key=glance_setup.LTS_IMAGE_NAME,
            flavor_name='m1.small',
        )
        openstack_utils.attach_volume(
            self.nova_client, test_vol.id, instance.id
        )
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            test_vol.id,
            wait_iteration_max_time=1200,
            stop_after_attempt=20,
            expected_status="in-use",
            msg="Volume status wait")
        # refresh the volume object now that it's attached
        test_vol = self.cinder_client.volumes.get(test_vol.id)
        self.assertEqual(test_vol.size, 1)

        # resize online and verify it's been resised from cinder's side
        self.cinder_client.volumes.extend(test_vol.id, '2')
        # wait for the resize to complete, then refresh the local data
        time.sleep(5)
        test_vol = self.cinder_client.volumes.get(test_vol.id)
        self.assertEqual(test_vol.size, 2)

        fip = neutron_tests.floating_ips_from_instance(instance)[0]
        username = guest.boot_tests['bionic']['username']
        privkey = openstack_utils.get_private_key(nova_utils.KEYPAIR_NAME)

        # now verify that the instance sees the new size
        def verify(stdin, stdout, stderr):
            status = stdout.channel.recv_exit_status()
            self.assertEqual(status, 0)
            output = stdout.read().decode().strip()
            self.assertEqual(output, '2G')

        openstack_utils.ssh_command(
            username, fip, instance_name,
            'lsblk -sn -o SIZE /dev/vdb',
            privkey=privkey, verify=verify)

    @property
    def services(self):
        """Return a list services for the selected OpenStack release."""
        current_value = zaza.model.get_application_config(
            self.application_name)['enabled-services']['value']

        if current_value == "all":
            services = ['cinder-scheduler', 'cinder-volume', 'cinder-api']
        else:
            services = ['cinder-{}'.format(svc)
                        for svc in ('api', 'scheduler', 'volume')
                        if svc in current_value]

        if ('cinder-api' in services and
            (openstack_utils.get_os_release() >=
                openstack_utils.get_os_release('xenial_ocata'))):
            services.remove('cinder-api')
            services.append('apache2')

        return services

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Config file affected by juju set config change
        conf_file = '/etc/cinder/cinder.conf'

        # Make config change, check for service restarts
        logging.debug('Setting debug mode...')
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


class SecurityTests(test_utils.OpenStackBaseTest):
    """Keystone security tests tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone aa-tests."""
        super(SecurityTests, cls).setUpClass()

    def test_security_checklist(self):
        """Verify expected state with security-checklist."""
        # Changes fixing the below expected failures will be made following
        # this initial work to get validation in. There will be bugs targeted
        # to each one and resolved independently where possible.

        expected_failures = [
            'check-max-request-body-size',
            'is-volume-encryption-enabled',
            'uses-tls-for-glance',
            'uses-tls-for-nova',
            'validate-uses-tls-for-keystone',
        ]
        expected_passes = [
            'validate-file-ownership',
            'validate-file-permissions',
            'validate-nas-uses-secure-environment',
            'validate-uses-keystone',
        ]

        for unit in zaza.model.get_units('cinder', model_name=self.model_name):
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


class CinderTempestTestK8S(tempest_tests.TempestTestScaleK8SBase):
    """Test cinder k8s scale out and scale back."""

    application_name = "cinder"
