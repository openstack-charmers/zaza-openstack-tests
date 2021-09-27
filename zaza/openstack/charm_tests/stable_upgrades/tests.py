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

"""Encapsulating stable upgrades of charm payloads."""


import logging

from zaza import model
import zaza.openstack.charm_tests.test_utils as test_utils
from zaza.openstack.utilities import openstack_upgrade


class StableUpgradeToProposedTest(test_utils.OpenStackBaseTest):
    """Stable dist-upgrade of charm payloads."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running stable upgrades to proposed."""
        super(StableUpgradeToProposedTest, cls).setUpClass()

    def test_upgrade_to_proposed(self):
        """Upgrade to proposed pocket.

        Updates openstack-origin or source charm config option for the
        specified applications, if they exist in the model, and
        dist-upgrades to the proposed pocket.
        """
        # Upgrade order matters here. See the order documented in the
        # charm deploy guide.
        applications = [
            'rabbitmq-server',
            'ceph-mon',
            'keystone',
            'aodh',
            'barbican',
            'ceilometer',
            'ceph-fs',
            'ceph-radosgw',
            'cinder',
            'designate',
            'designate-bind',
            'glance',
            'gnocchi',
            'heat',
            'manila',
            'manila-generic',
            'neutron-api',
            'neutron-api-plugin-ovn',
            'neutron-gateway',
            'ovn-central',
            'placement',
            'nova-cloud-controller',
            'openstack-dashboard',
            'nova-compute',
            'nova-compute-sriov',
            'ceph-osd',
            'swift-proxy',
            'swift-storage-z1',
            'swift-storage-z2',
            'swift-storage-z3',
            'octavia',
            'neutron-openvswitch-octavia',
        ]
        deployed_applications = model.sync_deployed()
        for application in applications:
            if application not in deployed_applications:
                continue
            logging.info("Running apt dist-upgrade on {}".format(application))
            openstack_upgrade.upgrade_to_proposed(application)
