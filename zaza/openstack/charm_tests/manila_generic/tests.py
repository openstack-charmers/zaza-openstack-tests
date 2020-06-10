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

"""Encapsulate Manila Generic testing."""

import tenacity
import logging

from manilaclient import client as manilaclient

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.juju as zaza_juju
import zaza.model


class ManilaGenericTests(test_utils.OpenStackBaseTest):
    """Encapsulate Manila Generic tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(ManilaGenericTests, cls).setUpClass()
        cls.manila_client = manilaclient.Client(
            session=cls.keystone_session, client_version='2')

    def test_manila_api(self):
        """Test that the Manila API is working."""
        self.assertEqual([], self._list_shares())

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=3, min=2, max=10))
    def _list_shares(self):
        return self.manila_client.shares.list()

    def test_manila_manila_generic_relation_address(self):
        """Verify the manila to manila-generic relation address match."""
        logging.debug('Checking the manila:manila-generic relation address.')
        unit_name = 'manila-generic/0'
        remote_unit_name = 'manila/0'
        relation_name = 'manila-plugin'
        remote_unit = zaza.model.get_unit_from_name(remote_unit_name)
        remote_ip = remote_unit.public_address
        relation = zaza_juju.get_relation_from_unit(
            unit_name,
            remote_unit_name,
            relation_name
        )
        # Get private-address in relation
        rel_private_ip = relation.get('private-address')
        # The private address in relation should match manila/0 address
        self.assertEqual(rel_private_ip, remote_ip)
