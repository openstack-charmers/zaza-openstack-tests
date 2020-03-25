#!/usr/bin/env python3

# Copyright 2018 Canonical Ltd.
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

"""Define class for Series Upgrade."""

import asyncio
import logging
import os
import unittest

from zaza import model
from zaza.openstack.utilities import (
    cli as cli_utils,
    series_upgrade as series_upgrade_utils,
    upgrade_utils as upgrade_utils,
)
from zaza.openstack.charm_tests.nova.tests import LTSGuestCreateTest


def _filter_easyrsa(app, app_config, model_name=None):
    charm_name = upgrade_utils.extract_charm_name_from_url(app_config['charm'])
    if "easyrsa" in charm_name:
        logging.warn("Skipping series upgrade of easyrsa Bug #1850121")
        return True
    return False


def _filter_etcd(app, app_config, model_name=None):
    charm_name = upgrade_utils.extract_charm_name_from_url(app_config['charm'])
    if "etcd" in charm_name:
        logging.warn("Skipping series upgrade of easyrsa Bug #1850124")
        return True
    return False


class SeriesUpgradeTest(unittest.TestCase):
    """Class to encapsulate Series Upgrade Tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Series Upgrades."""
        cli_utils.setup_logging()
        cls.from_series = None
        cls.to_series = None
        cls.workaround_script = None
        cls.files = []

    def test_200_run_series_upgrade(self):
        """Run series upgrade."""
        # Set Feature Flag
        os.environ["JUJU_DEV_FEATURE_FLAGS"] = "upgrade-series"

        applications = model.get_status().applications
        completed_machines = []
        for application, app_details in applications:
            # Skip subordinates
            if app_details["subordinate-to"]:
                continue
            if "easyrsa" in app_details["charm"]:
                logging.warn(
                    "Skipping series upgrade of easyrsa Bug #1850121")
                continue
            if "etcd" in app_details["charm"]:
                logging.warn(
                    "Skipping series upgrade of easyrsa Bug #1850124")
                continue
            charm_name = upgrade_utils.extract_charm_name_from_url(app_details['charm'])
            upgrade_config = series_upgrade_utils.app_config(
                charm_name,
                is_async=False)
            upgrade_function = upgrade_config.pop('upgrade_function')
            logging.warn("About to upgrade {}".format(application))
            upgrade_function(
                application,
                **upgrade_config,
                from_series=self.from_series,
                to_series=self.to_series,
                completed_machines=completed_machines,
                workaround_script=self.workaround_script,
                files=self.files,
            )
            if "rabbitmq-server" in app_details["charm"]:
                logging.info(
                    "Running complete-cluster-series-upgrade action on leader")
                model.run_action_on_leader(
                    'rabbitmq-server',
                    'complete-cluster-series-upgrade',
                    action_params={})
                model.block_until_all_units_idle()

            if "percona-cluster" in app_details["charm"]:
                logging.info(
                    "Running complete-cluster-series-upgrade action on leader")
                model.run_action_on_leader(
                    'mysql',
                    'complete-cluster-series-upgrade',
                    action_params={})
                model.block_until_all_units_idle()


class OpenStackSeriesUpgrade(SeriesUpgradeTest):
    """OpenStack Series Upgrade.

    Full OpenStack series upgrade with VM launch before and after the series
    upgrade.

    This test requires a full OpenStack including at least: keystone, glance,
    nova-cloud-controller, nova-compute, neutron-gateway, neutron-api and
    neutron-openvswitch.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for Series Upgrades."""
        super(OpenStackSeriesUpgrade, cls).setUpClass()
        cls.lts = LTSGuestCreateTest()
        cls.lts.setUpClass()

    def test_100_validate_pre_series_upgrade_cloud(self):
        """Validate pre series upgrade."""
        logging.info("Validate pre-series-upgrade: Spin up LTS instance")
        self.lts.test_launch_small_instance()

    def test_500_validate_series_upgraded_cloud(self):
        """Validate post series upgrade."""
        logging.info("Validate post-series-upgrade: Spin up LTS instance")
        self.lts.test_launch_small_instance()


class OpenStackTrustyXenialSeriesUpgrade(OpenStackSeriesUpgrade):
    """OpenStack Trusty to Xenial Series Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Trusty to Xenial Series Upgrades."""
        super(OpenStackTrustyXenialSeriesUpgrade, cls).setUpClass()
        cls.from_series = "trusty"
        cls.to_series = "xenial"


class OpenStackXenialBionicSeriesUpgrade(OpenStackSeriesUpgrade):
    """OpenStack Xenial to Bionic Series Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Xenial to Bionic Series Upgrades."""
        super(OpenStackXenialBionicSeriesUpgrade, cls).setUpClass()
        cls.from_series = "xenial"
        cls.to_series = "bionic"


class TrustyXenialSeriesUpgrade(SeriesUpgradeTest):
    """Trusty to Xenial Series Upgrade.

    Makes no assumptions about what is in the deployment.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for Trusty to Xenial Series Upgrades."""
        super(TrustyXenialSeriesUpgrade, cls).setUpClass()
        cls.from_series = "trusty"
        cls.to_series = "xenial"


class XenialBionicSeriesUpgrade(SeriesUpgradeTest):
    """Xenial to Bionic Series Upgrade.

    Makes no assumptions about what is in the deployment.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for Xenial to Bionic Series Upgrades."""
        super(XenialBionicSeriesUpgrade, cls).setUpClass()
        cls.from_series = "xenial"
        cls.to_series = "bionic"


class ParallelSeriesUpgradeTest(unittest.TestCase):
    """Class to encapsulate Series Upgrade Tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Series Upgrades."""
        cli_utils.setup_logging()
        cls.from_series = None
        cls.to_series = None
        cls.workaround_script = None
        cls.files = []

    def test_200_run_series_upgrade(self):
        """Run series upgrade."""
        # Set Feature Flag
        os.environ["JUJU_DEV_FEATURE_FLAGS"] = "upgrade-series"
        upgrade_groups = upgrade_utils.get_series_upgrade_groups(
            extra_filters=[_filter_etcd, _filter_easyrsa])
        applications = model.get_status().applications
        completed_machines = []
        for group_name, group in upgrade_groups.items():
            logging.warn("About to upgrade {} ({})".format(group_name, group))
            upgrade_group = []
            for application, app_details in applications.items():
                if application not in group:
                    continue
                charm_name = upgrade_utils.extract_charm_name_from_url(app_details['charm'])
                upgrade_config = series_upgrade_utils.app_config(charm_name)
                upgrade_function = upgrade_config.pop('upgrade_function')
                logging.warn("About to upgrade {}".format(application))
                upgrade_group.append(
                    upgrade_function(
                        application,
                        **upgrade_config,
                        from_series=self.from_series,
                        to_series=self.to_series,
                        completed_machines=completed_machines,
                        workaround_script=self.workaround_script,
                        files=self.files,
                    ))
            asyncio.get_event_loop().run_until_complete(
                asyncio.gather(*upgrade_group))
            if "rabbitmq-server" in group:
                logging.info(
                    "Running complete-cluster-series-upgrade action on leader")
                model.run_action_on_leader(
                    'rabbitmq-server',
                    'complete-cluster-series-upgrade',
                    action_params={})
                model.block_until_all_units_idle()

            if "percona-cluster" in group:
                logging.info(
                    "Running complete-cluster-series-upgrade action on leader")
                model.run_action_on_leader(
                    'mysql',
                    'complete-cluster-series-upgrade',
                    action_params={})
                model.block_until_all_units_idle()


class ParallelTrustyXenialSeriesUpgrade(ParallelSeriesUpgradeTest):
    """Trusty to Xenial Series Upgrade.

    Makes no assumptions about what is in the deployment.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for Trusty to Xenial Series Upgrades."""
        super(ParallelTrustyXenialSeriesUpgrade, cls).setUpClass()
        cls.from_series = "trusty"
        cls.to_series = "xenial"


class ParallelXenialBionicSeriesUpgrade(ParallelSeriesUpgradeTest):
    """Xenial to Bionic Series Upgrade.

    Makes no assumptions about what is in the deployment.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for Xenial to Bionic Series Upgrades."""
        super(ParallelXenialBionicSeriesUpgrade, cls).setUpClass()
        cls.from_series = "xenial"
        cls.to_series = "bionic"


if __name__ == "__main__":
    unittest.main()
