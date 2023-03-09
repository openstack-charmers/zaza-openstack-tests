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

import logging
import math

import boto3
import zaza.model as model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.tempest.tests as tempest_tests


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

    def test_412_image_conversion(self):
        """Check image-conversion config.

        When image-conversion config is enabled glance will convert images
        to raw format, this is only performed for interoperable image import
        docs.openstack.org/glance/train/admin/interoperable-image-import.html
        image conversion is done at server-side for better image handling
        """
        current_release = openstack_utils.get_os_release()
        bionic_stein = openstack_utils.get_os_release('bionic_stein')
        if current_release < bionic_stein:
            self.skipTest('image-conversion config is supported since '
                          'bionic_stein or newer versions')

        with self.config_change({'image-conversion': 'false'},
                                {'image-conversion': 'true'}):
            image_url = openstack_utils.find_cirros_image(arch='x86_64')
            image = openstack_utils.create_image(
                self.glance_client,
                image_url,
                'cirros-test-import',
                force_import=True)

            disk_format = self.glance_client.images.get(image.id).disk_format
            self.assertEqual('raw', disk_format)

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


class GlanceCephRGWBackendTest(test_utils.OpenStackBaseTest):
    """Encapsulate glance tests using the Ceph RGW backend.

    It validates the Ceph RGW backend in glance, which uses the Swift API.
    """

    @classmethod
    def setUpClass(cls):
        """Run class setup for running glance tests."""
        super(GlanceCephRGWBackendTest, cls).setUpClass()

        swift_session = openstack_utils.get_keystone_session_from_relation(
            'ceph-radosgw')
        cls.swift = openstack_utils.get_swift_session_client(
            swift_session)
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session)

    def test_100_create_image(self):
        """Create an image and do a simple validation of it.

        The OpenStack Swift API is used to do the validation, since the Ceph
        Rados Gateway serves an API which is compatible with that.
        """
        image_name = 'zaza-ceph-rgw-image'
        openstack_utils.create_image(
            glance=self.glance_client,
            image_url=openstack_utils.find_cirros_image(arch='x86_64'),
            image_name=image_name,
            backend='swift')
        headers, containers = self.swift.get_account()
        self.assertEqual(len(containers), 1)
        container_name = containers[0].get('name')
        headers, objects = self.swift.get_container(container_name)
        images = openstack_utils.get_images_by_name(
            self.glance_client,
            image_name)
        self.assertEqual(len(images), 1)
        image = images[0]
        total_bytes = 0
        for ob in objects:
            if '{}-'.format(image['id']) in ob['name']:
                total_bytes = total_bytes + int(ob['bytes'])
        logging.info(
            'Checking glance image size {} matches swift '
            'image size {}'.format(image['size'], total_bytes))
        self.assertEqual(image['size'], total_bytes)
        openstack_utils.delete_image(self.glance_client, image['id'])


class GlanceExternalS3Test(test_utils.OpenStackBaseTest):
    """Encapsulate glance tests using an external S3 backend."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running glance tests with S3 backend."""
        super(GlanceExternalS3Test, cls).setUpClass()
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session
        )

        configs = model.get_application_config("glance")
        cls.s3_store_host = configs["s3-store-host"]["value"]
        cls.s3_store_access_key = configs["s3-store-access-key"]["value"]
        cls.s3_store_secret_key = configs["s3-store-secret-key"]["value"]
        cls.s3_store_bucket = configs["s3-store-bucket"]["value"]

    def test_100_create_delete_image(self):
        """Create an image and do a simple validation of it.

        Validate the size of the image in both Glance API and actual S3 bucket.
        """
        image_name = "zaza-s3-test-image"
        openstack_utils.create_image(
            glance=self.glance_client,
            image_url=openstack_utils.find_cirros_image(arch="x86_64"),
            image_name=image_name,
            backend="s3",
        )
        images = openstack_utils.get_images_by_name(
            self.glance_client, image_name
        )
        self.assertEqual(len(images), 1)
        image = images[0]

        s3_client = boto3.client(
            "s3",
            endpoint_url=self.s3_store_host,
            aws_access_key_id=self.s3_store_access_key,
            aws_secret_access_key=self.s3_store_secret_key,
        )
        response = s3_client.head_object(
            Bucket=self.s3_store_bucket, Key=image["id"]
        )
        logging.info(
            "Checking glance image size {} matches S3 object's ContentLength "
            "{}".format(image["size"], response["ContentLength"])
        )
        self.assertEqual(image["size"], response["ContentLength"])
        openstack_utils.delete_image(self.glance_client, image["id"])


class GlanceCinderBackendTest(test_utils.OpenStackBaseTest):
    """Encapsulate glance tests using cinder backend."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running glance tests with cinder backend."""
        super(GlanceCinderBackendTest, cls).setUpClass()
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session)
        cls.cinder_client = openstack_utils.get_cinder_session_client(
            cls.keystone_session)

    def test_100_create_delete_image(self):
        """Create an image and do a simple validation of it.

        Validate the size of the image in both Glance API and Cinder API.
        """
        image_name = "zaza-cinder-test-image"
        openstack_utils.create_image(
            glance=self.glance_client,
            image_url=openstack_utils.find_cirros_image(arch="x86_64"),
            image_name=image_name,
            backend="cinder",
        )
        images = openstack_utils.get_images_by_name(
            self.glance_client, image_name)
        self.assertEqual(len(images), 1)
        image = images[0]

        volume_name = 'image-'+image["id"]
        volumes = openstack_utils.get_volumes_by_name(
            self.cinder_client, volume_name)
        self.assertEqual(len(volumes), 1)
        volume = volumes[0]

        logging.info(
            "Checking glance image size {} matches volume size {} "
            "GB".format(image["size"], volume.size))
        image_size_in_gb = int(math.ceil(float(image["size"]) / 1024 ** 3))
        self.assertEqual(image_size_in_gb, volume.size)
        openstack_utils.delete_image(self.glance_client, image["id"])


class GlanceTempestTestK8S(tempest_tests.TempestTestScaleK8SBase):
    """Test glance k8s scale out and scale back."""

    application_name = "glance"
