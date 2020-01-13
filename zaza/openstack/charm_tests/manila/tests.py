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

"""Encapsulate Manila testing."""

from tenacity import Retrying, stop_after_attempt, wait_exponential

from manilaclient import client as manilaclient

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class ManilaTests(test_utils.OpenStackBaseTest):
    """Encapsulate Manila  tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(ManilaTests, cls).setUpClass()
        cls.nova_client = (
            openstack_utils.get_nova_session_client(cls.keystone_session))
        cls.manila_client = manilaclient.Client(
            session=cls.keystone_session, client_version='2')

    def test_manila_api(self):
        """Test that the Manila API is working."""
        # now just try a list the shares
        for attempt in Retrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10)):
            self.manila_client.shares.list()
