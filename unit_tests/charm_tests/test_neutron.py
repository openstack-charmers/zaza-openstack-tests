# Copyright 2022 Canonical Ltd.
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
import unittest

import zaza.openstack.charm_tests.neutron.tests as neutron_tests


class FakeInstance:
    def __init__(self):
        self.addresses = {
            "foo_admin_net": [
                {"addr": "10.5.1.2",
                 "OS-EXT-IPS:type": "fixed"},
                {"addr": "10.245.166.188",
                 "OS-EXT-IPS:type": "floating"},
            ]
        }


class TestNeutron(unittest.TestCase):
    def test_network_name_from_instance(self):
        instance = FakeInstance()

        self.assertEqual('foo_admin_net',
                         neutron_tests.network_name_from_instance(instance))

        instance.addresses = {}
        self.assertEqual(None,
                         neutron_tests.network_name_from_instance(instance))

    def test_ips_from_instance(self):
        instance = FakeInstance()
        self.assertEqual(["10.245.166.188"],
                         neutron_tests.ips_from_instance(instance, "floating"))
        self.assertEqual(["10.5.1.2"],
                         neutron_tests.ips_from_instance(instance, "fixed"))
        instance.addresses = {}
        self.assertEqual([],
                         neutron_tests.ips_from_instance(instance, "floating"))
