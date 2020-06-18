#!/usr/bin/env python3

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

"""Encapsulating `neutron-arista` testing."""

import logging
import tenacity
import zaza.openstack.charm_tests.neutron.tests as neutron_tests
import zaza.openstack.charm_tests.neutron_arista.utils as arista_utils


class NeutronCreateAristaNetworkTest(neutron_tests.NeutronCreateNetworkTest):
    """Test creating an Arista Neutron network through the API."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Neutron Arista tests."""
        super(NeutronCreateAristaNetworkTest, cls).setUpClass()

        logging.info('Waiting for Neutron to become ready...')
        for attempt in tenacity.Retrying(
                wait=tenacity.wait_fixed(5),  # seconds
                stop=tenacity.stop_after_attempt(12),
                reraise=True):
            with attempt:
                cls.neutron_client.list_networks()

    def _test_400_additional_validation(self, expected_network_names):
        """Arista-specific assertions for test_400_create_network.

        :type expected_network_names: List[str]
        """
        logging.info("Querying Arista CVX's networks...")
        actual_network_names = arista_utils.query_fixture_networks(
            arista_utils.fixture_ip_addr())

        # NOTE(lourot): the assertion name is misleading as it's not only
        # checking the item count but also that all items are present in
        # both lists, without checking the order.
        self.assertCountEqual(actual_network_names, expected_network_names)
