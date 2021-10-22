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
from tenacity import Retrying, stop_after_attempt, wait_exponential

import zaza.model as model
import zaza.openstack.charm_tests.neutron.tests as neutron_tests
import zaza.openstack.charm_tests.nova.utils as nova_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.configure.guest as guest
import zaza.openstack.utilities.openstack as openstack_utils


class CephFSTests(test_utils.OpenStackBaseTest):
    """Encapsulate CephFS tests."""

    RESOURCE_PREFIX = 'zaza-cephfstests'
    INSTANCE_USERDATA = """#cloud-config
packages:
- ceph-fuse
- python
mounts:
  - [ 'none', '/mnt/cephfs', 'fuse.ceph', 'ceph.id=admin,ceph.conf=/etc/ceph/ceph.conf,_netdev,defaults', '0', '0' ]
write_files:
-   content: |
{}
    path: /etc/ceph/ceph.conf
-   content: |
{}
    path: /etc/ceph/ceph.client.admin.keyring
""" # noqa

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(CephFSTests, cls).setUpClass()

    def test_cephfs_share(self):
        """Test that CephFS shares can be accessed on two instances.

        1. Spawn two servers
        2. mount it on both
        3. write a file on one
        4. read it on the other
        5. profit
        """
        keyring = model.run_on_leader(
            'ceph-mon', 'cat /etc/ceph/ceph.client.admin.keyring')['Stdout']
        conf = model.run_on_leader(
            'ceph-mon', 'cat /etc/ceph/ceph.conf')['Stdout']
        # Spawn Servers
        instance_1, instance_2 = self.launch_guests(
            userdata=self.INSTANCE_USERDATA.format(
                _indent(conf, 8),
                _indent(keyring, 8)))

        # Write a file on instance_1
        def verify_setup(stdin, stdout, stderr):
            status = stdout.channel.recv_exit_status()
            self.assertEqual(status, 0)

        fip_1 = neutron_tests.floating_ips_from_instance(instance_1)[0]
        fip_2 = neutron_tests.floating_ips_from_instance(instance_2)[0]
        username = guest.boot_tests['bionic']['username']
        password = guest.boot_tests['bionic'].get('password')
        privkey = openstack_utils.get_private_key(nova_utils.KEYPAIR_NAME)

        for attempt in Retrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10)):
            with attempt:
                openstack_utils.ssh_command(
                    username, fip_1, 'instance-1',
                    'sudo mount -a && '
                    'echo "test" | sudo tee /mnt/cephfs/test',
                    password=password, privkey=privkey, verify=verify_setup)

        def verify(stdin, stdout, stderr):
            status = stdout.channel.recv_exit_status()
            self.assertEqual(status, 0)
            out = ""
            for line in iter(stdout.readline, ""):
                out += line
            self.assertEqual(out, "test\n")

        openstack_utils.ssh_command(
            username, fip_2, 'instance-2',
            'sudo mount -a && '
            'sudo cat /mnt/cephfs/test',
            password=password, privkey=privkey, verify=verify)


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

    def test_scaling(self):
        """Scale up and back the CephFS units."""
        mds = list(x.entity_id for x in model.get_units('ceph-fs'))
        mds_count = len(mds)
        logging.info('CephFS count is {}'.format(mds_count))
        model.add_unit('ceph-fs')
        model.block_until_unit_count('ceph-fs', mds_count + 1)
        model.block_until_all_units_idle(model_name=self.model_name)
        model.destroy_unit('ceph-fs', mds[0])
