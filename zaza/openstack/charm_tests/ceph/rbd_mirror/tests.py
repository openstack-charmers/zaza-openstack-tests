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

"""Encapsulate ``ceph-rbd-mirror`` testing."""
import json
import logging
import re

import cinderclient.exceptions as cinder_exceptions

import zaza.openstack.charm_tests.test_utils as test_utils

import zaza.model
import zaza.openstack.utilities.ceph
import zaza.openstack.utilities.openstack as openstack

from zaza.openstack.charm_tests.glance.setup import (
    LTS_IMAGE_NAME,
    CIRROS_IMAGE_NAME)


DEFAULT_CINDER_RBD_MIRRORING_MODE = 'pool'
INTERNAL_POOLS = ('.mgr', 'device_health_metrics')


def get_cinder_rbd_mirroring_mode(cinder_ceph_app_name='cinder-ceph'):
    """Get the RBD mirroring mode for the Cinder Ceph pool.

    :param cinder_ceph_app_name: Cinder Ceph Juju application name.
    :type cinder_ceph_app_name: str
    :returns: A string representing the RBD mirroring mode. It can be
              either 'pool' or 'image'.
    :rtype: str
    """
    rbd_mirroring_mode_config = zaza.model.get_application_config(
        cinder_ceph_app_name).get('rbd-mirroring-mode')
    if rbd_mirroring_mode_config:
        rbd_mirroring_mode = rbd_mirroring_mode_config.get(
            'value', DEFAULT_CINDER_RBD_MIRRORING_MODE).lower()
    else:
        rbd_mirroring_mode = DEFAULT_CINDER_RBD_MIRRORING_MODE

    return rbd_mirroring_mode


def get_glance_image(glance):
    """Get the Glance image object to be used by the Ceph tests.

    It looks for the Cirros Glance image, and it's returned if it's found.
    If the Cirros image is not found, it will try and find the Ubuntu
    LTS image.

    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :returns: Glance image object
    :rtype: glanceclient.image
    """
    images = openstack.get_images_by_name(glance, CIRROS_IMAGE_NAME)
    if images:
        return images[0]
    logging.info("Failed to find {} image, falling back to {}".format(
        CIRROS_IMAGE_NAME,
        LTS_IMAGE_NAME))
    return openstack.get_images_by_name(glance, LTS_IMAGE_NAME)[0]


def setup_cinder_repl_volume_type(cinder, type_name='repl',
                                  backend_name='cinder-ceph'):
    """Set up the Cinder volume replication type.

    :param cinder: Authenticated cinderclient
    :type cinder: cinder.Client
    :param type_name: Cinder volume type name
    :type type_name: str
    :param backend_name: Cinder volume backend name with replication enabled.
    :type backend_name: str
    :returns: Cinder volume type object
    :rtype: cinderclient.VolumeType
    """
    try:
        vol_type = cinder.volume_types.find(name=type_name)
    except cinder_exceptions.NotFound:
        vol_type = cinder.volume_types.create(type_name)

    vol_type.set_keys(metadata={
        'volume_backend_name': backend_name,
        'replication_enabled': '<is> True',
    })
    return vol_type


# TODO: This function should be incorporated into
# 'zaza.openstack.utilities.openstack.create_volume' helper, once the below
# flakiness comments are addressed.
def create_cinder_volume(cinder, name='zaza', image_id=None, type_id=None):
    """Create a new Cinder volume.

    :param cinder: Authenticated cinderclient.
    :type cinder: cinder.Client
    :param name: Volume name.
    :type name: str
    :param image_id: Glance image id, if the volume is created from image.
    :type image_id: str
    :param type_id: Cinder Volume type id, if the volume needs to use an
                    explicit volume type.
    :type type_id: boolean
    :returns: Cinder volume
    :rtype: :class:`Volume`.
    """
    # NOTE(fnordahl): for some reason create volume from image often fails
    # when run just after deployment is finished.  We should figure out
    # why, resolve the underlying issue and then remove this.
    #
    # We do not use tenacity here as it will interfere with tenacity used
    # in ``resource_reaches_status``
    def create_volume(cinder, volume_params, retry=20):
        if retry < 1:
            return
        volume = cinder.volumes.create(**volume_params)
        try:
            # Note(coreycb): stop_after_attempt is increased because using
            # juju storage for ceph-osd backed by cinder on undercloud
            # takes longer than the prior method of directory-backed OSD
            # devices.
            openstack.resource_reaches_status(
                cinder.volumes, volume.id, msg='volume',
                stop_after_attempt=20)
            return volume
        except AssertionError:
            logging.info('retrying')
            volume.delete()
            return create_volume(cinder, volume_params, retry=retry - 1)

    volume_params = {
        'size': 8,
        'name': name,
    }
    if image_id:
        volume_params['imageRef'] = image_id
    if type_id:
        volume_params['volume_type'] = type_id

    return create_volume(cinder, volume_params)


def remove_internal_pools(pools):
    """Exclude the internal pools from the passed dict."""
    for pool in INTERNAL_POOLS:
        pools.pop(pool, None)


class CephRBDMirrorBase(test_utils.OpenStackBaseTest):
    """Base class for ``ceph-rbd-mirror`` tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for ``ceph-rbd-mirror`` tests."""
        super().setUpClass()
        cls.cinder_ceph_app_name = 'cinder-ceph'
        cls.test_cinder_volume_name = 'test-cinder-ceph-volume'
        # get ready for multi-model Zaza
        cls.site_a_model = cls.site_b_model = zaza.model.get_juju_model()
        cls.site_b_app_suffix = '-b'

    def run_status_action(self, application_name=None, model_name=None,
                          pools=[]):
        """Run status action, decode and return response."""
        action_params = {
            'verbose': True,
            'format': 'json',
        }
        if len(pools) > 0:
            action_params['pools'] = ','.join(pools)
        result = zaza.model.run_action_on_leader(
            application_name or self.application_name,
            'status',
            model_name=model_name,
            action_params=action_params)
        return json.loads(result.results['output'])

    def get_pools(self, include_internal_pools=False):
        """Retrieve list of pools from both sites.

        :returns: Tuple with list of pools on each side.
        :rtype: tuple
        """
        site_a_pools = zaza.openstack.utilities.ceph.get_ceph_pools(
            zaza.model.get_lead_unit_name(
                'ceph-mon', model_name=self.site_a_model),
            model_name=self.site_a_model)
        site_b_pools = zaza.openstack.utilities.ceph.get_ceph_pools(
            zaza.model.get_lead_unit_name(
                'ceph-mon' + self.site_b_app_suffix,
                model_name=self.site_b_model),
            model_name=self.site_b_model)
        if not include_internal_pools:
            remove_internal_pools(site_a_pools)
            remove_internal_pools(site_b_pools)
        return sorted(site_a_pools.keys()), sorted(site_b_pools.keys())

    def get_failover_pools(self, **kwargs):
        """Get the failover Ceph pools' names, from both sites.

        If the Cinder RBD mirroring mode is 'image', the 'cinder-ceph' pool
        needs to be excluded, since Cinder orchestrates the failover then.

        :returns: Tuple with site-a pools and site-b pools.
        :rtype: Tuple[List[str], List[str]]
        """
        site_a_pools, site_b_pools = self.get_pools(**kwargs)
        if get_cinder_rbd_mirroring_mode(self.cinder_ceph_app_name) == 'image':
            site_a_pools.remove(self.cinder_ceph_app_name)
            site_b_pools.remove(self.cinder_ceph_app_name)
        return site_a_pools, site_b_pools

    def wait_for_mirror_state(self, state, application_name=None,
                              model_name=None,
                              check_entries_behind_master=False,
                              require_images_in=[],
                              pools=[]):
        """Wait until all images reach requested state.

        This function runs the ``status`` action and examines the data it
        returns.

        :param state: State to expect all images to be in
        :type state: str
        :param application_name: Application to run action on
        :type application_name: str
        :param model_name: Model to run in
        :type model_name: str
        :param check_entries_behind_master: Wait for ``entries_behind_master``
                                            to become '0'.  Only makes sense
                                            when used with state
                                            ``up+replying``.
        :type check_entries_behind_master: bool
        :param require_images_in: List of pools to require images in
        :type require_images_in: list of str
        :param pools: List of pools to run status on. If this is empty, the
                      status action will run on all the pools.
        :type pools: list of str
        :returns: True on success, never returns on failure
        """
        rep = re.compile(r'.*entries_behind_master=(\d+)')
        while True:
            try:
                # encapsulate in try except to work around LP: #1820976
                pool_status = self.run_status_action(
                    application_name=application_name, model_name=model_name,
                    pools=pools)
            except KeyError:
                continue
            for pool, status in pool_status.items():
                images = status.get('images', [])
                if not len(images) and pool in require_images_in:
                    break
                for image in images:
                    if image['state'] and image['state'] != state:
                        break
                    if check_entries_behind_master:
                        m = rep.match(image['description'])
                        # NOTE(fnordahl): Tactical fix for upstream Ceph
                        # Luminous bug https://tracker.ceph.com/issues/23516
                        if m and int(m.group(1)) > 42:
                            logging.info('entries_behind_master={}'
                                         .format(m.group(1)))
                            break
                else:
                    # not found here, check next pool
                    continue
                # found here, pass on to outer loop
                break
            else:
                # all images with state has expected state
                return True

    def setup_test_cinder_volume(self):
        """Set up the test Cinder volume into the Ceph RBD mirror environment.

        If the volume already exists, then it's returned.

        Also, if the Cinder RBD mirroring mode is 'image', the volume will
        use an explicit volume type with the appropriate replication flags.
        Otherwise, it is just a simple Cinder volume using the default backend.

        :returns: Cinder volume
        :rtype: :class:`Volume`.
        """
        session = openstack.get_overcloud_keystone_session()
        cinder = openstack.get_cinder_session_client(session, version=3)

        try:
            return cinder.volumes.find(name=self.test_cinder_volume_name)
        except cinder_exceptions.NotFound:
            logging.info("Test Cinder volume doesn't exist. Creating it")

        glance = openstack.get_glance_session_client(session)
        image = get_glance_image(glance)
        kwargs = {
            'cinder': cinder,
            'name': self.test_cinder_volume_name,
            'image_id': image.id,
        }
        if get_cinder_rbd_mirroring_mode(self.cinder_ceph_app_name) == 'image':
            volume_type = setup_cinder_repl_volume_type(
                cinder,
                backend_name=self.cinder_ceph_app_name)
            kwargs['type_id'] = volume_type.id

        return create_cinder_volume(**kwargs)


class CephRBDMirrorTest(CephRBDMirrorBase):
    """Encapsulate ``ceph-rbd-mirror`` tests."""

    def test_pause_resume(self):
        """Run pause and resume tests."""
        self.pause_resume(['rbd-mirror'])

    def test_pool_broker_synced(self):
        """Validate that pools created with broker protocol are synced.

        The functional test bundle includes the ``cinder``, ``cinder-ceph`` and
        ``glance`` charms.  The ``cinder-ceph`` and ``glance`` charms will
        create pools using the ceph charms broker protocol at deploy time.
        """
        site_a_pools, site_b_pools = self.get_pools()
        self.assertEqual(site_a_pools, site_b_pools)

    def test_pool_manual_synced(self):
        """Validate that manually created pools are synced after refresh.

        The ``ceph-rbd-mirror`` charm does not get notified when the operator
        creates a pool manually without using the ceph charms broker protocol.

        To alleviate this the charm has a ``refresh-pools`` action the operator
        can call to have it discover such pools.  Validate its operation.
        """
        # use action on ceph-mon to create a pool directly in the Ceph cluster
        # without using the broker protocol
        zaza.model.run_action_on_leader(
            'ceph-mon',
            'create-pool',
            model_name=self.site_a_model,
            action_params={
                'name': 'zaza',
                'app-name': 'rbd',
            })
        # tell ceph-rbd-mirror unit on site_a to refresh list of pools
        zaza.model.run_action_on_leader(
            'ceph-rbd-mirror',
            'refresh-pools',
            model_name=self.site_a_model,
            action_params={
            })
        # wait for execution to start
        zaza.model.wait_for_agent_status(model_name=self.site_a_model)
        zaza.model.wait_for_agent_status(model_name=self.site_b_model)
        # wait for execution to finish
        zaza.model.wait_for_application_states(model_name=self.site_a_model)
        zaza.model.wait_for_application_states(model_name=self.site_b_model)
        # make sure everything is idle before we test
        zaza.model.block_until_all_units_idle(model_name=self.site_a_model)
        zaza.model.block_until_all_units_idle(model_name=self.site_b_model)
        # validate result
        site_a_pools, site_b_pools = self.get_pools()
        self.assertEqual(site_a_pools, site_b_pools)

    def test_cinder_volume_mirrored(self):
        """Validate that a volume created through Cinder is mirrored.

        For RBD Mirroring to work clients must enable the correct set of
        features when creating images.

        The RBD image feature settings are announced by the ``ceph-mon`` charm
        over the client relation when it has units related on its
        ``rbd-mirror`` endpoint.

        By creating a volume through cinder on site A, checking for presence on
        site B and subsequently comparing the contents we get a full end to end
        test.
        """
        volume = self.setup_test_cinder_volume()
        site_a_hash = zaza.openstack.utilities.ceph.get_rbd_hash(
            zaza.model.get_lead_unit_name('ceph-mon',
                                          model_name=self.site_a_model),
            'cinder-ceph',
            'volume-{}'.format(volume.id),
            model_name=self.site_a_model)
        self.wait_for_mirror_state(
            'up+replaying',
            check_entries_behind_master=True,
            application_name=self.application_name + self.site_b_app_suffix,
            model_name=self.site_b_model)
        logging.info('Checking the Ceph RBD hashes of the primary and '
                     'the secondary Ceph images')
        site_b_hash = zaza.openstack.utilities.ceph.get_rbd_hash(
            zaza.model.get_lead_unit_name('ceph-mon' + self.site_b_app_suffix,
                                          model_name=self.site_b_model),
            'cinder-ceph',
            'volume-{}'.format(volume.id),
            model_name=self.site_b_model)
        logging.info(site_a_hash)
        logging.info(site_b_hash)
        self.assertEqual(site_a_hash, site_b_hash)


class CephRBDMirrorControlledFailoverTest(CephRBDMirrorBase):
    """Encapsulate ``ceph-rbd-mirror`` controlled failover tests."""

    def execute_failover_juju_actions(self,
                                      primary_site_app_name,
                                      primary_site_model,
                                      primary_site_pools,
                                      secondary_site_app_name,
                                      secondary_site_model,
                                      secondary_site_pools):
        """Execute the failover Juju actions.

        The failover / failback via Juju actions shares the same workflow. The
        failback is just a failover with sites in reversed order.

        This function encapsulates the tasks to failover a primary site to
        a secondary site:
        1. Demote primary site
        2. Validation of the primary site demotion
        3. Promote secondary site
        4. Validation of the secondary site promotion

        :param primary_site_app_name: Primary site Ceph RBD mirror app name.
        :type primary_site_app_name: str
        :param primary_site_model: Primary site Juju model name.
        :type primary_site_model: str
        :param primary_site_pools: Primary site pools.
        :type primary_site_pools: List[str]
        :param secondary_site_app_name: Secondary site Ceph RBD mirror
                                        app name.
        :type secondary_site_app_name: str
        :param secondary_site_model: Secondary site Juju model name.
        :type secondary_site_model: str
        :param secondary_site_pools: Secondary site pools.
        :type secondary_site_pools: List[str]
        """
        # Check if primary and secondary pools sizes are the same.
        self.assertEqual(len(primary_site_pools), len(secondary_site_pools))

        # Run the 'demote' Juju action against the primary site pools.
        logging.info('Demoting {} from model {}.'.format(
            primary_site_app_name, primary_site_model))
        result = zaza.model.run_action_on_leader(
            primary_site_app_name,
            'demote',
            model_name=primary_site_model,
            action_params={
                'pools': ','.join(primary_site_pools)
            })
        logging.info(result.results)
        self.assertEqual(int(result.results['Code']), 0)

        # Validate that the demoted pools count matches the total primary site
        # pools count.
        n_pools_demoted = len(result.results['output'].split('\n'))
        self.assertEqual(len(primary_site_pools), n_pools_demoted)

        # At this point, both primary and secondary sites are demoted. Validate
        # that the Ceph images, from both sites, report 'up+unknown', since
        # there isn't a primary site at the moment.
        logging.info('Waiting until {} is demoted.'.format(
            primary_site_app_name))
        self.wait_for_mirror_state(
            'up+unknown',
            application_name=primary_site_app_name,
            model_name=primary_site_model,
            pools=primary_site_pools)
        self.wait_for_mirror_state(
            'up+unknown',
            application_name=secondary_site_app_name,
            model_name=secondary_site_model,
            pools=secondary_site_pools)

        # Run the 'promote' Juju against the secondary site.
        logging.info('Promoting {} from model {}.'.format(
            secondary_site_app_name, secondary_site_model))
        result = zaza.model.run_action_on_leader(
            secondary_site_app_name,
            'promote',
            model_name=secondary_site_model,
            action_params={
                'pools': ','.join(secondary_site_pools)
            })
        logging.info(result.results)
        self.assertEqual(int(result.results['Code']), 0)

        # Validate that the promoted pools count matches the total secondary
        # site pools count.
        n_pools_promoted = len(result.results['output'].split('\n'))
        self.assertEqual(len(secondary_site_pools), n_pools_promoted)

        # Validate that the Ceph images from the newly promoted site
        # report 'up+stopped' state (which is reported by primary Ceph images).
        logging.info('Waiting until {} is promoted.'.format(
            secondary_site_app_name))
        self.wait_for_mirror_state(
            'up+stopped',
            application_name=secondary_site_app_name,
            model_name=secondary_site_model,
            pools=secondary_site_pools)

        # Validate that the Ceph images from site-a report 'up+replaying'
        # (which is reported by secondary Ceph images).
        self.wait_for_mirror_state(
            'up+replaying',
            check_entries_behind_master=True,
            application_name=primary_site_app_name,
            model_name=primary_site_model,
            pools=primary_site_pools)

    def test_100_cinder_failover(self):
        """Validate controlled failover via the Cinder API.

        This test only makes sense if Cinder RBD mirroring mode is 'image'.
        It will return early, if this is not the case.
        """
        cinder_rbd_mirroring_mode = get_cinder_rbd_mirroring_mode(
            self.cinder_ceph_app_name)
        if cinder_rbd_mirroring_mode != 'image':
            logging.warning(
                "Skipping 'test_100_cinder_failover' since Cinder RBD "
                "mirroring mode is {}.".format(cinder_rbd_mirroring_mode))
            return

        session = openstack.get_overcloud_keystone_session()
        cinder = openstack.get_cinder_session_client(session, version=3)

        # Check if the Cinder volume host is available with replication
        # enabled.
        host = 'cinder@{}'.format(self.cinder_ceph_app_name)
        svc = cinder.services.list(host=host, binary='cinder-volume')[0]
        self.assertEqual(svc.replication_status, 'enabled')
        self.assertEqual(svc.status, 'enabled')

        # Setup the test Cinder volume
        volume = self.setup_test_cinder_volume()

        # Check if the volume is properly mirrored
        self.wait_for_mirror_state(
            'up+replaying',
            check_entries_behind_master=True,
            application_name=self.application_name + self.site_b_app_suffix,
            model_name=self.site_b_model,
            pools=[self.cinder_ceph_app_name])

        # Execute the Cinder volume failover
        openstack.failover_cinder_volume_host(
            cinder=cinder,
            backend_name=self.cinder_ceph_app_name,
            target_backend_id='ceph',
            target_status='disabled',
            target_replication_status='failed-over')

        # Check if the test volume is still available after failover
        self.assertEqual(cinder.volumes.get(volume.id).status, 'available')

    def test_101_cinder_failback(self):
        """Validate controlled failback via the Cinder API.

        This test only makes sense if Cinder RBD mirroring mode is 'image'.
        It will return early, if this is not the case.

        The test needs to be executed when the Cinder volume host is already
        failed-over with the test volume on it.
        """
        cinder_rbd_mirroring_mode = get_cinder_rbd_mirroring_mode(
            self.cinder_ceph_app_name)
        if cinder_rbd_mirroring_mode != 'image':
            logging.warning(
                "Skipping 'test_101_cinder_failback' since Cinder RBD "
                "mirroring mode is {}.".format(cinder_rbd_mirroring_mode))
            return

        session = openstack.get_overcloud_keystone_session()
        cinder = openstack.get_cinder_session_client(session, version=3)

        # Check if the Cinder volume host is already failed-over
        host = 'cinder@{}'.format(self.cinder_ceph_app_name)
        svc = cinder.services.list(host=host, binary='cinder-volume')[0]
        self.assertEqual(svc.replication_status, 'failed-over')
        self.assertEqual(svc.status, 'disabled')

        # Check if the test Cinder volume is already present. The method
        # 'cinder.volumes.find' raises 404 if the volume is not found.
        volume = cinder.volumes.find(name=self.test_cinder_volume_name)

        # Execute the Cinder volume failback
        openstack.failover_cinder_volume_host(
            cinder=cinder,
            backend_name=self.cinder_ceph_app_name,
            target_backend_id='default',
            target_status='enabled',
            target_replication_status='enabled')

        # Check if the test volume is still available after failback
        self.assertEqual(cinder.volumes.get(volume.id).status, 'available')

    def test_200_juju_failover(self):
        """Validate controlled failover via Juju actions."""
        # Get the Ceph pools needed to failover
        site_a_pools, site_b_pools = self.get_failover_pools()

        # Execute the failover Juju actions with the appropriate parameters.
        site_b_app_name = self.application_name + self.site_b_app_suffix
        self.execute_failover_juju_actions(
            primary_site_app_name=self.application_name,
            primary_site_model=self.site_a_model,
            primary_site_pools=site_a_pools,
            secondary_site_app_name=site_b_app_name,
            secondary_site_model=self.site_b_model,
            secondary_site_pools=site_b_pools)

    def test_201_juju_failback(self):
        """Validate controlled failback via Juju actions."""
        # Get the Ceph pools needed to failback
        site_a_pools, site_b_pools = self.get_failover_pools()

        # Execute the failover Juju actions with the appropriate parameters.
        # The failback operation is just a failover with sites in reverse
        # order.
        site_b_app_name = self.application_name + self.site_b_app_suffix
        self.execute_failover_juju_actions(
            primary_site_app_name=site_b_app_name,
            primary_site_model=self.site_b_model,
            primary_site_pools=site_b_pools,
            secondary_site_app_name=self.application_name,
            secondary_site_model=self.site_a_model,
            secondary_site_pools=site_a_pools)

    def test_203_juju_resync(self):
        """Validate the 'resync-pools' Juju action.

        The 'resync-pools' Juju action is meant to flag Ceph images from the
        secondary site to re-sync against the Ceph images from the primary
        site.

        This use case is useful when the Ceph secondary images are out of sync.
        """
        # Get the Ceph pools needed to failback
        _, site_b_pools = self.get_failover_pools()

        # Run the 'resync-pools' Juju action against the pools from site-b.
        # This will make sure that the Ceph images from site-b are properly
        # synced with the primary images from site-a.
        site_b_app_name = self.application_name + self.site_b_app_suffix
        logging.info('Re-syncing {} from model {}'.format(
            site_b_app_name, self.site_b_model))
        result = zaza.model.run_action_on_leader(
            site_b_app_name,
            'resync-pools',
            model_name=self.site_b_model,
            action_params={
                'pools': ','.join(site_b_pools),
                'i-really-mean-it': True,
            })
        logging.info(result.results)
        self.assertEqual(int(result.results['Code']), 0)

        # Validate that the Ceph images from site-b report 'up+replaying'
        # (which is reported by secondary Ceph images). And check that images
        # exist in Cinder and Glance pools.
        if result.results['output']:
            # Depending on timing, there may be no images that were resynced.
            # As such, only run the following check when there are images,
            # to avoid going into an infinite loop.
            self.wait_for_mirror_state(
                'up+replaying',
                check_entries_behind_master=True,
                application_name=site_b_app_name,
                model_name=self.site_b_model,
                require_images_in=[self.cinder_ceph_app_name, 'glance'],
                pools=site_b_pools)


class CephRBDMirrorDisasterFailoverTest(CephRBDMirrorBase):
    """Encapsulate ``ceph-rbd-mirror`` destructive tests."""

    def apply_cinder_ceph_workaround(self):
        """Set minimal timeouts / retries to the Cinder Ceph backend.

        This is needed because the failover via Cinder API will try to do a
        demotion of the site-a. However, when site-a is down, and with the
        default timeouts / retries, the operation takes an unreasonably amount
        of time (or sometimes it never finishes).
        """
        # These new config options need to be set under the Cinder Ceph backend
        # section in the main Cinder config file.
        # At the moment, we don't the possibility of using Juju config to set
        # these options. And also, it's not even a good practice to have them
        # in production.
        # These should be set only to do the Ceph failover via Cinder API, and
        # they need to be removed after.
        configs = {
            'rados_connect_timeout': '1',
            'rados_connection_retries': '1',
            'rados_connection_interval': '0',
            'replication_connect_timeout': '1',
        }

        # Small Python script that will be executed via Juju run to update
        # the Cinder config file.
        update_cinder_conf_script = (
            "import configparser; "
            "config = configparser.ConfigParser(); "
            "config.read('/etc/cinder/cinder.conf'); "
            "{}"
            "f = open('/etc/cinder/cinder.conf', 'w'); "
            "config.write(f); "
            "f.close()")
        set_cmd = ''
        for cfg_name in configs:
            set_cmd += "config.set('{0}', '{1}', '{2}'); ".format(
                self.cinder_ceph_app_name, cfg_name, configs[cfg_name])
        script = update_cinder_conf_script.format(set_cmd)

        # Run the workaround script via Juju run
        zaza.model.run_on_leader(
            self.cinder_ceph_app_name,
            'python3 -c "{}"; systemctl restart cinder-volume'.format(script))

    def kill_primary_site(self):
        """Simulate an unexpected primary site shutdown."""
        logging.info('Killing the Ceph primary site')
        for application in ['ceph-rbd-mirror', 'ceph-mon', 'ceph-osd']:
            zaza.model.remove_application(
                application,
                model_name=self.site_a_model,
                forcefully_remove_machines=True)

    def test_100_forced_juju_failover(self):
        """Validate Ceph failover via Juju when the primary site is down.

        * Kill the primary site
        * Execute the forced failover via Juju actions
        """
        # Get the site-b Ceph pools that need to be promoted
        _, site_b_pools = self.get_failover_pools(include_internal_pools=True)
        site_b_app_name = self.application_name + self.site_b_app_suffix

        # Simulate primary site unexpected shutdown
        self.kill_primary_site()

        # Try and promote the site-b to primary.
        result = zaza.model.run_action_on_leader(
            site_b_app_name,
            'promote',
            model_name=self.site_b_model,
            action_params={
                'pools': ','.join(site_b_pools),
            })
        self.assertEqual(int(result.results['Code']), 0)

        # The site-b 'promote' Juju action is expected to fail, because the
        # primary site is down.
        self.assertEqual(result.status, 'failed')

        # Retry to promote site-b using the 'force' Juju action parameter.
        result = zaza.model.run_action_on_leader(
            site_b_app_name,
            'promote',
            model_name=self.site_b_model,
            action_params={
                'force': True,
                'pools': ','.join(pool for pool in site_b_pools
                                  if pool not in INTERNAL_POOLS)
            })
        self.assertEqual(int(result.results['Code']), 0)

        # Validate successful Juju action execution
        self.assertEqual(result.status, 'completed')

    def test_200_forced_cinder_failover(self):
        """Validate Ceph failover via Cinder when the primary site is down.

        This test only makes sense if Cinder RBD mirroring mode is 'image'.
        It will return early, if this is not the case.

        This assumes that the primary site is already killed.
        """
        cinder_rbd_mirroring_mode = get_cinder_rbd_mirroring_mode(
            self.cinder_ceph_app_name)
        if cinder_rbd_mirroring_mode != 'image':
            logging.warning(
                "Skipping 'test_200_cinder_failover_without_primary_site' "
                "since Cinder RBD mirroring mode is {}.".format(
                    cinder_rbd_mirroring_mode))
            return

        # Make sure that the Cinder Ceph backend workaround is applied.
        self.apply_cinder_ceph_workaround()

        session = openstack.get_overcloud_keystone_session()
        cinder = openstack.get_cinder_session_client(session, version=3)
        openstack.failover_cinder_volume_host(
            cinder=cinder,
            backend_name=self.cinder_ceph_app_name,
            target_backend_id='ceph',
            target_status='disabled',
            target_replication_status='failed-over')

        # Check that the Cinder volumes are still available after forced
        # failover.
        for volume in cinder.volumes.list():
            self.assertEqual(volume.status, 'available')
