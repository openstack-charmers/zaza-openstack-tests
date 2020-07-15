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

"""Encapsulate OVN testing."""

import logging

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class BaseCharmOperationTest(test_utils.BaseCharmTest):
    """Base OVN Charm operation tests."""

    # override if not possible to determine release pair from charm under test
    release_application = None

    @classmethod
    def setUpClass(cls):
        """Run class setup for OVN charm operation tests."""
        super(BaseCharmOperationTest, cls).setUpClass()
        cls.services = ['NotImplemented']  # This must be overridden
        cls.current_release = openstack_utils.get_os_release(
            openstack_utils.get_current_os_release_pair(
                cls.release_application or cls.application_name))

    def test_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped, then resume and check
        they are started.
        """
        with self.pause_resume(self.services):
            logging.info('Testing pause resume (services="{}")'
                         .format(self.services))


class CentralCharmOperationTest(BaseCharmOperationTest):
    """OVN Central Charm operation tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for OVN Central charm operation tests."""
        super(CentralCharmOperationTest, cls).setUpClass()
        cls.services = [
            'ovn-northd',
            'ovsdb-server',
        ]


class ChassisCharmOperationTest(BaseCharmOperationTest):
    """OVN Chassis Charm operation tests."""

    release_application = 'ovn-central'

    @classmethod
    def setUpClass(cls):
        """Run class setup for OVN Chassis charm operation tests."""
        super(ChassisCharmOperationTest, cls).setUpClass()
        cls.services = [
            'ovn-controller',
        ]
