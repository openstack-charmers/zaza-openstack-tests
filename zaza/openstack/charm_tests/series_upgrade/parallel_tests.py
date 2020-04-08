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
import sys
import unittest

from zaza import model
from zaza.openstack.utilities import (
    cli as cli_utils,
    upgrade_utils as upgrade_utils,
)
from zaza.openstack.charm_tests.nova.tests import LTSGuestCreateTest
from zaza.openstack.utilities.parallel_series_upgrade import (
    parallel_series_upgrade,
)


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
        from_series = self.from_series
        to_series = self.to_series
        completed_machines = []
        workaround_script = None
        files = []
        applications = model.get_status().applications
        for group_name, apps in upgrade_groups.items():
            logging.info("About to upgrade {} from {} to {}".format(
                group_name, from_series, to_series))
            upgrade_functions = []
            if group_name in ["Stateful Services", "Data Plane", "sweep_up"]:
                logging.info("Going to upgrade {} unit by unit".format(apps))
                upgrade_function = \
                    parallel_series_upgrade.serial_series_upgrade
            else:
                logging.info("Going to upgrade {} all at once".format(apps))
                upgrade_function = \
                    parallel_series_upgrade.parallel_series_upgrade

            for charm_name in apps:
                charm = applications[charm_name]['charm']
                name = upgrade_utils.extract_charm_name_from_url(charm)
                upgrade_config = parallel_series_upgrade.app_config(name)
                upgrade_functions.append(
                    upgrade_function(
                        charm_name,
                        **upgrade_config,
                        from_series=from_series,
                        to_series=to_series,
                        completed_machines=completed_machines,
                        workaround_script=workaround_script,
                        files=files))
            asyncio.get_event_loop().run_until_complete(
                asyncio.gather(*upgrade_functions))

            if "rabbitmq-server" in apps:
                logging.info(
                    "Running complete-cluster-series-upgrade action on leader")
                model.run_action_on_leader(
                    'rabbitmq-server',
                    'complete-cluster-series-upgrade',
                    action_params={})

            if "percona-cluster" in apps:
                logging.info(
                    "Running complete-cluster-series-upgrade action on leader")
                model.run_action_on_leader(
                    'mysql',
                    'complete-cluster-series-upgrade',
                    action_params={})
            model.block_until_all_units_idle()
            logging.info("Finished {}".format(group_name))
        logging.info("Done!")


class OpenStackParallelSeriesUpgrade(ParallelSeriesUpgradeTest):
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
        super(OpenStackParallelSeriesUpgrade, cls).setUpClass()
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


class TrustyXenialSeriesUpgrade(OpenStackParallelSeriesUpgrade):
    """OpenStack Trusty to Xenial Series Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Trusty to Xenial Series Upgrades."""
        super(TrustyXenialSeriesUpgrade, cls).setUpClass()
        cls.from_series = "trusty"
        cls.to_series = "xenial"


class XenialBionicSeriesUpgrade(OpenStackParallelSeriesUpgrade):
    """OpenStack Xenial to Bionic Series Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Xenial to Bionic Series Upgrades."""
        super(XenialBionicSeriesUpgrade, cls).setUpClass()
        cls.from_series = "xenial"
        cls.to_series = "bionic"


class BionicFocalSeriesUpgrade(OpenStackParallelSeriesUpgrade):
    """OpenStack Bionic to FocalSeries Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Xenial to Bionic Series Upgrades."""
        super(BionicFocalSeriesUpgrade, cls).setUpClass()
        cls.from_series = "bionic"
        cls.to_series = "focal"


if __name__ == "__main__":
    from_series = os.environ.get("FROM_SERIES")
    if from_series == "trusty":
        to_series = "xenial"
        series_upgrade_test = TrustyXenialSeriesUpgrade()
    elif from_series == "xenial":
        to_series = "bionic"
        series_upgrade_test = XenialBionicSeriesUpgrade()
    elif from_series == "bionic":
        to_series = "focal"
        series_upgrade_test = BionicFocalSeriesUpgrade()

    else:
        raise Exception("FROM_SERIES is not set to a vailid LTS series")
    series_upgrade_test.setUpClass()
    sys.exit(series_upgrade_test.test_200_run_series_upgrade())
