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
import boto3
import botocore.exceptions
import urllib3

import tenacity

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.model as zaza_model
import zaza.openstack.utilities.ceph as zaza_ceph
import zaza.openstack.utilities.exceptions as zaza_exceptions
import zaza.openstack.utilities.generic as zaza_utils
import zaza.utilities.juju as juju_utils
import zaza.openstack.utilities.openstack as zaza_openstack
import zaza.openstack.utilities.generic as generic_utils

# Disable warnings for ssl_verify=false
urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


class CephLowLevelTest(test_utils.BaseCharmTest):
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
            'ceph-mgr': 1,
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
        ceph_services = ['ceph-mon', 'ceph-mgr']
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


class CephTest(test_utils.BaseCharmTest):
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
        try:
            zaza_model.get_application('cinder-ceph')
        except KeyError:
            raise unittest.SkipTest("Skipping OpenStack dependent test")
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
        cmd = 'sudo ceph osd pool create test {PG_NUM}; \
               echo 123456789 > /tmp/input.txt; \
               rados put -p test test_input /tmp/input.txt; \
               rados get -p test test_input /dev/stdout'
        cmd = cmd.format(PG_NUM=32)
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
        current_release = zaza_openstack.get_os_release(application='ceph-mon')
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
        current_release = zaza_openstack.get_os_release(application='ceph-mon')
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

    def get_device_for_blacklist(self, unit):
        """Return a device to be used by the blacklist tests."""
        cmd = "mount | grep 'on / ' | awk '{print $1}'"
        obj = zaza_model.run_on_unit(unit, cmd)
        return obj.get('Stdout').strip()

    def test_blacklist(self):
        """Check the blacklist action.

        The blacklist actions execute and behave as expected.
        """
        logging.info('Checking blacklist-add-disk and '
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
        device = self.get_device_for_blacklist(unit_name)
        if not device:
            raise unittest.SkipTest(
                "Skipping test because no device was found")

        action_obj = zaza_model.run_action(
            unit_name=unit_name,
            action_name='blacklist-add-disk',
            action_params={'osd-devices': device}
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
            action_params={'osd-devices': device}
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

    def get_local_osd_id(self, unit):
        """Get the OSD id for a unit."""
        ret = zaza_model.run_on_unit(unit,
                                     'ceph-volume lvm list --format=json')
        local = list(json.loads(ret['Stdout']))[-1]
        return local if local.startswith('osd.') else 'osd.' + local

    def get_num_osds(self, osd, is_up_only=False):
        """Compute the number of active OSD's."""
        result = zaza_model.run_on_unit(osd, 'ceph osd stat --format=json')
        result = json.loads(result['Stdout'])
        if is_up_only:
            return int(result['num_up_osds'])
        else:
            return int(result['num_osds'])

    def get_osd_devices_on_unit(self, unit_name):
        """Get information for osd devices present on a particular unit.

        :param unit: Unit name to be queried for osd device info.
        :type unit: str
        """
        osd_devices = json.loads(
            zaza_model.run_on_unit(
                unit_name, 'ceph-volume lvm list --format=json'
            ).get('Stdout', '')
        )

        return osd_devices

    def remove_disk_from_osd_unit(self, unit, osd_id, is_purge=False):
        """Remove osd device with provided osd_id from unit.

        :param unit: Unit name where the osd device is to be removed from.
        :type unit: str

        :param osd_id: osd-id for the osd device to be removed.
        :type osd_id: str

        :param is_purge: whether to purge the osd device
        :type is_purge: bool
        """
        action_obj = zaza_model.run_action(
            unit_name=unit,
            action_name='remove-disk',
            action_params={
                'osd-ids': osd_id,
                'timeout': 10,
                'format': 'json',
                'purge': is_purge
            }
        )
        zaza_utils.assertActionRanOK(action_obj)
        results = json.loads(action_obj.data['results']['message'])
        results = results[next(iter(results))]
        self.assertEqual(results['osd-ids'], osd_id)
        zaza_model.run_on_unit(unit, 'partprobe')

    def remove_one_osd(self, unit, block_devs):
        """Remove one device from osd unit.

        :param unit: Unit name where the osd device is to be removed from.
        :type unit: str
        :params block_devs: list of block devices on the scpecified unit
        :type block_devs: list[str]
        """
        # Should have more than 1 OSDs to take one out and test.
        self.assertGreater(len(block_devs), 1)

        # Get complete device details for an OSD.
        key = list(block_devs)[-1]
        device = {
            'osd-id': key if key.startswith('osd.') else 'osd.' + key,
            'block-device': block_devs[key][0]['devices'][0]
        }

        self.remove_disk_from_osd_unit(unit, device['osd-id'], is_purge=True)
        return device

    def test_cache_device(self):
        """Test replacing a disk in use."""
        logging.info('Running add-disk action with a caching device')
        mon = next(iter(zaza_model.get_units('ceph-mon'))).entity_id
        osds = [x.entity_id for x in zaza_model.get_units('ceph-osd')]
        osd_info = dict()

        # Remove one of the two disks.
        logging.info('Removing single disk from each OSD')
        for unit in osds:
            block_devs = self.get_osd_devices_on_unit(unit)
            if len(block_devs) < 2:
                continue
            device_info = self.remove_one_osd(unit, block_devs)
            block_dev = device_info['block-device']
            logging.info("Removing device %s from unit %s" % (block_dev, unit))
            osd_info[unit] = device_info
        if not osd_info:
            raise unittest.SkipTest(
                'Skipping OSD replacement Test, no spare devices added')

        logging.debug('Removed OSD Info: {}'.format(osd_info))
        zaza_model.wait_for_application_states()

        logging.info('Recycling previously removed disks')
        for unit, device_info in osd_info.items():
            osd_id = device_info['osd-id']
            block_dev = device_info['block-device']
            logging.info("Found device %s on unit %s" % (block_dev, unit))
            self.assertNotEqual(block_dev, None)
            action_obj = zaza_model.run_action(
                unit_name=unit,
                action_name='add-disk',
                action_params={'osd-devices': block_dev,
                               'osd-ids': osd_id,
                               'partition-size': 5}
            )
            zaza_utils.assertActionRanOK(action_obj)
        zaza_model.wait_for_application_states()

        logging.info('Removing previously added OSDs')
        for unit, device_info in osd_info.items():
            osd_id = device_info['osd-id']
            block_dev = device_info['block-device']
            logging.info(
                "Removing block device %s from unit %s" %
                (block_dev, unit)
            )
            self.remove_disk_from_osd_unit(unit, osd_id, is_purge=False)
        zaza_model.wait_for_application_states()

        logging.info('Finally adding back OSDs')
        for unit, device_info in osd_info.items():
            block_dev = device_info['block-device']
            action_obj = zaza_model.run_action(
                unit_name=unit,
                action_name='add-disk',
                action_params={'osd-devices': block_dev,
                               'partition-size': 5}
            )
            zaza_utils.assertActionRanOK(action_obj)
        zaza_model.wait_for_application_states()

        for attempt in tenacity.Retrying(
            wait=tenacity.wait_exponential(multiplier=2, max=32),
            reraise=True, stop=tenacity.stop_after_attempt(10),
            retry=tenacity.retry_if_exception_type(AssertionError)
        ):
            with attempt:
                self.assertEqual(
                    len(osds) * 2, self.get_num_osds(mon, is_up_only=True)
                )


class CephRGWTest(test_utils.BaseCharmTest):
    """Ceph RADOS Gateway Daemons Test Class.

    This Testset is not idempotent, because we don't support scale down from
    multisite to singlesite (yet). Tests can be performed independently.
    However, If test_004 has completed migration, retriggering the test-set
    would cause a time-out in test_003.
    """

    # String Resources
    primary_rgw_app = 'ceph-radosgw'
    primary_rgw_unit = 'ceph-radosgw/0'
    secondary_rgw_app = 'secondary-ceph-radosgw'
    secondary_rgw_unit = 'secondary-ceph-radosgw/0'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph low level tests."""
        super(CephRGWTest, cls).setUpClass(application_name='ceph-radosgw')

    @property
    def expected_apps(self):
        """Determine application names for ceph-radosgw apps."""
        _apps = [
            self.primary_rgw_app
        ]
        try:
            zaza_model.get_application(self.secondary_rgw_app)
            _apps.append(self.secondary_rgw_app)
        except KeyError:
            pass
        return _apps

    @property
    def multisite(self):
        """Determine whether deployment is multi-site."""
        try:
            zaza_model.get_application(self.secondary_rgw_app)
            return True
        except KeyError:
            return False

    def get_rgwadmin_cmd_skeleton(self, unit_name):
        """
        Get radosgw-admin cmd skeleton with rgw.hostname populated key.

        :param unit_name: Unit on which the complete command would be run.
        :type unit_name: str
        :returns: hostname filled basic command skeleton
        :rtype: str
        """
        app_name = unit_name.split('/')[0]
        juju_units = zaza_model.get_units(app_name)
        unit_hostnames = generic_utils.get_unit_hostnames(juju_units)
        hostname = unit_hostnames[unit_name]
        return 'radosgw-admin --id=rgw.{} '.format(hostname)

    def purge_bucket(self, application, bucket_name):
        """Remove a bucket and all it's objects.

        :param application: RGW application name
        :type application: str
        :param bucket_name: Name for RGW bucket to be deleted
        :type bucket_name: str
        """
        juju_units = zaza_model.get_units(application)
        unit_hostnames = generic_utils.get_unit_hostnames(juju_units)
        for unit_name, hostname in unit_hostnames.items():
            key_name = "rgw.{}".format(hostname)
            cmd = 'radosgw-admin --id={} bucket rm --bucket={}' \
                  ' --purge-objects'.format(key_name, bucket_name)
            zaza_model.run_on_unit(unit_name, cmd)

    def wait_for_status(self, application,
                        is_primary=False, sync_expected=True):
        """Wait for required RGW endpoint to finish sync for data and metadata.

        :param application: RGW application which has to be waited for
        :type application: str
        :param is_primary: whether RGW application is primary or secondary
        :type is_primary: boolean
        :param sync_expected: whether sync details should be expected in status
        :type sync_expected: boolean
        """
        juju_units = zaza_model.get_units(application)
        unit_hostnames = generic_utils.get_unit_hostnames(juju_units)
        data_check = 'data is caught up with source'
        meta_primary = 'metadata sync no sync (zone is master)'
        meta_secondary = 'metadata is caught up with master'
        meta_check = meta_primary if is_primary else meta_secondary

        for attempt in tenacity.Retrying(
            wait=tenacity.wait_exponential(multiplier=10, max=300),
            reraise=True, stop=tenacity.stop_after_attempt(12),
            retry=tenacity.retry_if_exception_type(AssertionError)
        ):
            with attempt:
                for unit_name, hostname in unit_hostnames.items():
                    key_name = "rgw.{}".format(hostname)
                    cmd = 'radosgw-admin --id={} sync status'.format(key_name)
                    stdout = zaza_model.run_on_unit(
                        unit_name, cmd
                    ).get('Stdout', '')
                    if sync_expected:
                        # Both data and meta sync.
                        self.assertIn(data_check, stdout)
                        self.assertIn(meta_check, stdout)
                    else:
                        #  ExpectPrimary's Meta Status and no Data sync status
                        self.assertIn(meta_primary, stdout)
                        self.assertNotIn(data_check, stdout)

    def fetch_rgw_object(self, target_client, container_name, object_name):
        """Fetch RGW object content.

        :param target_client: boto3 client object configured for an endpoint.
        :type target_client: str
        :param container_name: RGW bucket name for desired object.
        :type container_name: str
        :param object_name: Object name for desired object.
        :type object_name: str
        """
        for attempt in tenacity.Retrying(
            wait=tenacity.wait_exponential(multiplier=1, max=60),
            reraise=True, stop=tenacity.stop_after_attempt(12)
        ):
            with attempt:
                return target_client.Object(
                    container_name, object_name
                ).get()['Body'].read().decode('UTF-8')

    def promote_rgw_to_primary(self, app_name: str):
        """Promote provided app to Primary and update period at new secondary.

        :param app_name: Secondary site rgw Application to be promoted.
        :type app_name: str
        """
        if app_name is self.primary_rgw_app:
            new_secondary = self.secondary_rgw_unit
        else:
            new_secondary = self.primary_rgw_unit

        # Promote to Primary
        zaza_model.run_action_on_leader(
            app_name,
            'promote',
            action_params={},
        )

        # Period Update Commit new secondary.
        cmd = self.get_rgwadmin_cmd_skeleton(new_secondary)
        zaza_model.run_on_unit(
            new_secondary, cmd + 'period update --commit'
        )

    def get_client_keys(self, rgw_app_name=None):
        """Create access_key and secret_key for boto3 client.

        :param rgw_app_name: RGW application for which keys are required.
        :type rgw_app_name: str
        """
        unit_name = self.primary_rgw_unit
        if rgw_app_name is not None:
            unit_name = rgw_app_name + '/0'
        user_name = 'botoclient'
        cmd = self.get_rgwadmin_cmd_skeleton(unit_name)
        users = json.loads(zaza_model.run_on_unit(
            unit_name, cmd + 'user list'
        ).get('Stdout', ''))
        # Fetch boto3 user keys if user exists.
        if user_name in users:
            output = json.loads(zaza_model.run_on_unit(
                unit_name, cmd + 'user info --uid={}'.format(user_name)
            ).get('Stdout', ''))
            keys = output['keys'][0]
            return keys['access_key'], keys['secret_key']
        # Create boto3 user if it does not exist.
        create_cmd = cmd + 'user create --uid={} --display-name={}'.format(
            user_name, user_name
        )
        output = json.loads(
            zaza_model.run_on_unit(unit_name, create_cmd).get('Stdout', '')
        )
        keys = output['keys'][0]
        return keys['access_key'], keys['secret_key']

    @tenacity.retry(
        retry=tenacity.retry_if_result(lambda ret: ret is None),
        wait=tenacity.wait_fixed(10),
        stop=tenacity.stop_after_attempt(5)
    )
    def get_rgw_endpoint(self, unit_name: str):
        """Fetch Application endpoint for RGW unit.

        :param unit_name: Unit name for which RGW endpoint is required.
        :type unit_name: str
        """
        unit = zaza_model.get_unit_from_name(unit_name)
        unit_address = zaza_model.get_unit_public_address(
            unit,
            self.model_name
        )

        logging.debug("Unit: {}, Endpoint: {}".format(unit_name, unit_address))
        if unit_address is None:
            return None
        # Evaluate port
        try:
            zaza_model.get_application("vault")
            return "https://{}:443".format(unit_address)
        except KeyError:
            return "http://{}:80".format(unit_address)

    def configure_rgw_apps_for_multisite(self):
        """Configure Multisite values on primary and secondary apps."""
        realm = 'zaza_realm'
        zonegroup = 'zaza_zg'

        zaza_model.set_application_config(
            self.primary_rgw_app,
            {
                'realm': realm,
                'zonegroup': zonegroup,
                'zone': 'zaza_primary'
            }
        )
        zaza_model.set_application_config(
            self.secondary_rgw_app,
            {
                'realm': realm,
                'zonegroup': zonegroup,
                'zone': 'zaza_secondary'
            }
        )

    def clean_rgw_multisite_config(self, app_name):
        """Clear Multisite Juju config values to default.

        :param app_name: App for which config values are to be cleared
        :type app_name: str
        """
        unit_name = app_name + "/0"
        zaza_model.set_application_config(
            app_name,
            {
                'realm': "",
                'zonegroup': "",
                'zone': "default"
            }
        )
        # Commit changes to period.
        cmd = self.get_rgwadmin_cmd_skeleton(unit_name)
        zaza_model.run_on_unit(
            unit_name, cmd + 'period update --commit --rgw-zone=default '
            '--rgw-zonegroup=default'
        )

    def test_001_processes(self):
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

    def test_002_services(self):
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

    def test_003_object_storage_and_secondary_block(self):
        """Verify Object Storage API and Secondary Migration block."""
        container_name = 'zaza-container'
        obj_data = 'Test data from Zaza'
        obj_name = 'prefile'

        logging.info('Checking Object Storage API for Primary Cluster')
        # 1. Fetch Primary Endpoint Details
        primary_endpoint = self.get_rgw_endpoint(self.primary_rgw_unit)
        self.assertNotEqual(primary_endpoint, None)

        # 2. Create RGW Client and perform IO
        access_key, secret_key = self.get_client_keys()
        primary_client = boto3.resource("s3",
                                        verify=False,
                                        endpoint_url=primary_endpoint,
                                        aws_access_key_id=access_key,
                                        aws_secret_access_key=secret_key)
        primary_client.Bucket(container_name).create()
        primary_object_one = primary_client.Object(
            container_name,
            obj_name
        )
        primary_object_one.put(Body=obj_data)

        # 3. Fetch Object and Perform Data Integrity check.
        content = primary_object_one.get()['Body'].read().decode('UTF-8')
        self.assertEqual(content, obj_data)

        # Skip multisite tests if not compatible with bundle.
        if not self.multisite:
            logging.info('Skipping Secondary Object gatewaty verification')
            return

        logging.info('Checking Object Storage API for Secondary Cluster')
        # 1. Fetch Secondary Endpoint Details
        secondary_endpoint = self.get_rgw_endpoint(self.secondary_rgw_unit)
        self.assertNotEqual(secondary_endpoint, None)

        # 2. Create RGW Client and perform IO
        access_key, secret_key = self.get_client_keys(self.secondary_rgw_app)
        secondary_client = boto3.resource("s3",
                                          verify=False,
                                          endpoint_url=secondary_endpoint,
                                          aws_access_key_id=access_key,
                                          aws_secret_access_key=secret_key)
        secondary_client.Bucket(container_name).create()
        secondary_object = secondary_client.Object(
            container_name,
            obj_name
        )
        secondary_object.put(Body=obj_data)

        # 3. Fetch Object and Perform Data Integrity check.
        content = secondary_object.get()['Body'].read().decode('UTF-8')
        self.assertEqual(content, obj_data)

        logging.info('Checking Secondary Migration Block')
        # 1. Migrate to multisite
        if zaza_model.get_relation_id(
                self.primary_rgw_app, self.secondary_rgw_app,
                remote_interface_name='secondary'
        ) is not None:
            logging.info('Skipping Test, Multisite relation already present.')
            return

        logging.info('Configuring Multisite')
        self.configure_rgw_apps_for_multisite()
        zaza_model.add_relation(
            self.primary_rgw_app,
            self.primary_rgw_app + ":primary",
            self.secondary_rgw_app + ":secondary"
        )

        # 2. Verify secondary fails migration due to existing Bucket.
        assert_state = {
            self.secondary_rgw_app: {
                "workload-status": "blocked",
                "workload-status-message-prefix":
                    "Non-Pristine RGW site can't be used as secondary"
            }
        }
        zaza_model.wait_for_application_states(states=assert_state,
                                               timeout=900)

        # 3. Perform Secondary Cleanup
        logging.info('Perform cleanup at secondary')
        self.clean_rgw_multisite_config(self.secondary_rgw_app)
        zaza_model.remove_relation(
            self.primary_rgw_app,
            self.primary_rgw_app + ":primary",
            self.secondary_rgw_app + ":secondary"
        )

        # Make secondary pristine.
        self.purge_bucket(self.secondary_rgw_app, container_name)

        zaza_model.block_until_unit_wl_status(self.secondary_rgw_unit,
                                              'active')

    def test_004_migration_and_multisite_failover(self):
        """Perform multisite migration and verify failover."""
        container_name = 'zaza-container'
        obj_data = 'Test data from Zaza'
        # Skip multisite tests if not compatible with bundle.
        if not self.multisite:
            raise unittest.SkipTest('Skipping Migration Test')

        logging.info('Perform Pre-Migration IO')
        # 1. Fetch Endpoint Details
        primary_endpoint = self.get_rgw_endpoint(self.primary_rgw_unit)
        self.assertNotEqual(primary_endpoint, None)

        # 2. Create primary client and add pre-migration object.
        access_key, secret_key = self.get_client_keys()
        primary_client = boto3.resource("s3",
                                        verify=False,
                                        endpoint_url=primary_endpoint,
                                        aws_access_key_id=access_key,
                                        aws_secret_access_key=secret_key)
        primary_client.Bucket(container_name).create()
        primary_client.Object(
            container_name,
            'prefile'
        ).put(Body=obj_data)

        # If Primary/Secondary relation does not exist, add it.
        if zaza_model.get_relation_id(
                self.primary_rgw_app, self.secondary_rgw_app,
                remote_interface_name='secondary'
        ) is None:
            logging.info('Configuring Multisite')
            self.configure_rgw_apps_for_multisite()
            zaza_model.add_relation(
                self.primary_rgw_app,
                self.primary_rgw_app + ":primary",
                self.secondary_rgw_app + ":secondary"
            )
            zaza_model.block_until_unit_wl_status(
                self.secondary_rgw_unit, "waiting"
            )

        zaza_model.block_until_unit_wl_status(
            self.secondary_rgw_unit, "active"
        )
        logging.info('Waiting for Data and Metadata to Synchronize')
        self.wait_for_status(self.secondary_rgw_app, is_primary=False)
        self.wait_for_status(self.primary_rgw_app, is_primary=True)

        logging.info('Performing post migration IO tests.')
        # Add another object at primary
        primary_client.Object(
            container_name,
            'postfile'
        ).put(Body=obj_data)

        # 1. Fetch Endpoint Details
        secondary_endpoint = self.get_rgw_endpoint(self.secondary_rgw_unit)
        self.assertNotEqual(secondary_endpoint, None)

        # 2. Create secondary client and fetch synchronised objects.
        secondary_client = boto3.resource("s3",
                                          verify=False,
                                          endpoint_url=secondary_endpoint,
                                          aws_access_key_id=access_key,
                                          aws_secret_access_key=secret_key)

        # 3. Verify Data Integrity
        # fetch_rgw_object has internal retry so waiting for sync beforehand
        # is not required for post migration object sync.
        pre_migration_data = self.fetch_rgw_object(
            secondary_client, container_name, 'prefile'
        )
        post_migration_data = self.fetch_rgw_object(
            secondary_client, container_name, 'postfile'
        )

        # 4. Verify Syncronisation works and objects are replicated
        self.assertEqual(pre_migration_data, obj_data)
        self.assertEqual(post_migration_data, obj_data)

        logging.info('Checking multisite failover/failback')
        # Failover Scenario, Promote Secondary-Ceph-RadosGW to Primary
        self.promote_rgw_to_primary(self.secondary_rgw_app)

        # Wait for Sites to be syncronised.
        self.wait_for_status(self.primary_rgw_app, is_primary=False)
        self.wait_for_status(self.secondary_rgw_app, is_primary=True)

        # IO Test
        container = 'failover-container'
        test_data = 'Test data from Zaza on Secondary'
        secondary_client.Bucket(container).create()
        secondary_object = secondary_client.Object(container, 'testfile')
        secondary_object.put(
            Body=test_data
        )
        secondary_content = secondary_object.get()[
            'Body'
        ].read().decode('UTF-8')

        # Recovery scenario, reset ceph-rgw as primary.
        self.promote_rgw_to_primary(self.primary_rgw_app)
        self.wait_for_status(self.primary_rgw_app, is_primary=True)
        self.wait_for_status(self.secondary_rgw_app, is_primary=False)

        # Fetch Syncronised copy of testfile from primary site.
        primary_content = self.fetch_rgw_object(
            primary_client, container, 'testfile'
        )

        # Verify Data Integrity.
        self.assertEqual(secondary_content, primary_content)

        # Scaledown and verify replication has stopped.
        logging.info('Checking multisite scaledown')
        zaza_model.remove_relation(
            self.primary_rgw_app,
            self.primary_rgw_app + ":primary",
            self.secondary_rgw_app + ":secondary"
        )

        # wait for sync stop
        self.wait_for_status(self.primary_rgw_app, sync_expected=False)
        self.wait_for_status(self.secondary_rgw_app, sync_expected=False)

        # Refresh client and verify objects are not replicating.
        primary_client = boto3.resource("s3",
                                        verify=False,
                                        endpoint_url=primary_endpoint,
                                        aws_access_key_id=access_key,
                                        aws_secret_access_key=secret_key)
        secondary_client = boto3.resource("s3",
                                          verify=False,
                                          endpoint_url=secondary_endpoint,
                                          aws_access_key_id=access_key,
                                          aws_secret_access_key=secret_key)

        # IO Test
        container = 'scaledown-container'
        test_data = 'Scaledown Test data'
        secondary_client.Bucket(container).create()
        secondary_object = secondary_client.Object(container, 'scaledown')
        secondary_object.put(
            Body=test_data
        )

        # Since bucket is not replicated.
        with self.assertRaises(botocore.exceptions.ClientError):
            primary_content = self.fetch_rgw_object(
                primary_client, container, 'scaledown'
            )

        # Cleanup of scaledown resources and synced resources.
        self.purge_bucket(self.secondary_rgw_app, container)
        self.purge_bucket(self.secondary_rgw_app, 'zaza-container')
        self.purge_bucket(self.secondary_rgw_app, 'failover-container')


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
        prometheus_mon_count = _get_mon_count_from_prometheus(
            zaza_model.get_unit_public_address(unit))
        self.assertTrue(0 < int(prometheus_mon_count))


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
                            self.assertEqual(pd['options'][k], v)
                            log_func("['options']['{}'] == {}".format(k, v))
                    for k, v in expected_properties.items():
                        if k == 'options':
                            continue
                        self.assertEqual(pd[k], v)
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


class CephAuthTest(unittest.TestCase):
    """Ceph auth tests (user creation and deletion)."""

    def test_ceph_auth(self):
        """Test creating and deleting user."""
        logging.info('Creating user and exported keyring...')
        action_obj = zaza_model.run_action_on_leader(
            'ceph-mon',
            'get-or-create-user',
            action_params={'username': 'sandbox',
                           'mon-caps': 'allow r',
                           'osd-caps': 'allow r'}
        )
        logging.debug('Result of action: {}'.format(action_obj))
        create_results = json.loads(action_obj.data['results']['message'])

        logging.info('Getting existing user and exported keyring...')
        action_obj = zaza_model.run_action_on_leader(
            'ceph-mon',
            'get-or-create-user',
            action_params={'username': 'sandbox'}
        )
        logging.debug('Result of action: {}'.format(action_obj))
        get_results = json.loads(action_obj.data['results']['message'])

        self.assertEqual(get_results, create_results)

        logging.info('Deleting existing user...')
        action_obj = zaza_model.run_action_on_leader(
            'ceph-mon',
            'delete-user',
            action_params={'username': 'sandbox'}
        )
        logging.debug('Result of action: {}'.format(action_obj))
        delete_results = action_obj.data['results']['message']
        self.assertEqual(delete_results, "updated\n")

        logging.info('Deleting non-existing user...')
        action_obj = zaza_model.run_action_on_leader(
            'ceph-mon',
            'delete-user',
            action_params={'username': 'sandbox'}
        )
        logging.debug('Result of action: {}'.format(action_obj))
        delete_results = action_obj.data['results']['message']
        self.assertEqual(delete_results,
                         "entity client.sandbox does not exist\n")


class CephMonActionsTest(test_utils.BaseCharmTest):
    """Test miscellaneous actions of the ceph-mon charm."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph-mon actions."""
        super(CephMonActionsTest, cls).setUpClass()
        # Allow mons to delete pools.
        zaza_model.run_on_unit(
            'ceph-mon/0',
            "ceph tell mon.\\* injectargs '--mon-allow-pool-delete=true'"
        )

    def _get_osd_weight(self, osd, unit):
        """Fetch the CRUSH weight of an OSD."""
        cmd = 'sudo ceph osd crush tree --format=json'
        result = zaza_model.run_on_unit(unit, cmd)
        self.assertEqual(int(result.get('Code')), 0)

        tree = json.loads(result.get('Stdout'))
        for node in tree['nodes']:
            if node.get('name') == osd:
                return node['crush_weight']

    def test_reweight_osd(self):
        """Test the change-osd-weight action."""
        unit = 'ceph-mon/0'
        osd = 0
        osd_str = 'osd.' + str(osd)
        weight = 700
        prev_weight = self._get_osd_weight(osd_str, unit)
        try:
            action_obj = zaza_model.run_action(
                unit_name=unit,
                action_name='change-osd-weight',
                action_params={'osd': osd, 'weight': 700}
            )
            zaza_utils.assertActionRanOK(action_obj)
            self.assertEqual(weight, self._get_osd_weight(osd_str, unit))
        finally:
            # Reset the weight.
            zaza_model.run_action(
                unit_name=unit,
                action_name='change-osd-weight',
                action_params={'osd': osd, 'weight': prev_weight}
            )

    def test_copy_pool(self):
        """Test the copy-pool (and list-pool) action."""
        unit = 'ceph-mon/0'
        logging.debug('Creating secondary test pool')
        cmd = 'sudo ceph osd pool create test2 32'
        cmd2 = 'sudo ceph osd pool create test3 32'
        try:
            result = zaza_model.run_on_unit(unit, cmd)
            self.assertEqual(int(result.get('Code')), 0)
            result = zaza_model.run_on_unit(unit, cmd2)
            self.assertEqual(int(result.get('Code')), 0)

            action_obj = zaza_model.run_action(
                unit_name=unit,
                action_name='list-pools',
                action_params={}
            )
            zaza_utils.assertActionRanOK(action_obj)
            self.assertIn('test2', action_obj.data['results']['message'])
            self.assertIn('test3', action_obj.data['results']['message'])

            logging.debug('Copying test pool')
            action_obj = zaza_model.run_action(
                unit_name=unit,
                action_name='copy-pool',
                action_params={'source': 'test2', 'target': 'test3'}
            )
            zaza_utils.assertActionRanOK(action_obj)
        finally:
            # Clean up our mess.
            zaza_model.run_on_unit(
                unit,
                ('sudo ceph osd pool delete test2 test2 '
                 '--yes-i-really-really-mean-it')
            )
            zaza_model.run_on_unit(
                unit,
                ('sudo ceph osd pool delete test3 test3 '
                 '--yes-i-really-really-mean-it')
            )
