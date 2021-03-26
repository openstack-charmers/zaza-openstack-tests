#!/usr/bin/env python3

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

"""Encapsulate glance testing."""

import json
import boto3
import logging

import zaza.model as model
import zaza.utilities.juju as juju
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.test_utils as test_utils


class GlanceTest(test_utils.OpenStackBaseTest):
    """Encapsulate glance tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running glance tests."""
        super(GlanceTest, cls).setUpClass()
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session)

    def test_410_glance_image_create_delete(self):
        """Create an image and then delete it."""
        image_url = openstack_utils.find_cirros_image(arch='x86_64')
        image = openstack_utils.create_image(
            self.glance_client,
            image_url,
            'cirrosimage')
        openstack_utils.delete_image(self.glance_client, image.id)

    def test_411_set_disk_format(self):
        """Change disk format and check.

        Change disk format and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        set_default = {
            'disk-formats': 'ami,ari,aki,vhd,vmdk,raw,qcow2,vdi,iso,root-tar'}
        set_alternate = {'disk-formats': 'qcow2'}

        # Config file affected by juju set config change
        conf_file = '/etc/glance/glance-api.conf'

        # Make config change, check for service restarts
        logging.debug('Setting disk format glance...')
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            {'image_format': {
                'disk_formats': [
                    'ami,ari,aki,vhd,vmdk,raw,qcow2,vdi,iso,root-tar']}},
            {'image_format': {'disk_formats': ['qcow2']}},
            ['glance-api'])

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change."""
        # Config file affected by juju set config change
        conf_file = '/etc/glance/glance-api.conf'

        # Services which are expected to restart upon config change
        services = {'glance-api': conf_file}
        current_release = openstack_utils.get_os_release()
        bionic_stein = openstack_utils.get_os_release('bionic_stein')
        if current_release < bionic_stein:
            services.update({'glance-registry': conf_file})

        # Make config change, check for service restarts
        logging.info('changing debug config')
        self.restart_on_changed_debug_oslo_config_file(
            conf_file,
            services)

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        self.pause_resume(['glance-api'])


class S3GlanceTest(test_utils.OpenStackBaseTest):
    """Encapsulate glance S3 tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running glance tests with S3 backend."""
        super(S3GlanceTest, cls).setUpClass()
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session)


    def test_s3_image_store(self):
        # Find existing user
        logging.info('Getting credentials')
        username = "'glance-s3-testuser'"
        cmd = "radosgw-admin user info --uid='glance-s3-testuser'"
        results = model.run_on_leader('ceph-mon', cmd)

        # Get access and secret keys
        stdout = json.loads(results['stdout'])
        keys = stdout['keys'][0]
        access_key = keys['access_key']
        secret_key = keys['secret_key']

        # Get S3 endpoint
        ip = juju.get_application_ip('ceph-radosgw')
        status = juju.get_application_status('ceph-radosgw')
        port = status.units['ceph-radosgw/0'].opened_ports[0].split('/')[0]
        endpoint = 'http://' + ip + ':' + port

        # Create boto client and verify image exists
        logging.info('Verifying image exists in S3 bucket')
        s3_client = boto3.client(
            's3',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=endpoint)
        objects = s3_client.list_objects(Bucket='glance-s3-test-bucket')
        self.assertTrue('Contents' in objects.keys())

