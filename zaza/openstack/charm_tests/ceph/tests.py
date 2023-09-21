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

"""Ceph Testing."""

import unittest
import json
import logging
from os import (
    listdir,
    path
)
import requests
import tempfile

import tenacity

from swiftclient.exceptions import ClientException

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.model as zaza_model
import zaza.openstack.utilities.ceph as zaza_ceph
import zaza.openstack.utilities.exceptions as zaza_exceptions
import zaza.openstack.utilities.generic as zaza_utils
import zaza.utilities.juju as juju_utils
import zaza.openstack.utilities.openstack as zaza_openstack


class CephLowLevelTest(test_utils.OpenStackBaseTest):
    """Ceph Low Level Test Class."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph low level tests."""
        super(CephLowLevelTest, cls).setUpClass()

    def test_processes(self):
        """Verify Ceph processes.

        Verify that the expected service processes are running
        on each ceph unit.
        """
        logging.info('Checking ceph-mon and ceph-osd processes...')
        # Process name and quantity of processes to expect on each unit
        ceph_mon_processes = {
            'ceph-mon': 1,
        }

        ceph_osd_processes = {
            'ceph-osd': [1, 2, 3]
        }

        # Units with process names and PID quantities expected
        expected_processes = {
            'ceph-mon/0': ceph_mon_processes,
            'ceph-mon/1': ceph_mon_processes,
            'ceph-mon/2': ceph_mon_processes,
            'ceph-osd/0': ceph_osd_processes,
            'ceph-osd/1': ceph_osd_processes,
            'ceph-osd/2': ceph_osd_processes
        }

        actual_pids = zaza_utils.get_unit_process_ids(expected_processes)
        ret = zaza_utils.validate_unit_process_ids(expected_processes,
                                                   actual_pids)
        self.assertTrue(ret)

    def test_services(self):
        """Verify the ceph services.

        Verify the expected services are running on the service units.
        """
        logging.info('Checking ceph-osd and ceph-mon services...')
        services = {}
        ceph_services = ['ceph-mon']
        services['ceph-osd/0'] = ['ceph-osd']

        services['ceph-mon/0'] = ceph_services
        services['ceph-mon/1'] = ceph_services
        services['ceph-mon/2'] = ceph_services

        for unit_name, unit_services in services.items():
            zaza_model.block_until_service_status(
                unit_name=unit_name,
                services=unit_services,
                target_status='running'
            )

    @test_utils.skipUntilVersion('ceph-mon', 'ceph', '14.2.0')
    def test_pg_tuning(self):
        """Verify that auto PG tuning is enabled for Nautilus+."""
        unit_name = 'ceph-mon/0'
        cmd = "ceph osd pool autoscale-status --format=json"
        result = zaza_model.run_on_unit(unit_name, cmd)
        self.assertEqual(result['Code'], '0')
        for pool in json.loads(result['Stdout']):
            self.assertEqual(pool['pg_autoscale_mode'], 'on')


class CephRelationTest(test_utils.OpenStackBaseTest):
    """Ceph's relations test class."""

    @classmethod
    def setUpClass(cls):
        """Run the ceph's relations class setup."""
        super(CephRelationTest, cls).setUpClass()

    def test_ceph_osd_ceph_relation_address(self):
        """Verify the ceph-osd to ceph relation data."""
        logging.info('Checking ceph-osd:ceph-mon relation data...')
        unit_name = 'ceph-osd/0'
        remote_unit_name = 'ceph-mon/0'
        relation_name = 'osd'
        remote_unit = zaza_model.get_unit_from_name(remote_unit_name)
        remote_ip = zaza_model.get_unit_public_address(remote_unit)
        relation = juju_utils.get_relation_from_unit(
            unit_name,
            remote_unit_name,
            relation_name
        )
        # Get private-address in relation
        rel_private_ip = relation.get('private-address')
        # The private address in relation should match ceph-mon/0 address
        self.assertEqual(rel_private_ip, remote_ip)

    def _ceph_to_ceph_osd_relation(self, remote_unit_name):
        """Verify the cephX to ceph-osd relation data.

        Helper function to test the relation.
        """
        logging.info('Checking {}:ceph-osd mon relation data...'.
                     format(remote_unit_name))
        unit_name = 'ceph-osd/0'
        relation_name = 'osd'
        remote_unit = zaza_model.get_unit_from_name(remote_unit_name)
        remote_ip = zaza_model.get_unit_public_address(remote_unit)
        cmd = 'leader-get fsid'
        result = zaza_model.run_on_unit(remote_unit_name, cmd)
        fsid = result.get('Stdout').strip()
        expected = {
            'private-address': remote_ip,
            'ceph-public-address': remote_ip,
            'fsid': fsid,
        }
        relation = juju_utils.get_relation_from_unit(
            unit_name,
            remote_unit_name,
            relation_name
        )
        for e_key, e_value in expected.items():
            a_value = relation[e_key]
            self.assertEqual(e_value, a_value)
        self.assertTrue(relation['osd_bootstrap_key'] is not None)

    def test_ceph0_to_ceph_osd_relation(self):
        """Verify the ceph0 to ceph-osd relation data."""
        remote_unit_name = 'ceph-mon/0'
        self._ceph_to_ceph_osd_relation(remote_unit_name)

    def test_ceph1_to_ceph_osd_relation(self):
        """Verify the ceph1 to ceph-osd relation data."""
        remote_unit_name = 'ceph-mon/1'
        self._ceph_to_ceph_osd_relation(remote_unit_name)

    def test_ceph2_to_ceph_osd_relation(self):
        """Verify the ceph2 to ceph-osd relation data."""
        remote_unit_name = 'ceph-mon/2'
        self._ceph_to_ceph_osd_relation(remote_unit_name)


class CephTest(test_utils.OpenStackBaseTest):
    """Ceph common functional tests."""

    @classmethod
    def setUpClass(cls):
        """Run the ceph's common class setup."""
        super(CephTest, cls).setUpClass()

    def osd_out_in(self, services):
        """Run OSD out and OSD in tests.

        Remove OSDs and then add them back in on a unit checking that services
        are in the required state after each action

        :param services: Services expected to be restarted when config_file is
                         changed.
        :type services: list
        """
        zaza_model.block_until_service_status(
            self.lead_unit,
            services,
            'running',
            model_name=self.model_name)
        zaza_model.block_until_unit_wl_status(
            self.lead_unit,
            'active',
            model_name=self.model_name)
        zaza_model.run_action(
            self.lead_unit,
            'osd-out',
            model_name=self.model_name)
        zaza_model.block_until_unit_wl_status(
            self.lead_unit,
            'maintenance',
            model_name=self.model_name)
        zaza_model.block_until_all_units_idle(model_name=self.model_name)
        zaza_model.run_action(
            self.lead_unit,
            'osd-in',
            model_name=self.model_name)
        zaza_model.block_until_unit_wl_status(
            self.lead_unit,
            'active',
            model_name=self.model_name)
        zaza_model.block_until_all_units_idle(model_name=self.model_name)
        zaza_model.block_until_service_status(
            self.lead_unit,
            services,
            'running',
            model_name=self.model_name)

    def test_ceph_check_osd_pools(self):
        """Check OSD pools.

        Check osd pools on all ceph units, expect them to be
        identical, and expect specific pools to be present.
        """
        logging.info('Checking pools on ceph units...')

        expected_pools = zaza_ceph.get_expected_pools()
        results = []
        unit_name = 'ceph-mon/0'

        # Check for presence of expected pools on each unit
        logging.debug('Expected pools: {}'.format(expected_pools))
        pools = zaza_ceph.get_ceph_pools(unit_name)
        results.append(pools)

        for expected_pool in expected_pools:
            if expected_pool not in pools:
                msg = ('{} does not have pool: '
                       '{}'.format(unit_name, expected_pool))
                raise zaza_exceptions.CephPoolNotFound(msg)
        logging.debug('{} has (at least) the expected '
                      'pools.'.format(unit_name))

        # Check that all units returned the same pool name:id data
        for i, result in enumerate(results):
            for other in results[i+1:]:
                logging.debug('result: {}, other: {}'.format(result, other))
                self.assertEqual(result, other)

    def test_ceph_pool_creation_with_text_file(self):
        """Check the creation of a pool and a text file.

        Create a pool, add a text file to it and retrieve its content.
        Verify that the content matches the original file.
        """
        unit_name = 'ceph-mon/0'
        cmd = 'sudo ceph osd pool create test 128; \
               echo 123456789 > /tmp/input.txt; \
               rados put -p test test_input /tmp/input.txt; \
               rados get -p test test_input /dev/stdout'
        logging.debug('Creating test pool and putting test file in pool...')
        result = zaza_model.run_on_unit(unit_name, cmd)
        code = result.get('Code')
        if code != '0':
            raise zaza_model.CommandRunFailed(cmd, result)
        output = result.get('Stdout').strip()
        logging.debug('Output received: {}'.format(output))
        self.assertEqual(output, '123456789')

    def test_ceph_encryption(self):
        """Test Ceph encryption.

        Verify that the new disk is added with encryption by checking for
        Ceph's encryption keys directory.
        """
        current_release = zaza_openstack.get_os_release()
        trusty_mitaka = zaza_openstack.get_os_release('trusty_mitaka')
        if current_release >= trusty_mitaka:
            logging.warn("Skipping encryption test for Mitaka and higher")
            return
        unit_name = 'ceph-osd/0'
        set_default = {
            'osd-encrypt': 'False',
            'osd-devices': '/dev/vdb /srv/ceph',
        }
        set_alternate = {
            'osd-encrypt': 'True',
            'osd-devices': '/dev/vdb /srv/ceph /srv/ceph_encrypted',
        }
        juju_service = 'ceph-osd'
        logging.info('Making config change on {}...'.format(juju_service))
        mtime = zaza_model.get_unit_time(unit_name)

        file_mtime = None

        folder_name = '/etc/ceph/dmcrypt-keys/'
        with self.config_change(set_default, set_alternate,
                                application_name=juju_service):
            with tempfile.TemporaryDirectory() as tempdir:
                # Creating a temp dir to copy keys
                temp_folder = '/tmp/dmcrypt-keys'
                cmd = 'mkdir {}'.format(temp_folder)
                ret = zaza_model.run_on_unit(unit_name, cmd)
                logging.debug('Ret for cmd {} is {}'.format(cmd, ret))
                # Copy keys from /etc to /tmp
                cmd = 'sudo cp {}* {}'.format(folder_name, temp_folder)
                ret = zaza_model.run_on_unit(unit_name, cmd)
                logging.debug('Ret for cmd {} is {}'.format(cmd, ret))
                # Changing permissions to be able to SCP the files
                cmd = 'sudo chown -R ubuntu:ubuntu {}'.format(temp_folder)
                ret = zaza_model.run_on_unit(unit_name, cmd)
                logging.debug('Ret for cmd {} is {}'.format(cmd, ret))
                # SCP to retrieve all files in folder
                # -p: preserve timestamps
                source = '/tmp/dmcrypt-keys/*'
                zaza_model.scp_from_unit(unit_name=unit_name,
                                         source=source,
                                         destination=tempdir,
                                         scp_opts='-p')
                for elt in listdir(tempdir):
                    file_path = '/'.join([tempdir, elt])
                    if path.isfile(file_path):
                        file_mtime = path.getmtime(file_path)
                        if file_mtime:
                            break

        if not file_mtime:
            logging.warn('Could not determine mtime, assuming '
                         'folder does not exist')
            raise FileNotFoundError('folder does not exist')

        if file_mtime >= mtime:
            logging.info('Folder mtime is newer than provided mtime '
                         '(%s >= %s) on %s (OK)' % (file_mtime,
                                                    mtime, unit_name))
        else:
            logging.warn('Folder mtime is older than provided mtime'
                         '(%s < on %s) on %s' % (file_mtime,
                                                 mtime, unit_name))
            raise Exception('Folder mtime is older than provided mtime')

    def test_blocked_when_non_pristine_disk_appears(self):
        """Test blocked state with non-pristine disk.

        Validate that charm goes into blocked state when it is presented with
        new block devices that have foreign data on them.
        Instances used in UOSCI has a flavour with ephemeral storage in
        addition to the bootable instance storage.  The ephemeral storage
        device is partitioned, formatted and mounted early in the boot process
        by cloud-init.
        As long as the device is mounted the charm will not attempt to use it.
        If we unmount it and trigger the config-changed hook the block device
        will appear as a new and previously untouched device for the charm.
        One of the first steps of device eligibility checks should be to make
        sure we are seeing a pristine and empty device before doing any
        further processing.
        As the ephemeral device will have data on it we can use it to validate
        that these checks work as intended.
        """
        current_release = zaza_openstack.get_os_release()
        focal_ussuri = zaza_openstack.get_os_release('focal_ussuri')
        if current_release >= focal_ussuri:
            # NOTE(ajkavanagh) - focal (on ServerStack) is broken for /dev/vdb
            # and so this test can't pass: LP#1842751 discusses the issue, but
            # basically the snapd daemon along with lxcfs results in /dev/vdb
            # being mounted in the lxcfs process namespace.  If the charm
            # 'tries' to umount it, it can (as root), but the mount is still
            # 'held' by lxcfs and thus nothing else can be done with it.  This
            # is only a problem in serverstack with images with a default
            # /dev/vdb ephemeral
            logging.warn("Skipping pristine disk test for focal and higher")
            return
        logging.info('Checking behaviour when non-pristine disks appear...')
        logging.info('Configuring ephemeral-unmount...')
        alternate_conf = {
            'ephemeral-unmount': '/mnt',
            'osd-devices': '/dev/vdb'
        }
        juju_service = 'ceph-osd'
        zaza_model.set_application_config(juju_service, alternate_conf)
        ceph_osd_states = {
            'ceph-osd': {
                'workload-status': 'blocked',
                'workload-status-message': 'Non-pristine'
            }
        }
        zaza_model.wait_for_application_states(states=ceph_osd_states)
        logging.info('Units now in blocked state, running zap-disk action...')
        unit_names = ['ceph-osd/0', 'ceph-osd/1', 'ceph-osd/2']
        for unit_name in unit_names:
            zap_disk_params = {
                'devices': '/dev/vdb',
                'i-really-mean-it': True,
            }
            action_obj = zaza_model.run_action(
                unit_name=unit_name,
                action_name='zap-disk',
                action_params=zap_disk_params
            )
            logging.debug('Result of action: {}'.format(action_obj))

        logging.info('Running add-disk action...')
        for unit_name in unit_names:
            add_disk_params = {
                'osd-devices': '/dev/vdb',
            }
            action_obj = zaza_model.run_action(
                unit_name=unit_name,
                action_name='add-disk',
                action_params=add_disk_params
            )
            logging.debug('Result of action: {}'.format(action_obj))

        logging.info('Wait for idle/ready status...')
        zaza_model.wait_for_application_states()

        logging.info('OK')

        set_default = {
            'ephemeral-unmount': '',
            'osd-devices': '/dev/vdb',
        }

        current_release = zaza_openstack.get_os_release()
        bionic_train = zaza_openstack.get_os_release('bionic_train')
        if current_release < bionic_train:
            set_default['osd-devices'] = '/dev/vdb /srv/ceph'

        logging.info('Restoring to default configuration...')
        zaza_model.set_application_config(juju_service, set_default)

        zaza_model.wait_for_application_states()

    def test_pause_and_resume(self):
        """The services can be paused and resumed."""
        logging.info('Checking pause and resume actions...')
        self.pause_resume(['ceph-osd'])

    def test_blacklist(self):
        """Check the blacklist action.

        The blacklist actions execute and behave as expected.
        """
        logging.info('Checking blacklist-add-disk and'
                     'blacklist-remove-disk actions...')
        unit_name = 'ceph-osd/0'

        zaza_model.block_until_unit_wl_status(
            unit_name,
            'active'
        )

        # Attempt to add device with non-absolute path should fail
        action_obj = zaza_model.run_action(
            unit_name=unit_name,
            action_name='blacklist-add-disk',
            action_params={'osd-devices': 'vda'}
        )
        self.assertTrue(action_obj.status != 'completed')
        zaza_model.block_until_unit_wl_status(
            unit_name,
            'active'
        )

        # Attempt to add device with non-existent path should fail
        action_obj = zaza_model.run_action(
            unit_name=unit_name,
            action_name='blacklist-add-disk',
            action_params={'osd-devices': '/non-existent'}
        )
        self.assertTrue(action_obj.status != 'completed')
        zaza_model.block_until_unit_wl_status(
            unit_name,
            'active'
        )

        # Attempt to add device with existent path should succeed
        action_obj = zaza_model.run_action(
            unit_name=unit_name,
            action_name='blacklist-add-disk',
            action_params={'osd-devices': '/dev/vda'}
        )
        self.assertEqual('completed', action_obj.status)
        zaza_model.block_until_unit_wl_status(
            unit_name,
            'active'
        )

        # Attempt to remove listed device should always succeed
        action_obj = zaza_model.run_action(
            unit_name=unit_name,
            action_name='blacklist-remove-disk',
            action_params={'osd-devices': '/dev/vda'}
        )
        self.assertEqual('completed', action_obj.status)
        zaza_model.block_until_unit_wl_status(
            unit_name,
            'active'
        )
        logging.debug('OK')

    def test_list_disks(self):
        """Test the list-disks action.

        The list-disks action execute.
        """
        logging.info('Checking list-disks action...')
        unit_name = 'ceph-osd/0'

        zaza_model.block_until_unit_wl_status(
            unit_name,
            'active'
        )

        action_obj = zaza_model.run_action(
            unit_name=unit_name,
            action_name='list-disks',
        )
        self.assertEqual('completed', action_obj.status)
        zaza_model.block_until_unit_wl_status(
            unit_name,
            'active'
        )
        logging.debug('OK')


class CephRGWTest(test_utils.OpenStackBaseTest):
    """Ceph RADOS Gateway Daemons Test Class."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph low level tests."""
        super(CephRGWTest, cls).setUpClass(application_name='ceph-radosgw')

    @property
    def expected_apps(self):
        """Determine application names for ceph-radosgw apps."""
        _apps = [
            'ceph-radosgw'
        ]
        try:
            zaza_model.get_application('slave-ceph-radosgw')
            _apps.append('slave-ceph-radosgw')
        except KeyError:
            pass
        return _apps

    @property
    def multisite(self):
        """Determine whether deployment is multi-site."""
        try:
            zaza_model.get_application('slave-ceph-radosgw')
            return True
        except KeyError:
            return False

    def test_processes(self):
        """Verify Ceph processes.

        Verify that the expected service processes are running
        on each ceph unit.
        """
        logging.info('Checking radosgw processes...')
        # Process name and quantity of processes to expect on each unit
        ceph_radosgw_processes = {
            'radosgw': 1,
        }

        # Units with process names and PID quantities expected
        expected_processes = {}
        for app in self.expected_apps:
            for unit in zaza_model.get_units(app):
                expected_processes[unit.entity_id] = ceph_radosgw_processes

        actual_pids = zaza_utils.get_unit_process_ids(expected_processes)
        ret = zaza_utils.validate_unit_process_ids(expected_processes,
                                                   actual_pids)
        self.assertTrue(ret)

    def test_services(self):
        """Verify the ceph services.

        Verify the expected services are running on the service units.
        """
        logging.info('Checking radosgw services...')
        services = ['radosgw', 'haproxy']
        for app in self.expected_apps:
            for unit in zaza_model.get_units(app):
                zaza_model.block_until_service_status(
                    unit_name=unit.entity_id,
                    services=services,
                    target_status='running'
                )

    # When testing with TLS there is a chance the deployment will appear done
    # and idle prior to ceph-radosgw and Keystone have updated the service
    # catalog.  Retry the test in this circumstance.
    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=10, max=300),
                    reraise=True, stop=tenacity.stop_after_attempt(10),
                    retry=tenacity.retry_if_exception_type(IOError))
    def test_object_storage(self):
        """Verify object storage API.

        Verify that the object storage API works as expected.
        """
        if self.multisite:
            raise unittest.SkipTest('Skipping REST API test, '
                                    'multisite configuration')
        logging.info('Checking Swift REST API')
        keystone_session = zaza_openstack.get_overcloud_keystone_session()
        region_name = zaza_model.get_application_config(
            self.application_name,
            model_name=self.model_name)['region']['value']
        swift_client = zaza_openstack.get_swift_session_client(
            keystone_session,
            region_name,
            cacert=self.cacert,
        )
        _container = 'demo-container'
        _test_data = 'Test data from Zaza'
        swift_client.put_container(_container)
        swift_client.put_object(_container,
                                'testfile',
                                contents=_test_data,
                                content_type='text/plain')
        _, content = swift_client.get_object(_container, 'testfile')
        self.assertEqual(content.decode('UTF-8'), _test_data)

    def test_object_storage_multisite(self):
        """Verify object storage replication.

        Verify that the object storage replication works as expected.
        """
        if not self.multisite:
            raise unittest.SkipTest('Skipping multisite replication test')

        logging.info('Checking multisite replication')
        keystone_session = zaza_openstack.get_overcloud_keystone_session()
        source_client = zaza_openstack.get_swift_session_client(
            keystone_session,
            region_name='east-1',
            cacert=self.cacert,
        )
        _container = 'demo-container'
        _test_data = 'Test data from Zaza'
        source_client.put_container(_container)
        source_client.put_object(_container,
                                 'testfile',
                                 contents=_test_data,
                                 content_type='text/plain')
        _, source_content = source_client.get_object(_container, 'testfile')
        self.assertEqual(source_content.decode('UTF-8'), _test_data)

        target_client = zaza_openstack.get_swift_session_client(
            keystone_session,
            region_name='east-1',
            cacert=self.cacert,
        )

        @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                        reraise=True, stop=tenacity.stop_after_attempt(12))
        def _target_get_object():
            return target_client.get_object(_container, 'testfile')
        _, target_content = _target_get_object()

        self.assertEqual(target_content.decode('UTF-8'),
                         source_content.decode('UTF-8'))
        target_client.delete_object(_container, 'testfile')

        try:
            source_client.head_object(_container, 'testfile')
        except ClientException as e:
            self.assertEqual(e.http_status, 404)
        else:
            self.fail('object not deleted on source radosgw')

    def test_multisite_failover(self):
        """Verify object storage failover/failback.

        Verify that the slave radosgw can be promoted to master status
        """
        if not self.multisite:
            raise unittest.SkipTest('Skipping multisite failover test')

        logging.info('Checking multisite failover/failback')
        keystone_session = zaza_openstack.get_overcloud_keystone_session()
        source_client = zaza_openstack.get_swift_session_client(
            keystone_session,
            region_name='east-1',
            cacert=self.cacert,
        )
        target_client = zaza_openstack.get_swift_session_client(
            keystone_session,
            region_name='west-1',
            cacert=self.cacert,
        )
        zaza_model.run_action_on_leader(
            'slave-ceph-radosgw',
            'promote',
            action_params={},
        )
        _container = 'demo-container-for-failover'
        _test_data = 'Test data from Zaza on Slave'
        target_client.put_container(_container)
        target_client.put_object(_container,
                                 'testfile',
                                 contents=_test_data,
                                 content_type='text/plain')
        _, target_content = target_client.get_object(_container, 'testfile')

        zaza_model.run_action_on_leader(
            'ceph-radosgw',
            'promote',
            action_params={},
        )

        @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                        reraise=True, stop=tenacity.stop_after_attempt(12))
        def _source_get_object():
            return source_client.get_object(_container, 'testfile')
        _, source_content = _source_get_object()

        self.assertEqual(target_content.decode('UTF-8'),
                         source_content.decode('UTF-8'))


class CephProxyTest(unittest.TestCase):
    """Test ceph via proxy."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(CephProxyTest, cls).setUpClass()

    def test_ceph_health(self):
        """Make sure ceph-proxy can communicate with ceph."""
        logging.info('Wait for idle/ready status...')
        zaza_model.wait_for_application_states()

        self.assertEqual(
            zaza_model.run_on_leader("ceph-proxy", "sudo ceph health")["Code"],
            "0"
        )

    def test_cinder_ceph_restrict_pool_setup(self):
        """Make sure cinder-ceph restrict pool was created successfully."""
        logging.info('Wait for idle/ready status...')
        zaza_model.wait_for_application_states()

        pools = zaza_ceph.get_ceph_pools('ceph-mon/0')
        if 'cinder-ceph' not in pools:
            msg = 'cinder-ceph pool was not found upon querying ceph-mon/0'
            raise zaza_exceptions.CephPoolNotFound(msg)

        # Checking for cinder-ceph specific permissions makes
        # the test more rugged when we add additional relations
        # to ceph for other applications (such as glance and nova).
        expected_permissions = [
            "allow rwx pool=cinder-ceph",
            "allow class-read object_prefix rbd_children",
        ]
        cmd = "sudo ceph auth get client.cinder-ceph"
        result = zaza_model.run_on_unit('ceph-mon/0', cmd)
        output = result.get('Stdout').strip()

        for expected in expected_permissions:
            if expected not in output:
                msg = ('cinder-ceph pool restriction ({}) was not'
                       ' configured correctly.'
                       ' Found: {}'.format(expected, output))
                raise zaza_exceptions.CephPoolNotConfigured(msg)


class CephPrometheusTest(unittest.TestCase):
    """Test the Ceph <-> Prometheus relation."""

    def test_prometheus_metrics(self):
        """Validate that Prometheus has Ceph metrics."""
        try:
            zaza_model.get_application(
                'prometheus2')
        except KeyError:
            raise unittest.SkipTest('Prometheus not present, skipping test')
        unit = zaza_model.get_unit_from_name(
            zaza_model.get_lead_unit_name('prometheus2'))
        self.assertEqual(
            '3',
            _get_mon_count_from_prometheus(
                zaza_model.get_unit_public_address(unit)))


class CephPoolConfig(Exception):
    """Custom Exception for bad Ceph pool config."""

    pass


class CheckPoolTypes(unittest.TestCase):
    """Test the ceph pools created for clients are of the expected type."""

    def test_check_pool_types(self):
        """Check type of pools created for clients."""
        app_pools = [
            ('glance', 'glance'),
            ('nova-compute', 'nova'),
            ('cinder-ceph', 'cinder-ceph')]
        runtime_pool_details = zaza_ceph.get_ceph_pool_details()
        for app, pool_name in app_pools:
            try:
                app_config = zaza_model.get_application_config(app)
            except KeyError:
                logging.info(
                    'Skipping pool check of %s, application %s not present',
                    pool_name,
                    app)
                continue
            rel_id = zaza_model.get_relation_id(
                app,
                'ceph-mon',
                remote_interface_name='client')
            if not rel_id:
                logging.info(
                    'Skipping pool check of %s, ceph relation not present',
                    app)
                continue
            juju_pool_config = app_config.get('pool-type')
            if juju_pool_config:
                expected_pool_type = juju_pool_config['value']
            else:
                # If the pool-type option is absent assume the default of
                # replicated.
                expected_pool_type = zaza_ceph.REPLICATED_POOL_TYPE
            for pool_config in runtime_pool_details:
                if pool_config['pool_name'] == pool_name:
                    logging.info('Checking {} is {}'.format(
                        pool_name,
                        expected_pool_type))
                    expected_pool_code = -1
                    if expected_pool_type == zaza_ceph.REPLICATED_POOL_TYPE:
                        expected_pool_code = zaza_ceph.REPLICATED_POOL_CODE
                    elif expected_pool_type == zaza_ceph.ERASURE_POOL_TYPE:
                        expected_pool_code = zaza_ceph.ERASURE_POOL_CODE
                    self.assertEqual(
                        pool_config['type'],
                        expected_pool_code)
                    break
            else:
                raise CephPoolConfig(
                    "Failed to find config for {}".format(pool_name))


# NOTE: We might query before prometheus has fetch data
@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1,
                                               min=5, max=10),
                reraise=True)
def _get_mon_count_from_prometheus(prometheus_ip):
    url = ('http://{}:9090/api/v1/query?query='
           'count(ceph_mon_metadata)'.format(prometheus_ip))
    client = requests.session()
    response = client.get(url)
    logging.debug("Prometheus response: {}".format(response.json()))
    return response.json()['data']['result'][0]['value'][1]


class BlueStoreCompressionCharmOperation(test_utils.BaseCharmTest):
    """Test charm handling of bluestore compression configuration options."""

    @classmethod
    def setUpClass(cls):
        """Perform class one time initialization."""
        super(BlueStoreCompressionCharmOperation, cls).setUpClass()
        release_application = 'keystone'
        try:
            zaza_model.get_application(release_application)
        except KeyError:
            release_application = 'ceph-mon'
        cls.current_release = zaza_openstack.get_os_release(
            application=release_application)
        cls.bionic_rocky = zaza_openstack.get_os_release('bionic_rocky')

    def setUp(self):
        """Perform common per test initialization steps."""
        super(BlueStoreCompressionCharmOperation, self).setUp()

        # determine if the tests should be run or not
        logging.debug('os_release: {} >= {} = {}'
                      .format(self.current_release,
                              self.bionic_rocky,
                              self.current_release >= self.bionic_rocky))
        self.mimic_or_newer = self.current_release >= self.bionic_rocky

    def _assert_pools_properties(self, pools, pools_detail,
                                 expected_properties, log_func=logging.info):
        """Check properties on a set of pools.

        :param pools: List of pool names to check.
        :type pools: List[str]
        :param pools_detail: List of dictionaries with pool detail
        :type pools_detail List[Dict[str,any]]
        :param expected_properties: Properties to check and their expected
                                    values.
        :type expected_properties: Dict[str,any]
        :returns: Nothing
        :raises: AssertionError
        """
        for pool in pools:
            for pd in pools_detail:
                if pd['pool_name'] == pool:
                    if 'options' in expected_properties:
                        for k, v in expected_properties['options'].items():
                            self.assertEquals(pd['options'][k], v)
                            log_func("['options']['{}'] == {}".format(k, v))
                    for k, v in expected_properties.items():
                        if k == 'options':
                            continue
                        self.assertEquals(pd[k], v)
                        log_func("{} == {}".format(k, v))

    def test_configure_compression(self):
        """Enable compression and validate properties flush through to pool."""
        if not self.mimic_or_newer:
            logging.info('Skipping test, Mimic or newer required.')
            return
        if self.application_name == 'ceph-osd':
            # The ceph-osd charm itself does not request pools, neither does
            # the BlueStore Compression configuration options it have affect
            # pool properties.
            logging.info('test does not apply to ceph-osd charm.')
            return
        elif self.application_name == 'ceph-radosgw':
            # The Ceph RadosGW creates many light weight pools to keep track of
            # metadata, we only compress the pool containing actual data.
            app_pools = ['.rgw.buckets.data']
        else:
            # Retrieve which pools the charm under test has requested skipping
            # metadata pools as they are deliberately not compressed.
            app_pools = [
                pool
                for pool in zaza_ceph.get_pools_from_broker_req(
                    self.application_name, model_name=self.model_name)
                if 'metadata' not in pool
            ]

        ceph_pools_detail = zaza_ceph.get_ceph_pool_details(
            model_name=self.model_name)

        logging.debug('BEFORE: {}'.format(ceph_pools_detail))
        try:
            logging.info('Checking Ceph pool compression_mode prior to change')
            self._assert_pools_properties(
                app_pools, ceph_pools_detail,
                {'options': {'compression_mode': 'none'}})
        except KeyError:
            logging.info('property does not exist on pool, which is OK.')
        logging.info('Changing "bluestore-compression-mode" to "force" on {}'
                     .format(self.application_name))
        with self.config_change(
                {'bluestore-compression-mode': 'none'},
                {'bluestore-compression-mode': 'force'}):
            logging.info('Checking Ceph pool compression_mode after to change')
            self._check_pool_compression_mode(app_pools, 'force')

        logging.info('Checking Ceph pool compression_mode after '
                     'restoring config to previous value')
        self._check_pool_compression_mode(app_pools, 'none')

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
        stop=tenacity.stop_after_attempt(10),
        reraise=True,
        retry=tenacity.retry_if_exception_type(AssertionError)
    )
    def _check_pool_compression_mode(self, app_pools, mode):
        ceph_pools_detail = zaza_ceph.get_ceph_pool_details(
            model_name=self.model_name)
        logging.debug('ceph_pools_details: %s', ceph_pools_detail)
        logging.debug(juju_utils.get_relation_from_unit(
            'ceph-mon', self.application_name, None,
            model_name=self.model_name))
        self._assert_pools_properties(
            app_pools, ceph_pools_detail,
            {'options': {'compression_mode': mode}})

    def test_invalid_compression_configuration(self):
        """Set invalid configuration and validate charm response."""
        if not self.mimic_or_newer:
            logging.info('Skipping test, Mimic or newer required.')
            return
        stored_target_deploy_status = self.test_config.get(
            'target_deploy_status', {})
        new_target_deploy_status = stored_target_deploy_status.copy()
        new_target_deploy_status[self.application_name] = {
            'workload-status': 'blocked',
            'workload-status-message': 'Invalid configuration',
        }
        if 'target_deploy_status' in self.test_config:
            self.test_config['target_deploy_status'].update(
                new_target_deploy_status)
        else:
            self.test_config['target_deploy_status'] = new_target_deploy_status

        with self.config_change(
                {'bluestore-compression-mode': 'none'},
                {'bluestore-compression-mode': 'PEBCAK'}):
            logging.info('Charm went into blocked state as expected, restore '
                         'configuration')
            self.test_config[
                'target_deploy_status'] = stored_target_deploy_status
