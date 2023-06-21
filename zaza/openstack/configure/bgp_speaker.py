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

"""Module to setup BGP speaker configuration."""

import argparse
import logging
import sys
import tenacity
import zaza.model

from zaza.openstack.utilities import (
    cli as cli_utils,
    openstack as openstack_utils,
    juju as juju_utils,
)


NDR_TEST_FIP = "NDR_TEST_FIP"


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                reraise=True, stop=tenacity.stop_after_attempt(10))
def _assert_speaker_added(local_as):
    logging.debug(f"Checking that a BGP speaker for {local_as} has been added")
    # As soon as this message appears in the log on a pristine machine we can
    # proceed with adding routes. The check is due to LP: #2024481.
    grep_cmd = (f'grep "Added BGP Speaker for local_as={local_as}"'
                f' /var/log/neutron/neutron-bgp-dragent.log')
    # Usually we only have one unit in test bundles but let's be generic.
    for unit in zaza.model.get_units("neutron-dynamic-routing"):
        juju_utils.remote_run(unit.name, fatal=True, remote_cmd=grep_cmd)


def setup_bgp_speaker(peer_application_name, keystone_session=None):
    """Perform BGP Speaker setup.

    :param peer_application_name: String name of BGP peer application
    :type peer_application_name: string
    :param keystone_session: Keystone session object for overcloud
    :type keystone_session: keystoneauth1.session.Session object
    :returns: None
    :rtype: None
    """
    # Get ASNs from deployment
    dr_relation = juju_utils.get_relation_from_unit(
        'neutron-dynamic-routing',
        peer_application_name,
        'bgpclient')
    peer_asn = dr_relation.get('asn')
    logging.debug('peer ASn: "{}"'.format(peer_asn))
    peer_relation = juju_utils.get_relation_from_unit(
        peer_application_name,
        'neutron-dynamic-routing',
        'bgp-speaker')
    dr_asn = peer_relation.get('asn')
    logging.debug('our ASn: "{}"'.format(dr_asn))

    # If a session has not been provided, acquire one
    if not keystone_session:
        keystone_session = openstack_utils.get_overcloud_keystone_session()

    # Get authenticated clients
    neutron_client = openstack_utils.get_neutron_session_client(
        keystone_session)

    # Create BGP speaker
    logging.info("Setting up BGP speaker")
    bgp_speaker = openstack_utils.create_bgp_speaker(
        neutron_client, local_as=dr_asn)

    # Due to LP: #2024481 make sure the BGP speaker is actually scheduled
    # on this unit before adding any networks to it.
    _assert_speaker_added(local_as=bgp_speaker["local_as"])

    # Add networks to bgp speaker
    logging.info("Advertising BGP routes")
    openstack_utils.add_network_to_bgp_speaker(
        neutron_client, bgp_speaker, openstack_utils.EXT_NET)
    openstack_utils.add_network_to_bgp_speaker(
        neutron_client, bgp_speaker, openstack_utils.PRIVATE_NET)
    logging.debug("Advertised routes: {}"
                  .format(
                      neutron_client.list_route_advertised_from_bgp_speaker(
                          bgp_speaker["id"])))

    # Create peer
    logging.info("Setting up BGP peer")
    bgp_peer = openstack_utils.create_bgp_peer(neutron_client,
                                               peer_application_name,
                                               remote_as=peer_asn)
    # Add peer to bgp speaker
    logging.info("Adding BGP peer to BGP speaker")
    openstack_utils.add_peer_to_bgp_speaker(
        neutron_client, bgp_speaker, bgp_peer)

    # Create Floating IP to advertise
    logging.info("Creating floating IP to advertise")
    port = openstack_utils.create_port(neutron_client,
                                       NDR_TEST_FIP,
                                       openstack_utils.PRIVATE_NET)
    floating_ip = openstack_utils.create_floating_ip(neutron_client,
                                                     openstack_utils.EXT_NET,
                                                     port=port)
    logging.info(
        "Advertised floating IP: {}".format(
            floating_ip["floating_ip_address"]))


def run_from_cli():
    """Run BGP Speaker setup from CLI.

    :returns: None
    :rtype: None
    """
    cli_utils.setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--peer-application", "-a",
                        help="BGP peer application name. Default: osci-frr",
                        default="osci-frr")

    options = parser.parse_args()
    peer_application_name = cli_utils.parse_arg(options,
                                                "peer_application")

    setup_bgp_speaker(peer_application_name)


if __name__ == "__main__":
    sys.exit(run_from_cli())
