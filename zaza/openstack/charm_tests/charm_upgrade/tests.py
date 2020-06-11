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

"""Define class for Charm Upgrade."""

import logging
import unittest

import zaza.model
from zaza.openstack.utilities import (
    cli as cli_utils,
    upgrade_utils as upgrade_utils,
)
from zaza.openstack.charm_tests.nova.tests import LTSGuestCreateTest


class FullCloudCharmUpgradeTest(unittest.TestCase):
    """Class to encapsulate Charm Upgrade Tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Charm Upgrades."""
        cli_utils.setup_logging()
        cls.lts = LTSGuestCreateTest()
        cls.target_charm_namespace = '~openstack-charmers-next'

    def get_upgrade_url(self, charm_url):
        """Return the charm_url to upgrade to.

        :param charm_url: Current charm url.
        :type charm_url: str
        """
        charm_name = upgrade_utils.extract_charm_name_from_url(
            charm_url)
        next_charm_url = zaza.model.get_latest_charm_url(
            "cs:{}/{}".format(self.target_charm_namespace, charm_name))
        return next_charm_url

    def test_200_run_charm_upgrade(self):
        """Run charm upgrade."""
        self.lts.test_launch_small_instance()
        applications = zaza.model.get_status().applications
        groups = upgrade_utils.get_charm_upgrade_groups()
        for group_name, group in groups.items():
            logging.info("About to upgrade {} ({})".format(group_name, group))
            for application, app_details in applications.items():
                if application not in group:
                    continue
                target_url = self.get_upgrade_url(app_details['charm'])
                if target_url == app_details['charm']:
                    logging.warn(
                        "Skipping upgrade of {}, already using {}".format(
                            application,
                            target_url))
                else:
                    logging.info("Upgrading {} to {}".format(
                        application,
                        target_url))
                    zaza.model.upgrade_charm(
                        application,
                        switch=target_url)
                logging.info("Waiting for charm url to update")
                zaza.model.block_until_charm_url(application, target_url)
            zaza.model.block_until_all_units_idle()
        self.lts.test_launch_small_instance()
