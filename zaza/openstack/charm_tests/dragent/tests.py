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

"""Define class of BGP tests."""

import logging
import tenacity
import unittest
import zaza.openstack.charm_tests.neutron.tests as neutron_tests

from zaza import model
from zaza.openstack.utilities import (
    cli as cli_utils,
    juju as juju_utils,
)


class DRAgentTest(neutron_tests.NeutronNetworkingBase):
    """Class to encapsulate BPG tests."""

    BGP_PEER_APPLICATION = 'osci-frr'

    def setUp(self):
        """Run setup actions specific to the class."""
        super().setUp()
        self._peer_unit = model.get_units(
            self.BGP_PEER_APPLICATION)[0].entity_id

    @classmethod
    def setUpClass(cls):
        """Run setup actions specific to the class."""
        super().setUpClass()
        cli_utils.setup_logging()

    @staticmethod
    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(10))
    def _assert_cidr_in_peer_routing_table(peer_unit, cidr):
        logging.debug("Checking for {} on BGP peer {}"
                      .format(cidr, peer_unit))
        # Run show ip route bgp on BGP peer
        routes = juju_utils.remote_run(
            peer_unit, remote_cmd='vtysh -c "show ip route bgp"')
        logging.info(routes)
        assert cidr in routes, (
            "CIDR, {}, not found in BGP peer's routing table: {}"
            .format(cidr, routes))

    @staticmethod
    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(10))
    def _assert_ip_reachable_via_peer(peer_unit, address):
        logging.debug(f"Checking if {peer_unit} can reach {address} using "
                      f"routes adverised by NDR")
        # Ping with -w specified will return an exit code if there is no
        # response after the number of seconds specified. This is to ignore the
        # first ping that may not arrive due to an ARP resolution.
        juju_utils.remote_run(peer_unit, fatal=True,
                              remote_cmd=f'ping -w4 {address}')

    def test_bgp_routes(self):
        """Test BGP routes.

        A test that checks only the control plane of Neutron Dynamic Routing.

        :raises: AssertionError if expected BGP routes are not found
        :returns: None
        :rtype: None
        """
        # Get expected advertised routes
        private_cidr = self.project_subnet['cidr']
        floating_ip_cidr = "{}/32".format(
            self.neutron_client.list_floatingips()
            ["floatingips"][0]["floating_ip_address"])

        # This test may run immediately after configuration.
        # It may take time for routes to propagate via BGP. Do a
        # binary backoff.
        self._assert_cidr_in_peer_routing_table(self._peer_unit, private_cidr)
        logging.info("Private subnet CIDR, {}, found in routing table"
                     .format(private_cidr))
        self._assert_cidr_in_peer_routing_table(self._peer_unit,
                                                floating_ip_cidr)
        logging.info("Floating IP CIDR, {}, found in routing table"
                     .format(floating_ip_cidr))

    def test_instance_connectivity(self):
        """Test connectivity to instances via dynamic routes.

        Make sure that with routes advertised via NDR it is actually possible
        to reach instances from a unit that gets those routes programmed into
        its routing table.
        """
        # Get an instance but do not perform connectivity checks as the machine
        # running those tests does not have the dynamic routes advertised to
        # the peer unit by NDR.
        fip_instance = self.launch_guest('fip-instance', instance_key='jammy',
                                         perform_connectivity_check=False)

        @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                        reraise=True, stop=tenacity.stop_after_attempt(10))
        def get_fip(nova_client, instance_id):
            """Try to get a FIP from an instance.

            Instance FIPs may not be immediately accessible from the Nova
            object after the instance creation so a retry logic is necessary.
            """
            # The reason for looking up an instance object again is that the
            # Nova client does not refresh address information after
            instance = nova_client.servers.find(id=instance_id)
            fips = neutron_tests.floating_ips_from_instance(instance)
            if not fips:
                raise tenacity.TryAgain
            return fips[0]

        fip = get_fip(self.nova_client, fip_instance.id)

        # First check that the FIP is present in the peer unit's routing table.
        self._assert_cidr_in_peer_routing_table(self._peer_unit, f'{fip}/32')
        # Once it is, check if it is actually reachable.
        self._assert_ip_reachable_via_peer(self._peer_unit, fip)


if __name__ == "__main__":
    unittest.main()
