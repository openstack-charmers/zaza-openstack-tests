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
    os_versions,
    upgrade_utils,
)


class FullCloudCharmUpgradeTest(unittest.TestCase):
    """Class to encapsulate Charm Upgrade Tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Charm Upgrades."""
        cli_utils.setup_logging()

    def test_200_run_charm_upgrade(self):
        """Run charm upgrade."""
        applications = zaza.model.get_status().applications
        groups = upgrade_utils.get_charm_upgrade_groups(
            extra_filters=[upgrade_utils._filter_etcd,
                           upgrade_utils._filter_easyrsa,
                           upgrade_utils._filter_memcached])
        for group_name, group in groups:
            logging.info("About to upgrade {} ({})".format(group_name, group))
            for application, app_details in applications.items():
                if application not in group:
                    continue
                charm_channel = applications[application].charm_channel
                charm_track, charm_risk = charm_channel.split('/')
                os_version, os_codename = (
                    upgrade_utils.determine_next_openstack_release(
                        charm_track))
                if os_versions.CompareOpenStack(os_codename) > 'zed':
                    new_charm_track = os_version
                else:
                    new_charm_track = os_codename
                new_charm_channel = f"{new_charm_track}/{charm_risk}"
                self.assertNotEqual(charm_channel, new_charm_channel)
                logging.info("Upgrading {} to {}".format(
                    application, new_charm_channel))
                zaza.model.upgrade_charm(
                    application, channel=new_charm_channel)
                logging.info("Waiting for charm channel to update")
                zaza.model.block_until_charm_channel(
                    application, new_charm_channel)
            zaza.model.block_until_all_units_idle(timeout=10800)
