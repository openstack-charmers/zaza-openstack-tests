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

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup

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
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session)
        cls.nova_client = openstack_utils.get_nova_session_client(
            cls.keystone_session)

    def setUp(self):
        """Verify cinder services are up and ready."""
        super(CinderTests, self).setUp()
        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                services = list(self.cinder_client.services.list())
                services_ready = [
                    svc.binary for svc in services
                    if svc.state == 'up' and svc.status == 'enabled'
                ]
                if len(services) != len(services_ready):
                    logging.debug('services ready: {}; waiting for all'
                                  ' services to become ready.'
                                  ''.format(', '.join(services_ready)))
                    continue

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
        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                vol_new = self.cinder_client.volumes.create(
                    name='{}-100-vol'.format(self.RESOURCE_PREFIX),
                    size='1')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            wait_iteration_max_time=180,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")
        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                self.cinder_client.volumes.extend(
                    vol_new.id,
                    '2')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            wait_iteration_max_time=180,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

    def test_105_volume_create_from_img(self):
        """Test creating a volume from an image."""
        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                logging.debug("finding image {} ..."
                              .format(glance_setup.LTS_IMAGE_NAME))
                image = self.nova_client.glance.find_image(
                    glance_setup.LTS_IMAGE_NAME)
                logging.debug("using cinder_client to create volume"
                              " from image {}".format(image.id))
                vol_img = self.cinder_client.volumes.create(
                    name='{}-105-vol-from-img'.format(self.RESOURCE_PREFIX),
                    size=3,
                    imageRef=image.id)
        logging.debug("now waiting for volume {} to reach available"
                      .format(vol_img.id))
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_img.id,
            wait_iteration_max_time=300,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

    def test_110_volume_snap_clone(self):
        """Test creating snapshot and build a volume from it."""
        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                # Create a 1GB
                vol_new = self.cinder_client.volumes.create(
                    name='{}-110-vol'.format(self.RESOURCE_PREFIX),
                    size='1')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            wait_iteration_max_time=600,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                # Snapshot the volume
                snap_new = self.cinder_client.volume_snapshots.create(
                    volume_id=vol_new.id,
                    name='{}-110-snap'.format(self.RESOURCE_PREFIX))
        openstack_utils.resource_reaches_status(
            self.cinder_client.volume_snapshots,
            snap_new.id,
            wait_iteration_max_time=600,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                # Create a volume from the snapshot
                vol_from_snap = self.cinder_client.volumes.create(
                    name='{}-110-vol-from-snap'.format(self.RESOURCE_PREFIX),
                    size=snap_new.size,
                    snapshot_id=snap_new.id)
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_from_snap.id,
            wait_iteration_max_time=600,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")

    def test_120_volume_force_delete(self):
        """Test force deleting a volume."""
        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                vol_new = self.cinder_client.volumes.create(
                    name='{}-120-vol'.format(self.RESOURCE_PREFIX),
                    size='1')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            wait_iteration_max_time=600,
            stop_after_attempt=20,
            expected_status="available",
            msg="Volume status wait")
        for attempt in Retrying(
                stop=stop_after_attempt(8),
                wait=wait_exponential(multiplier=1, min=2, max=60)):
            with attempt:
                vol_new.force_delete()
                openstack_utils.resource_removed(
                    self.cinder_client.volumes,
                    vol_new.id,
                    msg="Volume")

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

    def _security_checklist(self, expected_failures, expected_passes):
        """Verify expected state with security-checklist."""
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
        self._security_checklist(expected_failures, expected_passes)


class TLSSecurityTests(SecurityTests):
    """Keystone over TLS security tests tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone aa-tests."""
        super(TLSSecurityTests, cls).setUpClass()

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
        ]
        expected_passes = [
            'validate-file-ownership',
            'validate-file-permissions',
            'validate-nas-uses-secure-environment',
            'validate-uses-keystone',
            'validate-uses-tls-for-keystone',
        ]
        self._security_checklist(expected_failures, expected_passes)
