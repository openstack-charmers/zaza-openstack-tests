#!/usr/bin/env python3
#
# Copyright 2021 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Encapsulate magnum testing."""

import logging
import urllib

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.utilities.generic as generic_utils

from zaza.openstack.charm_tests.magnum.setup import IMAGE_NAME

# Resource and name constants
CLUSTER_NAME = 'test-kubernetes'
TEMPLATE_NAME = 'test-kubernetes-template'
FLAVOR_NAME = 'm1.small'


class MagnumBasicDeployment(test_utils.OpenStackBaseTest):
    """Encapsulate Magnum tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running magnum tests."""
        super(MagnumBasicDeployment, cls).setUpClass()
        cls.keystone_session = openstack_utils.get_overcloud_keystone_session()
        cls.magnum_client = openstack_utils.get_magnum_session_client(
            cls.keystone_session)
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session)

    @property
    def services(self):
        """Return a list services for the selected OpenStack release.

        :returns: List of services
        :rtype: [str]
        """
        services = ['magnum-api', 'magnum-conductor']
        return services

    def test_410_magnum_cluster_create_delete(self):
        """Create cluster, confirm nova compute resource, delete cluster."""
        # Verify new image name
        images_list = list(self.glance_client.images.list())
        self.assertEqual(images_list[0].name, IMAGE_NAME,
                         "Magnum image not found")

        # Create magnum template
        template_fields = {
            'name': TEMPLATE_NAME,
            'image_id': IMAGE_NAME,
            'external_network_id': openstack_utils.EXT_NET,
            'dns_nameserver': '1.1.1.1',
            'master_flavor_id': FLAVOR_NAME,
            'flavor_id': FLAVOR_NAME,
            'coe': 'kubernetes'
        }

        logging.info('Creating magnum cluster template...')

        template = self.magnum_client.cluster_templates.create(
            **template_fields)
        logging.info('Cluster template data: {}'.format(template))

        # Create a magnum cluster from a magnum template, verify its status
        logging.info('Creating magnum cluster...')
        # Create the cluster
        cluster_fields = {
            'name': CLUSTER_NAME,
            'cluster_template_id': template.uuid,
            'master_count': 1,
            'node_count': 1,
            'keypair': 'zaza'
        }

        cluster = self.magnum_client.clusters.create(**cluster_fields)
        logging.info('Cluster data: {}'.format(cluster))

        # Confirm stack reaches COMPLETE status.
        openstack_utils.resource_reaches_status(
            self.magnum_client.clusters,
            cluster.uuid,
            expected_status="CREATE_COMPLETE",
            msg="Cluster status wait",
            stop_after_attempt=20,
            wait_iteration_max_time=600,
            wait_exponential_multiplier=2)

        # List cluster
        clusters = list(self.magnum_client.clusters.list())
        logging.info('All clusters: {}'.format(clusters))

        # Get cluster information
        cluster = self.magnum_client.clusters.get(CLUSTER_NAME)

        # Check Kubernetes api address
        api_address = urllib.parse.urlparse(cluster.api_address)
        api_status = generic_utils.is_port_open(api_address.port,
                                                api_address.hostname)
        self.assertTrue(api_status, 'Kubernetes API is unavailable')

        # Delete cluster
        logging.info('Deleting magnum cluster...')
        openstack_utils.delete_resource(self.magnum_client.clusters,
                                        CLUSTER_NAME, msg="magnum cluster")

        # Delete template
        logging.info('Deleting magnum cluster template...')
        openstack_utils.delete_resource(self.magnum_client.cluster_templates,
                                        TEMPLATE_NAME,
                                        msg="magnum cluster template")

    def test_900_magnum_restart_on_config_change(self):
        """Verify the specified services are restarted when config changes."""
        logging.info('Testing restart on configuration change')

        # Expected default and alternate values
        set_default = {'cert-manager-type': 'barbican'}
        set_alternate = {'cert-manager-type': 'x509keypair'}

        # Config file affected by juju set config change
        conf_file = '/etc/magnum/magnum.conf'

        # Make config change, check for service restarts
        logging.info('Making configuration change')
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            None,
            None,
            self.services)

    def test_910_pause_and_resume(self):
        """Run services pause and resume tests."""
        logging.info('Checking pause and resume actions...')

        logging.info('Skipping pause resume test LP: #1886202...')
        return
        with self.pause_resume(self.services):
            logging.info("Testing pause resume")
