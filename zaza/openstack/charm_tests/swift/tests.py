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

"""Encapsulate swift testing."""

import logging
import pprint
import tenacity

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.configure.guest
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.utilities.swift as swift_utils

import boto3


class SwiftImageCreateTest(test_utils.OpenStackBaseTest):
    """Test swift proxy via glance."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(SwiftImageCreateTest, cls).setUpClass()
        cls.image_name = 'zaza-swift-lts'
        swift_session = openstack_utils.get_keystone_session_from_relation(
            'swift-proxy')

        cls.swift = openstack_utils.get_swift_session_client(
            swift_session)
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session)

    def test_100_create_image(self):
        """Create an image and do simple validation of image in swift."""
        glance_setup.add_lts_image(image_name=self.image_name)
        headers, containers = self.swift.get_account()
        self.assertEqual(len(containers), 1)
        container_name = containers[0].get('name')
        headers, objects = self.swift.get_container(container_name)
        images = openstack_utils.get_images_by_name(
            self.glance_client,
            self.image_name)
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


class SwiftProxyTests(test_utils.OpenStackBaseTest):
    """Tests specific to swift proxy."""

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(['swift-proxy-server', 'haproxy', 'apache2',
                                'memcached']):
            logging.info("Testing pause resume")

    def test_903_disk_usage_action(self):
        """Check diskusage action runs."""
        logging.info('Running diskusage action on leader')
        action = zaza.model.run_action_on_leader(
            'swift-proxy',
            'diskusage',
            action_params={})
        self.assertEqual(action.status, "completed")


class SwiftProxyMultiZoneTests(test_utils.OpenStackBaseTest):
    """Tests specific to swift proxy in multi zone environment."""

    RESOURCE_PREFIX = 'zaza-swift-proxy-multizone-tests'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        cls.region1_model_alias = 'swift_gr_region1'
        cls.region1_proxy_app = 'swift-proxy-region1'
        super(SwiftProxyMultiZoneTests, cls).setUpClass(
            application_name=cls.region1_proxy_app,
            model_alias=cls.region1_model_alias)
        cls.region1_model_name = cls.model_aliases[cls.region1_model_alias]
        cls.storage_topology = swift_utils.get_swift_storage_topology(
            model_name=cls.region1_model_name)
        cls.swift_session = openstack_utils.get_keystone_session_from_relation(
            cls.region1_proxy_app,
            model_name=cls.region1_model_name)
        cls.swift_region1 = openstack_utils.get_swift_session_client(
            cls.swift_session,
            region_name='RegionOne')

    @classmethod
    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=16, max=600),
        reraise=True,
        stop=tenacity.stop_after_attempt(10))
    def tearDown(cls):
        """Remove test resources.

        The retry decorator is needed as it is luck of the draw as to whether
        a delete of a newly created container will result in a 404. Retrying
        will eventually result in the delete being accepted.
        """
        logging.info('Running teardown')
        resp_headers, containers = cls.swift_region1.get_account()
        logging.info('Found containers {}'.format(containers))
        for container in containers:
            if not container['name'].startswith(cls.RESOURCE_PREFIX):
                continue
            for obj in cls.swift_region1.get_container(container['name'])[1]:
                logging.info('Deleting object {} from {}'.format(
                    obj['name'],
                    container['name']))
                cls.swift_region1.delete_object(
                    container['name'],
                    obj['name'])
            logging.info('Deleting container {}'.format(container['name']))
            cls.swift_region1.delete_container(container['name'])

    def test_900_remove_device_action(self):
        """Check remove-device action runs.

        This tests destroys the environment and should be run as last.
        """
        logging.info('Running remove-devices action on leader')
        action = zaza.model.run_action_on_leader(
            'swift-proxy-region1',
            'remove-devices',
            action_params={
                'ring': 'account',
                'search-value': 'r1z3'
            })
        logging.info(action)
        self.assertEqual(action.status, "completed")

        container_name, obj_name, _ = swift_utils.create_object(
            self.swift_region1,
            self.region1_proxy_app,
            self.storage_topology,
            self.RESOURCE_PREFIX,
            model_name=self.region1_model_name)
        # Check object is accessible from the region proxy.
        response = self.swift_region1.head_object(container_name, obj_name)
        self.assertIsNotNone(response)


class SwiftStorageTests(test_utils.OpenStackBaseTest):
    """Tests specific to swift storage."""

    def test_901_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        services = ['swift-account-server',
                    'swift-account-auditor',
                    'swift-account-reaper',
                    'swift-container-server',
                    'swift-container-auditor',
                    'swift-container-updater',
                    'swift-object-server',
                    'swift-object-auditor',
                    'swift-object-updater',
                    'swift-container-sync']

        current_os_release = openstack_utils.get_os_release()
        focal_victoria = openstack_utils.get_os_release('focal_victoria')
        if current_os_release < focal_victoria:
            services += ['swift-account-replicator',
                         'swift-container-replicator',
                         'swift-object-replicator']
        else:
            services += ['swift-account-server',
                         'swift-container-server',
                         'swift-object-server']

        with self.pause_resume(services):
            logging.info("Testing pause resume")


class SwiftGlobalReplicationTests(test_utils.OpenStackBaseTest):
    """Test swift global replication."""

    RESOURCE_PREFIX = 'zaza-swift-gr-tests'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        cls.region1_model_alias = 'swift_gr_region1'
        cls.region1_proxy_app = 'swift-proxy-region1'
        cls.region2_model_alias = 'swift_gr_region2'
        cls.region2_proxy_app = 'swift-proxy-region2'
        super(SwiftGlobalReplicationTests, cls).setUpClass(
            application_name=cls.region1_proxy_app,
            model_alias=cls.region1_model_alias)
        cls.region1_model_name = cls.model_aliases[cls.region1_model_alias]
        cls.region2_model_name = cls.model_aliases[cls.region2_model_alias]
        cls.storage_topology = swift_utils.get_swift_storage_topology(
            model_name=cls.region1_model_name)
        cls.storage_topology.update(
            swift_utils.get_swift_storage_topology(
                model_name=cls.region2_model_name))
        cls.swift_session = openstack_utils.get_keystone_session_from_relation(
            cls.region1_proxy_app,
            model_name=cls.region1_model_name)
        cls.swift_region1 = openstack_utils.get_swift_session_client(
            cls.swift_session,
            region_name='RegionOne')
        cls.swift_region2 = openstack_utils.get_swift_session_client(
            cls.swift_session,
            region_name='RegionTwo')

    @classmethod
    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=16, max=600),
        reraise=True,
        stop=tenacity.stop_after_attempt(10))
    def tearDown(cls):
        """Remove test resources.

        The retry decorator is needed as it is luck of the draw as to whether
        a delete of a newly created container will result in a 404. Retrying
        will eventually result in the delete being accepted.
        """
        logging.info('Running teardown')
        resp_headers, containers = cls.swift_region1.get_account()
        logging.info('Found containers {}'.format(containers))
        for container in containers:
            if not container['name'].startswith(cls.RESOURCE_PREFIX):
                continue
            for obj in cls.swift_region1.get_container(container['name'])[1]:
                logging.info('Deleting object {} from {}'.format(
                    obj['name'],
                    container['name']))
                cls.swift_region1.delete_object(
                    container['name'],
                    obj['name'])
            logging.info('Deleting container {}'.format(container['name']))
            cls.swift_region1.delete_container(container['name'])

    def test_901_two_regions_any_zones_two_replicas(self):
        """Create an object with two replicas across two regions.

        We set write affinity to write the first copy in the local
        region of the proxy used to perform the write, the other
        replica will land in the remote region.
        """
        swift_utils.apply_proxy_config(
            self.region1_proxy_app,
            {
                'write-affinity': 'r1',
                'write-affinity-node-count': '1',
                'replicas': '2'},
            self.region1_model_name)
        swift_utils.apply_proxy_config(
            self.region2_proxy_app,
            {
                'write-affinity': 'r2',
                'write-affinity-node-count': '1',
                'replicas': '2'},
            self.region2_model_name)
        logging.info('Proxy configs updated in both regions')
        container_name, obj_name, obj_replicas = swift_utils.create_object(
            self.swift_region1,
            self.region1_proxy_app,
            self.storage_topology,
            self.RESOURCE_PREFIX,
            model_name=self.region1_model_name)
        # Check object is accessible from other regions proxy.
        self.swift_region2.head_object(container_name, obj_name)
        # Check there is at least one replica in each region.
        self.assertEqual(
            sorted(obj_replicas.distinct_regions),
            [1, 2])
        # Check there are two relicas
        self.assertEqual(
            len(obj_replicas.all_zones),
            2)

    def test_902_two_regions_any_zones_three_replicas(self):
        """Create an object with three replicas across two regions.

        We set write affinity to write the first copy in the local
        region of the proxy used to perform the write, at least one
        of the other two replicas will end up in the opposite region
        based on primary partitions in the ring.
        """
        swift_utils.apply_proxy_config(
            self.region1_proxy_app,
            {
                'write-affinity': 'r1',
                'write-affinity-node-count': '1',
                'replicas': '3'},
            self.region1_model_name)
        swift_utils.apply_proxy_config(
            self.region2_proxy_app,
            {
                'write-affinity': 'r2',
                'write-affinity-node-count': '1',
                'replicas': '3'},
            self.region2_model_name)
        logging.info('Proxy configs updated in both regions')
        container_name, obj_name, obj_replicas = swift_utils.create_object(
            self.swift_region1,
            self.region1_proxy_app,
            self.storage_topology,
            self.RESOURCE_PREFIX,
            model_name=self.region1_model_name)
        # Check object is accessible from other regions proxy.
        self.swift_region2.head_object(container_name, obj_name)
        # Check there is at least one replica in each region.
        self.assertEqual(
            sorted(obj_replicas.distinct_regions),
            [1, 2])
        # Check there are three relicas
        self.assertEqual(
            len(obj_replicas.all_zones),
            3)


class S3APITest(test_utils.OpenStackBaseTest):
    """Test object storage S3 API."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(S3APITest, cls).setUpClass()

        session = openstack_utils.get_overcloud_keystone_session()
        ks_client = openstack_utils.get_keystone_session_client(session)

        # Get token data so we can glean our user_id and project_id
        token_data = ks_client.tokens.get_token_data(session.get_token())
        project_id = token_data['token']['project']['id']
        user_id = token_data['token']['user']['id']

        # Store URL to service providing S3 compatible API
        for entry in token_data['token']['catalog']:
            if entry['type'] == 's3':
                for endpoint in entry['endpoints']:
                    if endpoint['interface'] == 'public':
                        cls.s3_region = endpoint['region']
                        cls.s3_endpoint = endpoint['url']

        # Create AWS compatible application credentials in Keystone
        cls.ec2_creds = ks_client.ec2.create(user_id, project_id)

    def test_901_s3_list_buckets(self):
        """Use S3 API to list buckets."""
        # We use a mix of the high- and low-level API with common arguments
        kwargs = {
            'region_name': self.s3_region,
            'aws_access_key_id': self.ec2_creds.access,
            'aws_secret_access_key': self.ec2_creds.secret,
            'endpoint_url': self.s3_endpoint,
            'verify': self.cacert,
        }
        s3_client = boto3.client('s3', **kwargs)
        s3 = boto3.resource('s3', **kwargs)

        # Create bucket
        bucket_name = 'zaza-s3'
        bucket = s3.Bucket(bucket_name)
        bucket.create()

        # Validate its presence
        bucket_list = s3_client.list_buckets()
        logging.info(pprint.pformat(bucket_list))
        for bkt in bucket_list['Buckets']:
            if bkt['Name'] == bucket_name:
                break
        else:
            AssertionError('Bucket "{}" not found'.format(bucket_name))

        # Delete bucket
        bucket.delete()

        # Validate its absence
        bucket_list = s3_client.list_buckets()
        logging.info(pprint.pformat(bucket_list))
        for bkt in bucket_list['Buckets']:
            assert bkt['Name'] != bucket_name
