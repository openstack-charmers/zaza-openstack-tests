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

"""Encapsulate pacemaker-remote testing."""

import unittest

import tenacity
import zaza.model
import zaza.openstack.configure.hacluster
import zaza.openstack.utilities.generic as generic_utils


class PacemakerRemoteTest(unittest.TestCase):
    """Encapsulate pacemaker-remote tests."""

    def test_check_nodes_online(self):
        """Test that all nodes are online."""
        for attempt in tenacity.Retrying(
            reraise=True,
            stop=tenacity.stop_after_attempt(5),
            wait=tenacity.wait_fixed(5),
        ):
            with attempt:
                zaza.openstack.configure.hacluster.check_all_nodes_online(
                    'api'
                )
        units = zaza.model.get_units('pacemaker-remote')
        last_unit = units[-1]
        node_names = generic_utils.get_unit_hostnames(units)
        node_name = node_names[last_unit.entity_id]
        zaza.openstack.configure.hacluster.remove_node(
            'api',
            node_name)
        for attempt in tenacity.Retrying(
            reraise=True,
            stop=tenacity.stop_after_attempt(5),
            wait=tenacity.wait_fixed(5),
        ):
            with attempt:
                self.assertTrue(
                    zaza.openstack.configure.hacluster.check_all_nodes_online(
                        'api'
                    )
                )
