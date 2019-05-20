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
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class CinderTests(test_utils.OpenStackBaseTest):
    """Encapsulate Cinder tests."""

    RESOURCE_PREFIX = 'zaza-cindertests'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(CinderTests, cls).setUpClass()
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session)

    @classmethod
    def tearDown(cls):
        """Remove test resources."""
        logging.info('Running teardown')
        for snapshot in cls.cinder_client.volume_snapshots.list():
            if snapshot.name.startswith(cls.RESOURCE_PREFIX):
                openstack_utils.delete_resource(
                    cls.cinder_client.volume_snapshots,
                    snapshot.id,
                    msg="snapshot")
        for volume in cls.cinder_client.volumes.list():
            if volume.name.startswith(cls.RESOURCE_PREFIX):
                openstack_utils.delete_resource(
                    cls.cinder_client.volumes,
                    volume.id,
                    msg="volume")

    def test_100_volume_create_extend_delete(self):
        """Test creating, extending a volume."""
        vol_new = self.cinder_client.volumes.create(
            name='{}-100-vol'.format(self.RESOURCE_PREFIX),
            size='1')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
            expected_status="available",
            msg="Volume status wait")
        self.cinder_client.volumes.extend(
            vol_new.id,
            '2')
        openstack_utils.resource_reaches_status(
            self.cinder_client.volumes,
            vol_new.id,
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
            expected_status="available",
            msg="Volume status wait")

        # Snapshot the volume
        snap_new = self.cinder_client.volume_snapshots.create(
            volume_id=vol_new.id,
            name='{}-110-snap'.format(self.RESOURCE_PREFIX))
        openstack_utils.resource_reaches_status(
            self.cinder_client.volume_snapshots,
            snap_new.id,
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
            expected_status="available",
            msg="Volume status wait")
        vol_new.force_delete()
        openstack_utils.resource_removed(
            self.cinder_client.volumes,
            vol_new.id,
            msg="Volume")

    @property
    def services(self):
        """Return a list services for OpenStack release."""
        services = ['cinder-scheduler', 'cinder-volume']
        if (openstack_utils.get_os_release() >=
                openstack_utils.get_os_release('xenial_ocata')):
            services.append('apache2')
        else:
            services.append('cinder-api')
        return services

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change disk format and assert then change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        set_default = {'debug': 'False'}
        set_alternate = {'debug': 'True'}

        # Config file affected by juju set config change
        conf_file = '/etc/cinder/cinder.conf'

        # Make config change, check for service restarts
        logging.debug('Setting disk format glance...')
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            {'DEFAULT': {'debug': ['False']}},
            {'DEFAULT': {'debug': ['True']}},
            self.services)

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        services = ['cinder-scheduler', 'cinder-volume']
        if (openstack_utils.get_os_release() >=
                openstack_utils.get_os_release('xenial_ocata')):
            services.append('apache2')
        else:
            services.append('cinder-api')
        with self.pause_resume(services):
            logging.info("Testing pause resume")
