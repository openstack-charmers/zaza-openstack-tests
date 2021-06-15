#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
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

"""Encapsulate Manila NetApp setup."""

import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.neutron.setup as neutron_setup


MANILA_NETAPP_TYPE_NAME = "netapp-ontap"
MANILA_NETAPP_BACKEND_NAME = "netapp-ontap"

MANILA_NETAPP_DHSS_TYPE_NAME = "netapp-ontap-dhss"
MANILA_NETAPP_DHSS_BACKEND_NAME = "netapp-ontap-dhss"

MANILA_NETAPP_SHARE_NET_NAME = "netapp-ontap-share-network"


def create_netapp_share_type(manila_client=None):
    """Create a share type for Manila with NetApp Data ONTAP driver.

    :param manila_client: Authenticated manilaclient
    :type manila_client: manilaclient.Client
    """
    if manila_client is None:
        manila_client = openstack_utils.get_manila_session_client(
            openstack_utils.get_overcloud_keystone_session())

    manila_client.share_types.create(
        name=MANILA_NETAPP_TYPE_NAME,
        spec_driver_handles_share_servers=False,
        extra_specs={
            'vendor_name': 'NetApp',
            'share_backend_name': MANILA_NETAPP_BACKEND_NAME,
            'storage_protocol': 'NFS_CIFS',
        })


def create_netapp_dhss_share_type(manila_client=None):
    """Create a DHSS share type for Manila with NetApp Data ONTAP driver.

    :param manila_client: Authenticated manilaclient
    :type manila_client: manilaclient.Client
    """
    if manila_client is None:
        manila_client = openstack_utils.get_manila_session_client(
            openstack_utils.get_overcloud_keystone_session())

    manila_client.share_types.create(
        name=MANILA_NETAPP_DHSS_TYPE_NAME,
        spec_driver_handles_share_servers=True,
        extra_specs={
            'vendor_name': 'NetApp',
            'share_backend_name': MANILA_NETAPP_DHSS_BACKEND_NAME,
            'storage_protocol': 'NFS_CIFS',
        })


def create_netapp_share_network(manila_client=None):
    """Create a Manila share network from the existing provider network.

    This setup function assumes that 'neutron.setup.basic_overcloud_network'
    is called to have the proper tenant networks setup.

    The share network will be bound to the provider network configured by
    'neutron.setup.basic_overcloud_network'.
    """
    session = openstack_utils.get_overcloud_keystone_session()
    if manila_client is None:
        manila_client = openstack_utils.get_manila_session_client(session)

    neutron = openstack_utils.get_neutron_session_client(session)
    external_net = neutron.find_resource(
        'network',
        neutron_setup.OVERCLOUD_NETWORK_CONFIG['external_net_name'])
    external_subnet = neutron.find_resource(
        'subnet',
        neutron_setup.OVERCLOUD_NETWORK_CONFIG['external_subnet_name'])

    manila_client.share_networks.create(
        name=MANILA_NETAPP_SHARE_NET_NAME,
        neutron_net_id=external_net['id'],
        neutron_subnet_id=external_subnet['id'])
