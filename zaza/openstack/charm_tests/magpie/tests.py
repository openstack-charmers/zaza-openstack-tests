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

"""Encapsulate Magpie testing."""

import logging

import zaza

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils


class MagpieTest(test_utils.BaseCharmTest):
    """Base Magpie tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for Magpie charm operation tests."""
        super(MagpieTest, cls).setUpClass()
        unit_names = sorted(
            [i.entity_id
             for i in zaza.model.get_units('magpie')])
        cls.test_unit_0 = unit_names[0]
        cls.test_unit_1 = unit_names[1]

    def test_break_dns_single(self):
        """Check DNS failure is reflected in workload status."""
        zaza.model.run_on_unit(
            self.test_unit_0,
            'mv /etc/resolv.conf /etc/resolv.conf.bak')
        zaza.model.run_on_unit(
            self.test_unit_0,
            './hooks/update-status')
        zaza.model.block_until_unit_wl_message_match(
            self.test_unit_0,
            '.*rev dns failed.*')
        logging.info('Restoring /etc/resolv.conf')
        zaza.model.run_on_unit(
            self.test_unit_0,
            'mv /etc/resolv.conf.bak /etc/resolv.conf')
        logging.info('Updating status')
        zaza.model.run_on_unit(
            self.test_unit_0,
            './hooks/update-status')

    def test_break_ping_single(self):
        """Check ping failure is reflected in workload status."""
        icmp = "iptables {} INPUT -p icmp --icmp-type echo-request -j REJECT"
        logging.info('Blocking ping on {}'.format(self.test_unit_1))
        zaza.model.run_on_unit(
            self.test_unit_1,
            icmp.format('--append'))
        zaza.model.run_on_unit(
            self.test_unit_0,
            './hooks/update-status')
        logging.info('Checking status on {}'.format(self.test_unit_0))
        zaza.model.block_until_unit_wl_message_match(
            self.test_unit_0,
            '.*icmp failed.*')
        logging.info('Allowing ping on {}'.format(self.test_unit_1))
        zaza.model.run_on_unit(
            self.test_unit_1,
            icmp.format('--delete'))
        zaza.model.run_on_unit(
            self.test_unit_0,
            './hooks/update-status')
        logging.info('Checking status on {}'.format(self.test_unit_0))
        zaza.model.block_until_unit_wl_message_match(
            self.test_unit_0,
            '.*icmp ok.*')
