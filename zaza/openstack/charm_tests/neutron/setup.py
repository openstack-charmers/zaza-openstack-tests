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

"""Setup for Neutron deployments."""

import functools
import logging

from zaza.openstack.configure import (
    network,
)
from zaza.openstack.utilities import (
    cli as cli_utils,
    generic as generic_utils,
    openstack as openstack_utils,
)

import zaza.utilities.juju as juju_utils

import zaza.charm_lifecycle.utils as lifecycle_utils


# The overcloud network configuration settings are declared.
# These are the network configuration settings under test.
OVERCLOUD_NETWORK_CONFIG = {
    "network_type": "gre",
    "router_name": openstack_utils.PROVIDER_ROUTER,
    "ip_version": "4",
    "address_scope": "public",
    "external_net_name": openstack_utils.EXT_NET,
    "external_subnet_name": openstack_utils.EXT_NET_SUBNET,
    "prefix_len": "24",
    "subnetpool_name": "pooled_subnets",
    "subnetpool_prefix": "192.168.0.0/16",
    "project_net_name": openstack_utils.PRIVATE_NET,
    "project_subnet_name": openstack_utils.PRIVATE_NET_SUBNET,
}

OVERCLOUD_PROVIDER_VLAN_NETWORK_CONFIG = {
    "provider_vlan_net_name": "provider_vlan",
    "provider_vlan_subnet_name": "provider_vlan_subnet",
    "provider_vlan_cidr": "10.42.33.0/24",
    "provider_vlan_id": "2933",
}

# The undercloud network configuration settings are substrate specific to
# the environment where the tests are being executed. These settings may be
# overridden by environment variables. See the doc string documentation for
# zaza.openstack.utilities.generic_utils.get_undercloud_env_vars for the
# environment variables required to be exported and available to zaza.
# These are default settings provided as an example.
DEFAULT_UNDERCLOUD_NETWORK_CONFIG = {
    "start_floating_ip": "10.5.150.0",
    "end_floating_ip": "10.5.150.254",
    "external_dns": "10.5.0.2",
    "external_net_cidr": "10.5.0.0/16",
    "default_gateway": "10.5.0.1",
}

# For Neutron Dynamic Tests it is useful to avoid relying on the directly
# connected routes and instead using the advertised routes on the southbound
# path and default routes on the northbound path. To do that, a separate
# service subnet may be optionally created to force Neutron to use that instead
# of the external network subnet without concrete service IPs which is used as
# a fallback only.
DEFAULT_FIP_SERVICE_SUBNET_CONFIG = {
    "fip_service_subnet_name": openstack_utils.FIP_SERVICE_SUBNET_NAME,
    "fip_service_subnet_cidr": "100.64.0.0/24"
}


def undercloud_and_charm_setup(limit_gws=None):
    """Perform undercloud and charm setup for network plumbing.

    :param limit_gws: Limit the number of gateways that get a port attached
    :type limit_gws: int
    """
    # Get network configuration settings
    network_config = {}
    # Default undercloud settings
    network_config.update(DEFAULT_UNDERCLOUD_NETWORK_CONFIG)
    # Environment specific settings
    network_config.update(generic_utils.get_undercloud_env_vars())

    # Get optional use_juju_wait for network option
    options = (lifecycle_utils
               .get_charm_config(fatal=False)
               .get('configure_options', {}))
    use_juju_wait = options.get(
        'configure_gateway_ext_port_use_juju_wait', True)

    # Handle network for OpenStack-on-OpenStack scenarios
    provider_type = juju_utils.get_provider_type()
    if provider_type == "openstack":
        undercloud_ks_sess = openstack_utils.get_undercloud_keystone_session()
        network.setup_gateway_ext_port(network_config,
                                       keystone_session=undercloud_ks_sess,
                                       limit_gws=limit_gws,
                                       use_juju_wait=use_juju_wait)
    elif provider_type == "maas":
        # NOTE(fnordahl): After validation of the MAAS+Netplan Open vSwitch
        # integration support, we would most likely want to add multiple modes
        # of operation with MAAS.
        #
        # Perform charm based OVS configuration
        openstack_utils.configure_charmed_openstack_on_maas(
            network_config, limit_gws=limit_gws)
    else:
        logging.warning('Unknown Juju provider type, "{}", will not perform'
                        ' charm network configuration.'
                        .format(provider_type))


def basic_overcloud_network(limit_gws=None, use_separate_fip_subnet=False):
    """Run setup for neutron networking.

    Configure the following:
        The overcloud network using subnet pools

    :param limit_gws: Limit the number of gateways that get a port attached
    :type limit_gws: int
    :param use_separate_fip_subnet: Use a separate service subnet for floating
                                    ips instead of relying on the external
                                    network subnet for FIP allocations.
    :type use_separate_fip_subnet: bool
    """
    cli_utils.setup_logging()

    # Get network configuration settings
    network_config = {}
    # Declared overcloud settings
    network_config.update(OVERCLOUD_NETWORK_CONFIG)
    # Default undercloud settings
    network_config.update(DEFAULT_UNDERCLOUD_NETWORK_CONFIG)

    if use_separate_fip_subnet:
        network_config.update(DEFAULT_FIP_SERVICE_SUBNET_CONFIG)

    # Environment specific settings
    network_config.update(generic_utils.get_undercloud_env_vars())

    # Get keystone session
    keystone_session = openstack_utils.get_overcloud_keystone_session()

    # Perform undercloud and charm setup for network plumbing
    undercloud_and_charm_setup(limit_gws=limit_gws)

    # Configure the overcloud network
    network.setup_sdn(network_config, keystone_session=keystone_session)


def vlan_provider_overcloud_network():
    """Run setup to create a VLAN provider network."""
    cli_utils.setup_logging()

    # Get network configuration settings
    network_config = {}
    # Declared overcloud settings
    network_config.update(OVERCLOUD_NETWORK_CONFIG)
    # Declared provider vlan overcloud settings
    network_config.update(OVERCLOUD_PROVIDER_VLAN_NETWORK_CONFIG)
    # Environment specific settings
    network_config.update(generic_utils.get_undercloud_env_vars())

    # Get keystone session
    keystone_session = openstack_utils.get_overcloud_keystone_session()

    # Configure the overcloud network
    network.setup_sdn_provider_vlan(network_config,
                                    keystone_session=keystone_session)


# Configure function to get one gateway with external network
overcloud_network_one_gw = functools.partial(
    basic_overcloud_network,
    limit_gws=1)


# Configure function to get two gateways with external network
overcloud_network_two_gws = functools.partial(
    basic_overcloud_network,
    limit_gws=2)
