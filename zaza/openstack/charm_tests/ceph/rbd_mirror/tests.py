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
import time

import cinderclient.exceptions as cinder_exceptions

import zaza.openstack.charm_tests.test_utils as test_utils

import zaza.model
import zaza.openstack.utilities.ceph
import zaza.openstack.utilities.openstack as openstack

from zaza.openstack.charm_tests.glance.setup import (
    LTS_IMAGE_NAME,
    CIRROS_IMAGE_NAME)


class CephRBDMirrorBase(test_utils.OpenStackBaseTest):
    """Base class for ``ceph-rbd-mirror`` tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for ``ceph-rbd-mirror`` tests."""
        super().setUpClass()
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

    def get_pools(self):
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
        return sorted(site_a_pools.keys()), sorted(site_b_pools.keys())

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

    def get_cinder_rbd_mirroring_mode(self,
                                      cinder_ceph_app_name='cinder-ceph'):
        """Get the RBD mirroring mode for the Cinder Ceph pool.

        :returns: A string representing the RBD mirroring mode. It can be
                  either 'pool' or 'image'.
        """
        DEFAULT_RBD_MIRRORING_MODE = 'pool'

        rbd_mirroring_mode_config = zaza.model.get_application_config(
            cinder_ceph_app_name).get('rbd-mirroring-mode')
        if rbd_mirroring_mode_config:
            rbd_mirroring_mode = rbd_mirroring_mode_config.get(
                'value', DEFAULT_RBD_MIRRORING_MODE).lower()
        else:
            rbd_mirroring_mode = DEFAULT_RBD_MIRRORING_MODE

        return rbd_mirroring_mode

    def create_cinder_volume(self, session, from_image=False):
        """Create Cinder Volume from image.

        :rtype: :class:`Volume`.
        """
        def get_glance_image(session):
            glance = openstack.get_glance_session_client(session)
            images = openstack.get_images_by_name(glance, CIRROS_IMAGE_NAME)
            if images:
                return images[0]
            logging.info("Failed to find {} image, falling back to {}".format(
                CIRROS_IMAGE_NAME,
                LTS_IMAGE_NAME))
            return openstack.get_images_by_name(glance, LTS_IMAGE_NAME)[0]

        def create_volume_type(cinder):
            try:
                vol_type = cinder.volume_types.find(name='repl')
            except cinder_exceptions.NotFound:
                vol_type = cinder.volume_types.create('repl')
                vol_type.set_keys(metadata={
                    'volume_backend_name': 'cinder-ceph',
                    'replication_enabled': '<is> True',
                })
            return vol_type

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
            'name': 'zaza',
        }
        if from_image:
            volume_params['imageRef'] = get_glance_image(session).id
        cinder = openstack.get_cinder_session_client(session)
        if self.get_cinder_rbd_mirroring_mode() == 'image':
            volume_params['volume_type'] = create_volume_type(cinder).id

        return create_volume(cinder, volume_params)

    def failover_cinder_volume_host(self, cinder_client,
                                    backend_name='cinder-ceph',
                                    target_backend_id='ceph',
                                    target_status='disabled',
                                    target_replication_status='failed-over',
                                    timeout=300):
        """Failover Cinder volume host."""
        host = 'cinder@{}'.format(backend_name)
        logging.info(
            'Failover Cinder host %s to backend_id %s',
            host, target_backend_id)
        cinder_client.services.failover_host(
            host=host,
            backend_id=target_backend_id)
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise cinder_exceptions.TimeoutException(
                    obj=cinder_client.services,
                    action='failover_host')
            service = cinder_client.services.list(
                host=host,
                binary='cinder-volume')[0]
            if (service.status == target_status and
                    service.replication_status == target_replication_status):
                break
            time.sleep(5)
        logging.info(
            'Successfully failed-over Cinder host %s to backend_id %s',
            host, target_backend_id)


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
        session = openstack.get_overcloud_keystone_session()
        volume = self.create_cinder_volume(session, from_image=True)
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

    def cinder_fail_over_fall_back(self):
        """Validate controlled fail over and fall back via the Cinder API."""
        session = openstack.get_overcloud_keystone_session()
        cinder = openstack.get_cinder_session_client(session)
        volume = self.create_cinder_volume(session, from_image=True)
        self.wait_for_mirror_state(
            'up+replaying',
            check_entries_behind_master=True,
            application_name=self.application_name + self.site_b_app_suffix,
            model_name=self.site_b_model,
            pools=['cinder-ceph'])
        self.failover_cinder_volume_host(
            cinder_client=cinder)
        self.assertEqual(cinder.volumes.get(volume.id).status, 'available')
        self.failover_cinder_volume_host(
            cinder_client=cinder,
            target_backend_id='default',
            target_status='enabled',
            target_replication_status='enabled')
        self.assertEqual(cinder.volumes.get(volume.id).status, 'available')

    def test_fail_over_fall_back(self):
        """Validate controlled fail over and fall back."""
        site_a_pools, site_b_pools = self.get_pools()
        site_a_action_params = {}
        site_b_action_params = {}
        if self.get_cinder_rbd_mirroring_mode() == 'image':
            site_a_pools.remove('cinder-ceph')
            site_a_action_params['pools'] = ','.join(site_a_pools)
            site_b_pools.remove('cinder-ceph')
            site_b_action_params['pools'] = ','.join(site_b_pools)
        result = zaza.model.run_action_on_leader(
            'ceph-rbd-mirror',
            'demote',
            model_name=self.site_a_model,
            action_params=site_a_action_params)
        logging.info(result.results)
        n_pools_demoted = len(result.results['output'].split('\n'))
        self.assertEqual(len(site_a_pools), n_pools_demoted)
        self.wait_for_mirror_state(
            'up+unknown',
            model_name=self.site_a_model,
            pools=site_a_pools)
        self.wait_for_mirror_state(
            'up+unknown',
            application_name=self.application_name + self.site_b_app_suffix,
            model_name=self.site_b_model,
            pools=site_b_pools)
        result = zaza.model.run_action_on_leader(
            'ceph-rbd-mirror' + self.site_b_app_suffix,
            'promote',
            model_name=self.site_b_model,
            action_params=site_b_action_params)
        logging.info(result.results)
        n_pools_promoted = len(result.results['output'].split('\n'))
        self.assertEqual(len(site_b_pools), n_pools_promoted)
        self.wait_for_mirror_state(
            'up+replaying',
            model_name=self.site_a_model,
            pools=site_a_pools)
        self.wait_for_mirror_state(
            'up+stopped',
            application_name=self.application_name + self.site_b_app_suffix,
            model_name=self.site_b_model,
            pools=site_b_pools)
        result = zaza.model.run_action_on_leader(
            'ceph-rbd-mirror' + self.site_b_app_suffix,
            'demote',
            model_name=self.site_b_model,
            action_params=site_b_action_params)
        logging.info(result.results)
        n_pools_demoted = len(result.results['output'].split('\n'))
        self.assertEqual(len(site_a_pools), n_pools_demoted)
        self.wait_for_mirror_state(
            'up+unknown',
            model_name=self.site_a_model,
            pools=site_a_pools)
        self.wait_for_mirror_state(
            'up+unknown',
            application_name=self.application_name + self.site_b_app_suffix,
            model_name=self.site_b_model,
            pools=site_b_pools)
        result = zaza.model.run_action_on_leader(
            'ceph-rbd-mirror',
            'promote',
            model_name=self.site_a_model,
            action_params=site_a_action_params)
        logging.info(result.results)
        n_pools_promoted = len(result.results['output'].split('\n'))
        self.assertEqual(len(site_b_pools), n_pools_promoted)
        self.wait_for_mirror_state(
            'up+stopped',
            model_name=self.site_a_model,
            pools=site_a_pools)
        action_params = {
            'i-really-mean-it': True,
        }
        if self.get_cinder_rbd_mirroring_mode() == 'image':
            action_params['pools'] = site_b_action_params['pools']
        result = zaza.model.run_action_on_leader(
            'ceph-rbd-mirror' + self.site_b_app_suffix,
            'resync-pools',
            model_name=self.site_b_model,
            action_params=action_params)
        logging.info(result.results)
        self.wait_for_mirror_state(
            'up+replaying',
            application_name=self.application_name + self.site_b_app_suffix,
            model_name=self.site_b_model,
            require_images_in=['cinder-ceph', 'glance'],
            pools=site_a_pools)
        if self.get_cinder_rbd_mirroring_mode() == 'image':
            self.cinder_fail_over_fall_back()


class CephRBDMirrorDisasterFailoverTest(CephRBDMirrorBase):
    """Encapsulate ``ceph-rbd-mirror`` destructive tests."""

    def forced_failover_cinder_volume_host(self, cinder_client):
        """Validate forced Cinder volume host fail over."""
        def apply_cinder_workaround():
            """Set minimal timeouts / retries to the Cinder Ceph backend.

            This is needed because the failover via Cinder will try to do a
            demotion of the site-a, and with the default timeouts / retries,
            the operation takes an unreasonably amount of time.
            """
            cinder_configs = {
                'rados_connect_timeout': '1',
                'rados_connection_retries': '1',
                'rados_connection_interval': '0',
                'replication_connect_timeout': '1',
            }
            update_cinder_conf_cmd = (
                "import configparser; "
                "config = configparser.ConfigParser(); "
                "config.read('/etc/cinder/cinder.conf'); "
                "{}"
                "f = open('/etc/cinder/cinder.conf', 'w'); "
                "config.write(f); "
                "f.close()")
            cmd = ''
            for config in cinder_configs:
                cmd += "config.set('cinder-ceph', '{0}', '{1}'); ".format(
                    config, cinder_configs[config])
            cmd = update_cinder_conf_cmd.format(cmd)
            zaza.model.run_on_leader(
                'cinder-ceph',
                'python3 -c "{}"; systemctl restart cinder-volume'.format(cmd))

        apply_cinder_workaround()
        self.failover_cinder_volume_host(cinder_client)

        for volume in cinder_client.volumes.list():
            self.assertEqual(volume.status, 'available')

    def test_kill_site_a_fail_over(self):
        """Validate fail over after uncontrolled shutdown of primary."""
        action_params = {}
        if self.get_cinder_rbd_mirroring_mode() == 'image':
            _, site_b_pools = self.get_pools()
            site_b_pools.remove('cinder-ceph')
            action_params['pools'] = ','.join(site_b_pools)

        for application in 'ceph-rbd-mirror', 'ceph-mon', 'ceph-osd':
            zaza.model.remove_application(
                application,
                model_name=self.site_a_model,
                forcefully_remove_machines=True)
        result = zaza.model.run_action_on_leader(
            'ceph-rbd-mirror' + self.site_b_app_suffix,
            'promote',
            model_name=self.site_b_model,
            action_params=action_params)
        self.assertEqual(result.status, 'failed')
        action_params['force'] = True
        result = zaza.model.run_action_on_leader(
            'ceph-rbd-mirror' + self.site_b_app_suffix,
            'promote',
            model_name=self.site_b_model,
            action_params=action_params)
        self.assertEqual(result.status, 'completed')
        if self.get_cinder_rbd_mirroring_mode() == 'image':
            session = openstack.get_overcloud_keystone_session()
            cinder = openstack.get_cinder_session_client(session)
            self.forced_failover_cinder_volume_host(cinder)
