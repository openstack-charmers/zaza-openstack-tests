# Copyright 2020 Canonical Ltd.
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

"""Encapsulate CephFS testing."""

import logging
import json
import subprocess
from tenacity import retry, Retrying, stop_after_attempt, wait_exponential
import unittest
import zaza
import zaza.model as model
import zaza.openstack.charm_tests.test_utils as test_utils


class CephFSTests(unittest.TestCase):
    """Encapsulate CephFS tests."""

    mounts_share = False
    mount_dir = '/mnt/cephfs'

    def tearDown(self):
        """Cleanup after running tests."""
        if self.mounts_share:
            for unit in ['ubuntu/0', 'ubuntu/1']:
                try:
                    zaza.utilities.generic.run_via_ssh(
                        unit_name=unit,
                        cmd='sudo fusermount -u {0} && sudo rmdir {0}'.format(
                            self.mount_dir))
                except subprocess.CalledProcessError:
                    logging.warning(
                        "Failed to cleanup mounts on {}".format(unit))

    def _mount_share(self, unit_name: str,
                     retry: bool = True):
        self._install_dependencies(unit_name)
        self._install_keyring(unit_name)
        ssh_cmd = (
            'sudo mkdir -p {0} && '
            'sudo ceph-fuse {0}'.format(self.mount_dir)
        )
        if retry:
            for attempt in Retrying(
                    stop=stop_after_attempt(5),
                    wait=wait_exponential(multiplier=3,
                                          min=2, max=10)):
                with attempt:
                    zaza.utilities.generic.run_via_ssh(
                        unit_name=unit_name,
                        cmd=ssh_cmd)
        else:
            zaza.utilities.generic.run_via_ssh(
                unit_name=unit_name,
                cmd=ssh_cmd)
        self.mounts_share = True

    def _install_keyring(self, unit_name: str):

        keyring = model.run_on_leader(
            'ceph-mon', 'cat /etc/ceph/ceph.client.admin.keyring')['Stdout']
        config = model.run_on_leader(
            'ceph-mon', 'cat /etc/ceph/ceph.conf')['Stdout']
        commands = [
            'sudo mkdir -p /etc/ceph',
            "echo '{}' | sudo tee /etc/ceph/ceph.conf".format(config),
            "echo '{}' | "
            'sudo tee /etc/ceph/ceph.client.admin.keyring'.format(keyring)
        ]
        for cmd in commands:
            zaza.utilities.generic.run_via_ssh(
                unit_name=unit_name,
                cmd=cmd)

    def _install_dependencies(self, unit: str):
        zaza.utilities.generic.run_via_ssh(
            unit_name=unit,
            cmd='sudo apt-get install -yq ceph-fuse')

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(CephFSTests, cls).setUpClass()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=3, min=2, max=10))
    def _write_testing_file_on_instance(self, instance_name: str):
        zaza.utilities.generic.run_via_ssh(
            unit_name=instance_name,
            cmd='echo -n "test" | sudo tee {}/test'.format(self.mount_dir))

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=3, min=2, max=10))
    def _verify_testing_file_on_instance(self, instance_name: str):
        output = zaza.model.run_on_unit(
            instance_name, 'sudo cat {}/test'.format(self.mount_dir))['Stdout']
        self.assertEqual('test', output.strip())

    def test_cephfs_share(self):
        """Test that CephFS shares can be accessed on two instances.

        1. Spawn two servers
        2. mount it on both
        3. write a file on one
        4. read it on the other
        5. profit
        """
        self._mount_share('ubuntu/0')
        self._mount_share('ubuntu/1')

        self._write_testing_file_on_instance('ubuntu/0')
        self._verify_testing_file_on_instance('ubuntu/1')

    def test_conf(self):
        """Test ceph to ensure juju config options are properly set."""
        self.TESTED_UNIT = 'ceph-fs/0'

        def _get_conf():
            """get/parse ceph daemon response into dict.

            :returns dict: Current configuration of the Ceph MDS daemon
            :rtype: dict
            """
            cmd = "sudo ceph daemon mds.$HOSTNAME config show"
            conf = model.run_on_unit(self.TESTED_UNIT, cmd)
            return json.loads(conf['Stdout'])

        @retry(wait=wait_exponential(multiplier=1, min=4, max=10),
               stop=stop_after_attempt(10))
        def _change_conf_check(mds_config):
            """Change configs, then assert to ensure config was set.

            Doesn't return a value.
            """
            model.set_application_config('ceph-fs', mds_config)
            results = _get_conf()
            self.assertEqual(
                results['mds_cache_memory_limit'],
                mds_config['mds-cache-memory-limit'])
            self.assertAlmostEqual(
                float(results['mds_cache_reservation']),
                float(mds_config['mds-cache-reservation']))
            self.assertAlmostEqual(
                float(results['mds_health_cache_threshold']),
                float(mds_config['mds-health-cache-threshold']))

        # ensure defaults are set
        mds_config = {'mds-cache-memory-limit': '4294967296',
                      'mds-cache-reservation': '0.05',
                      'mds-health-cache-threshold': '1.5'}
        _change_conf_check(mds_config)

        # change defaults
        mds_config = {'mds-cache-memory-limit': '8589934592',
                      'mds-cache-reservation': '0.10',
                      'mds-health-cache-threshold': '2'}
        _change_conf_check(mds_config)

        # Restore config to keep tests idempotent
        mds_config = {'mds-cache-memory-limit': '4294967296',
                      'mds-cache-reservation': '0.05',
                      'mds-health-cache-threshold': '1.5'}
        _change_conf_check(mds_config)


def _indent(text, amount, ch=' '):
    padding = amount * ch
    return ''.join(padding+line for line in text.splitlines(True))


class CharmOperationTest(test_utils.BaseCharmTest):
    """CephFS Charm operation tests."""

    def test_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped, then resume and check
        they are started.
        """
        services = ['ceph-mds']
        with self.pause_resume(services):
            logging.info('Testing pause resume (services="{}")'
                         .format(services))
