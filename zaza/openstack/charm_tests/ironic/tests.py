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

"""Encapsulate ironic testing."""

import logging

import ironicclient.client as ironic_client
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


def _get_ironic_client(ironic_api_version="1.58"):
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    ironic = ironic_client.Client(1, session=keystone_session,
                                  os_ironic_api_version=ironic_api_version)
    return ironic


class IronicTest(test_utils.OpenStackBaseTest):
    """Run Ironic specific tests."""

    _SERVICES = ['ironic-api']

    def test_110_catalog_endpoints(self):
        """Verify that the endpoints are present in the catalog."""
        overcloud_auth = openstack_utils.get_overcloud_auth()
        keystone_client = openstack_utils.get_keystone_client(
            overcloud_auth)
        actual_endpoints = keystone_client.service_catalog.get_endpoints()
        actual_interfaces = [endpoint['interface'] for endpoint in
                             actual_endpoints["baremetal"]]
        for expected_interface in ('internal', 'admin', 'public'):
            assert expected_interface in actual_interfaces

    def test_400_api_connection(self):
        """Simple api calls to check service is up and responding."""
        ironic = _get_ironic_client()

        logging.info('listing conductors')
        conductors = ironic.conductor.list()
        assert len(conductors) > 0

        # By default, only IPMI HW type is enabled. iDrac and Redfish
        # can optionally be enabled
        drivers = ironic.driver.list()
        driver_names = [drv.name for drv in drivers]

        expected = ['intel-ipmi', 'ipmi']
        for exp in expected:
            assert exp in driver_names
        assert len(driver_names) == 2

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        self.restart_on_changed_debug_oslo_config_file(
            '/etc/ironic/ironic.conf', self._SERVICES)

    def test_910_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        logging.info('Skipping pause resume test LP: #1886202...')
        return
        with self.pause_resume(self._SERVICES):
            logging.info("Testing pause resume")
