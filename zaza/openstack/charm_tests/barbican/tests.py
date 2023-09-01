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

"""Encapsulate barbican testing."""

import logging

import barbicanclient.client as barbican_client
import zaza.openstack.charm_tests.tempest.tests as tempest_tests
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class BarbicanTest(test_utils.OpenStackBaseTest):
    """Run barbican specific tests."""

    _SERVICES = ['apache2', 'barbican-worker']

    def test_110_catalog_endpoints(self):
        """Verify that the endpoints are present in the catalog."""
        overcloud_auth = openstack_utils.get_overcloud_auth()
        keystone_client = openstack_utils.get_keystone_client(
            overcloud_auth)
        actual_endpoints = keystone_client.service_catalog.get_endpoints()
        for service_type in ('key-manager', 'identity'):
            actual_interfaces = [endpoint['interface'] for endpoint in
                                 actual_endpoints[service_type]]
            for expected_interface in ('internal', 'admin', 'public'):
                assert expected_interface in actual_interfaces

    def test_400_api_connection(self):
        """Simple api calls to check service is up and responding."""
        logging.info('Authenticating with the barbican endpoint')
        overcloud_auth = openstack_utils.get_overcloud_auth()
        keystone_client = openstack_utils.get_keystone_client(
            overcloud_auth)
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        barbican_endpoint = keystone_client.service_catalog.url_for(
            service_type='key-manager', interface='publicURL')
        barbican = barbican_client.Client(session=keystone_session,
                                          endpoint=barbican_endpoint)

        logging.info('Creating a secret')
        my_secret = barbican.secrets.create()
        my_secret.name = u'Random plain text password'
        my_secret.payload = u'password'

        logging.info('Storing the secret')
        my_secret_ref = my_secret.store()
        assert my_secret_ref is not None

        logging.info('Deleting the secret')
        my_secret.delete()

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        self.restart_on_changed_debug_oslo_config_file(
            '/etc/barbican/barbican.conf', self._SERVICES)

    def test_910_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(self._SERVICES):
            logging.info("Testing pause resume")


class BarbicanTempestTestK8S(tempest_tests.TempestTestScaleK8SBase):
    """Test barbican k8s scale out and scale back."""

    application_name = "barbican"
