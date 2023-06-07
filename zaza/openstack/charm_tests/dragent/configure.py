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

"""Setup for BGP deployments."""

import logging
import zaza.model
from zaza.openstack.configure import bgp_speaker
from zaza.openstack.utilities import (
    generic as generic_utils,
    openstack as openstack_utils,
)
from zaza.openstack.charm_tests.neutron.setup import basic_overcloud_network

DEFAULT_PEER_APPLICATION_NAME = "osci-frr"


def setup():
    """Run setup for BGP networking.

    Configure the following:
        The overcloud network using subnet pools
        The overcloud BGP speaker
        The BGP peer
        Advertising of the FIPs via BGP
        Advertising of the project network(s) via BGP

    :returns: None
    :rtype: None
    """
    # Reuse the existing network configuration code.
    basic_overcloud_network()

    # Get a keystone session
    keystone_session = openstack_utils.get_overcloud_keystone_session()

    # LP Bugs #1784083 and #1841459, require a late restart of the
    # neutron-bgp-dragent service
    logging.warning("Due to LP Bugs #1784083 and #1841459, we require a late "
                    "restart of the neutron-bgp-dragent service before "
                    "setting up BGP.")
    for unit in zaza.model.get_units("neutron-dynamic-routing"):
        generic_utils.systemctl(unit, "neutron-bgp-dragent", command="restart")

    # Configure BGP
    bgp_speaker.setup_bgp_speaker(
        peer_application_name=DEFAULT_PEER_APPLICATION_NAME,
        keystone_session=keystone_session)
