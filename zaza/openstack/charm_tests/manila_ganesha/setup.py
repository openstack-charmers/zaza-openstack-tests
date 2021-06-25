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


"""Encapsulate Manila Ganesha setup."""


import zaza.openstack.utilities.openstack as openstack_utils

from manilaclient import client as manilaclient


MANILA_GANESHA_TYPE_NAME = "cephfsnfstype"


def setup_ganesha_share_type(manila_client=None):
    """Create a share type for manila with Ganesha.

    :param manila_client: Authenticated manilaclient
    :type manila_client: manilaclient.Client
    """
    if manila_client is None:
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        manila_client = manilaclient.Client(
            session=keystone_session, client_version='2')

    manila_client.share_types.create(
        name=MANILA_GANESHA_TYPE_NAME, spec_driver_handles_share_servers=False,
        extra_specs={
            'vendor_name': 'Ceph',
            'storage_protocol': 'NFS',
            'snapshot_support': False,
        })
