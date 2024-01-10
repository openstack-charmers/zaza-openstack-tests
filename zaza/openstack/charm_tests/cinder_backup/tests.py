#!/usr/bin/env python3
#
# Copyright 2019 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Encapsulate cinder-backup testing."""
import copy
import logging

import tenacity

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.ceph as ceph_utils
import zaza.openstack.utilities.openstack as openstack_utils
from zaza.openstack.utilities import ObjectRetrierWraps


class CinderBackupTest(test_utils.OpenStackBaseTest):
    """Encapsulate Cinder Backup tests."""

    RESOURCE_PREFIX = 'zaza-cinderbackuptests'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Cinder Backup tests."""
        super(CinderBackupTest, cls).setUpClass()
        cls.cinder_client = ObjectRetrierWraps(
            openstack_utils.get_cinder_session_client(
                cls.keystone_session))

    @property
    def services(self):
        """Return a list services for the selected OpenStack release."""
        current_release = openstack_utils.get_os_release()
        services = ['cinder-scheduler', 'cinder-volume']
        if (current_release >=
                openstack_utils.get_os_release('xenial_ocata')):
            services.append('apache2')
        else:
            services.append('cinder-api')
        return services

    def test_100_volume_create_extend_delete(self):
        """Test creating, extending a volume."""
        vol_new = openstack_utils.create_volume(
            self.cinder_client,
            name='{}-100-vol'.format(self.RESOURCE_PREFIX),
            size=1)
        self.cinder_client.volumes.extend(
            vol_new.id,
            '2')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            expected_status="available",
            msg="Extended volume")

    def test_410_cinder_vol_create_backup_delete_restore_pool_inspect(self):
        """Create, backup, delete, restore a ceph-backed cinder volume.

        Create, backup, delete, restore a ceph-backed cinder volume, and
        inspect ceph cinder pool object count as the volume is created
        and deleted.
        """
        unit_name = zaza.model.get_lead_unit_name('ceph-mon')
        obj_count_samples = []
        pool_size_samples = []
        pools = ceph_utils.get_ceph_pools(unit_name)
        expected_pool = 'cinder-ceph'
        cinder_ceph_pool = pools[expected_pool]

        # Check ceph cinder pool object count, disk space usage and pool name
        logging.info('Checking ceph cinder pool original samples...')
        pool_name, obj_count, kb_used = ceph_utils.get_ceph_pool_sample(
            unit_name, cinder_ceph_pool)

        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        self.assertEqual(pool_name, expected_pool)

        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_attempt(3)):
            with attempt:
                # Create ceph-backed cinder volume
                cinder_vol_name = '{}-410-{}-vol'.format(
                    self.RESOURCE_PREFIX, attempt.retry_state.attempt_number)
                cinder_vol = self.cinder_client.volumes.create(
                    name=cinder_vol_name, size=1)
                openstack_utils.resource_reaches_status(
                    self.cinder_client.volumes,
                    cinder_vol.id,
                    wait_iteration_max_time=180,
                    stop_after_attempt=15,
                    expected_status='available',
                    msg='ceph-backed cinder volume')

                # Back up the volume
                # NOTE(lourot): sometimes, especially on Mitaka, the backup
                # remains stuck forever in 'creating' state and the volume in
                # 'backing-up' state. See lp:1877076
                # Attempting to create another volume and another backup
                # usually then succeeds. Release notes and bug trackers show
                # that many things have been fixed and are still left to be
                # fixed in this area.
                # When the backup creation succeeds, it usually does within
                # 12 minutes.
                vol_backup_name = '{}-410-{}-backup-vol'.format(
                    self.RESOURCE_PREFIX, attempt.retry_state.attempt_number)
                vol_backup = self.cinder_client.backups.create(
                    cinder_vol.id, name=vol_backup_name)
                openstack_utils.resource_reaches_status(
                    self.cinder_client.backups,
                    vol_backup.id,
                    wait_iteration_max_time=180,
                    stop_after_attempt=15,
                    expected_status='available',
                    msg='Backup volume')

        # Delete the volume
        openstack_utils.delete_volume(self.cinder_client, cinder_vol.id)
        # Restore the volume
        self.cinder_client.restores.restore(vol_backup.id)
        openstack_utils.resource_reaches_status(
            self.cinder_client.backups,
            vol_backup.id,
            wait_iteration_max_time=180,
            stop_after_attempt=15,
            expected_status='available',
            msg='Restored backup volume')
        # Delete the backup
        openstack_utils.delete_volume_backup(
            self.cinder_client,
            vol_backup.id)
        openstack_utils.resource_removed(
            self.cinder_client.backups,
            vol_backup.id,
            wait_iteration_max_time=180,
            stop_after_attempt=15,
            msg="Backup volume")

        # Re-check ceph cinder pool object count and disk usage
        logging.info('Checking ceph cinder pool samples '
                     'after volume create...')
        pool_name, obj_count, kb_used = ceph_utils.get_ceph_pool_sample(
            unit_name, cinder_ceph_pool, self.model_name)

        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        vols = self.cinder_client.volumes.list()
        try:
            cinder_vols = [v for v in vols if v.name == cinder_vol_name]
        except AttributeError:
            cinder_vols = [v for v in vols if
                           v.display_name == cinder_vol_name]
        if not cinder_vols:
            # NOTE(hopem): it appears that at some point cinder-backup stopped
            # restoring volume metadata properly so revert to default name if
            # original is not found
            name = "restore_backup_{}".format(vol_backup.id)
            try:
                cinder_vols = [v for v in vols if v.name == name]
            except AttributeError:
                cinder_vols = [v for v in vols if v.display_name == name]

        self.assertTrue(cinder_vols)

        cinder_vol = cinder_vols[0]

        # Delete restored cinder volume
        openstack_utils.delete_volume(self.cinder_client, cinder_vol.id)
        openstack_utils.resource_removed(
            self.cinder_client.volumes,
            cinder_vol.id,
            wait_iteration_max_time=180,
            stop_after_attempt=15,
            msg="Volume")

        @tenacity.retry(wait=tenacity.wait_exponential(multiplier=10, max=300),
                        reraise=True, stop=tenacity.stop_after_attempt(10),
                        retry=tenacity.retry_if_exception_type(AssertionError))
        def _check_get_ceph_pool_sample(obj_count_samples, pool_size_samples):
            pool_name, obj_count, kb_used = ceph_utils.get_ceph_pool_sample(
                unit_name, cinder_ceph_pool, self.model_name)

            _obj_count_samples = copy.deepcopy(obj_count_samples)
            _pool_size_samples = copy.deepcopy(pool_size_samples)
            _obj_count_samples.append(obj_count)
            _pool_size_samples.append(kb_used)
            # Validate ceph cinder pool object count samples over time
            original, created, deleted = range(3)
            self.assertFalse(_obj_count_samples[created] <=
                             _obj_count_samples[original])
            self.assertFalse(_obj_count_samples[deleted] >=
                             _obj_count_samples[created])

            # Luminous (pike) ceph seems more efficient at disk usage so we
            # cannot guarantee the ordering of kb_used
            if (openstack_utils.get_os_release() <
                    openstack_utils.get_os_release('xenial_mitaka')):
                self.assertFalse(_pool_size_samples[created] <=
                                 _pool_size_samples[original])
                self.assertFalse(_pool_size_samples[deleted] >=
                                 _pool_size_samples[created])

        # Final check, ceph cinder pool object count and disk usage
        logging.info('Checking ceph cinder pool after volume delete...')
        # It sometime takes a short time for removal to be reflected in
        # get_ceph_pool_sample so wrap check in tenacity decorator to retry.
        _check_get_ceph_pool_sample(obj_count_samples, pool_size_samples)
