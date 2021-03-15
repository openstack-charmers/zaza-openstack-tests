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

"""Encapsulate Manila NetApp testing."""

from zaza.openstack.charm_tests.manila_netapp.setup import (
    MANILA_NETAPP_TYPE_NAME,
    MANILA_NETAPP_DHSS_TYPE_NAME,
    MANILA_NETAPP_SHARE_NET_NAME,
)

import zaza.openstack.charm_tests.manila.tests as manila_tests


class ManilaNetAppNFSTest(manila_tests.ManilaBaseTest):
    """Encapsulate Manila NetApp NFS test."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(ManilaNetAppNFSTest, cls).setUpClass()
        cls.share_name = 'netapp-ontap-share'
        cls.share_type_name = MANILA_NETAPP_TYPE_NAME
        cls.share_protocol = 'nfs'


class ManilaNetAppDHSSNFSTest(manila_tests.ManilaBaseTest):
    """Encapsulate Manila NetApp NFS test."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(ManilaNetAppDHSSNFSTest, cls).setUpClass()
        cls.share_name = 'netapp-ontap-dhss-share'
        cls.share_type_name = MANILA_NETAPP_DHSS_TYPE_NAME
        cls.share_protocol = 'nfs'
        cls.share_network = cls.manila_client.share_networks.find(
            name=MANILA_NETAPP_SHARE_NET_NAME)
