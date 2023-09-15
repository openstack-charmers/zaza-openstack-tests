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
import juju
import zaza

from zaza import model
from zaza.openstack.utilities import (
    cli as cli_utils,
    upgrade_utils as upgrade_utils,
)
from zaza.openstack.charm_tests.nova.tests import LTSGuestCreateTest
from zaza.openstack.utilities import (
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
        # NOTE(ajkavanagh): Set the jujulib Connection frame size to 4GB to
        # cope with all the outputs from series upgrade; long term, don't send
        # that output back, which will require that the upgrade function in the
        # charm doesn't capture the output of the upgrade in the action, but
        # instead puts it somewhere that can by "juju scp"ed.
        juju.client.connection.Connection.MAX_FRAME_SIZE = 2**32
        cli_utils.setup_logging()
        cls.from_series = None
        cls.to_series = None
        cls.workaround_script = None
        cls.vault_unsealer = None
        cls.files = []

    def test_200_run_series_upgrade(self):
        """Run series upgrade."""
        # Set Feature Flag
        os.environ["JUJU_DEV_FEATURE_FLAGS"] = "upgrade-series"
        upgrade_groups = upgrade_utils.get_series_upgrade_groups(
            extra_filters=[_filter_etcd, _filter_easyrsa],
            target_series=self.to_series)
        from_series = self.from_series
        to_series = self.to_series
        vault_unsealer = self.vault_unsealer
        completed_machines = []
        workaround_script = None
        files = []
        applications = model.get_status().applications
        for group_name, apps in upgrade_groups:
            logging.info("About to upgrade {} from {} to {}".format(
                group_name, from_series, to_series))
            upgrade_functions = []
            if group_name in ["Database Services",
                              "Stateful Services",
                              "Data Plane",
                              "sweep_up"]:
                logging.info("Going to upgrade {} unit by unit".format(apps))
                upgrade_function = \
                    parallel_series_upgrade.serial_series_upgrade
            else:
                logging.info("Going to upgrade {} all at once".format(apps))
                upgrade_function = \
                    parallel_series_upgrade.parallel_series_upgrade

            # allow up to 4 parallel upgrades at a time.  This is to limit the
            # amount of data/calls that asyncio is handling as it's gets
            # unstable if all the applications are done at the same time.
            sem = asyncio.Semaphore(4)
            for charm_name in apps:
                if applications[charm_name]["series"] == to_series:
                    logging.warn("{} already has series {}, skipping".format(
                        charm_name, to_series))
                    continue
                charm = applications[charm_name]['charm']
                name = upgrade_utils.extract_charm_name_from_url(charm)
                upgrade_config = parallel_series_upgrade.app_config(
                    name, vault_unsealer)
                upgrade_functions.append(
                    wrap_coroutine_with_sem(
                        sem,
                        upgrade_function(
                            charm_name,
                            **upgrade_config,
                            from_series=from_series,
                            to_series=to_series,
                            completed_machines=completed_machines,
                            workaround_script=workaround_script,
                            files=files)))
            zaza.run(asyncio.gather(*upgrade_functions))
            model.block_until_all_units_idle()
            logging.info("Finished {}".format(group_name))
        logging.info("Done!")


async def wrap_coroutine_with_sem(sem, coroutine):
    """Wrap a coroutine with a semaphore to limit concurrency.

    :param sem: The semaphore to limit concurrency
    :type sem: asyncio.Semaphore
    :param coroutine: the corouting to limit concurrency
    :type coroutine: types.CoroutineType
    """
    async with sem:
        await coroutine


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
        """Run setup for Bionic to Focal Series Upgrades."""
        super(BionicFocalSeriesUpgrade, cls).setUpClass()
        cls.from_series = "bionic"
        cls.to_series = "focal"


class FocalJammySeriesUpgrade(OpenStackParallelSeriesUpgrade):
    """OpenStack Bionic to FocalSeries Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Focal to Jammy Series Upgrades."""
        super(BionicFocalSeriesUpgrade, cls).setUpClass()
        cls.from_series = "focal"
        cls.to_series = "jammy"


class UbuntuLiteParallelSeriesUpgrade(unittest.TestCase):
    """ubuntu Lite Parallel Series Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Series Upgrades."""
        cli_utils.setup_logging()
        cls.from_series = None
        cls.to_series = None

    def test_200_run_series_upgrade(self):
        """Run series upgrade."""
        # Set Feature Flag
        os.environ["JUJU_DEV_FEATURE_FLAGS"] = "upgrade-series"
        parallel_series_upgrade.upgrade_ubuntu_lite(
            from_series=self.from_series,
            to_series=self.to_series
        )


class TrustyXenialSeriesUpgradeUbuntu(UbuntuLiteParallelSeriesUpgrade):
    """OpenStack Trusty to Xenial Series Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Trusty to Xenial Series Upgrades."""
        super(TrustyXenialSeriesUpgradeUbuntu, cls).setUpClass()
        cls.from_series = "trusty"
        cls.to_series = "xenial"


class XenialBionicSeriesUpgradeUbuntu(UbuntuLiteParallelSeriesUpgrade):
    """OpenStack Xenial to Bionic Series Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Xenial to Bionic Series Upgrades."""
        super(XenialBionicSeriesUpgradeUbuntu, cls).setUpClass()
        cls.from_series = "xenial"
        cls.to_series = "bionic"


class BionicFocalSeriesUpgradeUbuntu(UbuntuLiteParallelSeriesUpgrade):
    """OpenStack Bionic to FocalSeries Upgrade."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Xenial to Bionic Series Upgrades."""
        super(BionicFocalSeriesUpgradeUbuntu, cls).setUpClass()
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
