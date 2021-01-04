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

"""Define class for OpenStack Upgrade."""

import logging
import unittest

from zaza.openstack.utilities import (
    cli as cli_utils,
    upgrade_utils as upgrade_utils,
    openstack as openstack_utils,
    openstack_upgrade as openstack_upgrade,
)
from zaza.openstack.charm_tests.nova.tests import LTSGuestCreateTest


class OpenStackUpgradeVMLaunchBase(object):
    """A base class to peform a simple validation on the cloud.

    This wraps an OpenStack upgrade with a VM launch before and after the
    upgrade.

    This test requires a full OpenStack including at least: keystone, glance,
    nova-cloud-controller, nova-compute, neutron-gateway, neutron-api and
    neutron-openvswitch.

    This class should be used as a base class to the upgrade 'test'.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for OpenStack Upgrades."""
        print("Running OpenStackUpgradeMixin setUpClass")
        super().setUpClass()
        cls.lts = LTSGuestCreateTest()
        cls.lts.setUpClass()

    def test_100_validate_pre_openstack_upgrade_cloud(self):
        """Validate pre openstack upgrade."""
        logging.info("Validate pre-openstack-upgrade: Spin up LTS instance")
        self.lts.test_launch_small_instance()

    def test_500_validate_openstack_upgraded_cloud(self):
        """Validate post openstack upgrade."""
        logging.info("Validate post-openstack-upgrade: Spin up LTS instance")
        self.lts.test_launch_small_instance()


class WaitForMySQL(unittest.TestCase):
    """Helper test to wait on mysql-innodb-cluster to be fully ready.

    In practice this means that there is at least on R/W unit available.
    Sometimes, after restarting units in the mysql-innodb-cluster, all the
    units are R/O until the cluster picks the R/W unit.
    """

    @classmethod
    def setUpClass(cls):
        """Set up class."""
        print("Running OpenstackUpgradeTests setUpClass")
        super().setUpClass()
        cli_utils.setup_logging()

    def test_100_wait_for_happy_mysql_innodb_cluster(self):
        """Wait for mysql cluster to have at least one R/W node."""
        logging.info("Starting wait for an R/W unit.")
        openstack_upgrade.block_until_mysql_innodb_cluster_has_rw()
        logging.info("Done .. all seems well.")


class OpenStackUpgradeTestsFocalUssuri(OpenStackUpgradeVMLaunchBase):
    """Upgrade OpenStack from distro -> cloud:focal-victoria."""

    @classmethod
    def setUpClass(cls):
        """Run setup for OpenStack Upgrades."""
        print("Running OpenstackUpgradeTests setUpClass")
        super().setUpClass()
        cli_utils.setup_logging()

    def test_200_run_openstack_upgrade(self):
        """Run openstack upgrade, but work out what to do."""
        openstack_upgrade.run_upgrade_tests("cloud:focal-victoria")


class OpenStackUpgradeTests(OpenStackUpgradeVMLaunchBase):
    """A Principal Class to encapsulate OpenStack Upgrade Tests.

    A generic Test class that can discover which Ubuntu version and OpenStack
    version to upgrade from.

    TODO: Not used at present.  Use the declarative tests directly that choose
    the version to upgrade to.  The functions that this class depends on need a
    bit more work regarding how the determine which version to go to.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for OpenStack Upgrades."""
        print("Running OpenstackUpgradeTests setUpClass")
        super().setUpClass()
        cli_utils.setup_logging()

    def test_200_run_openstack_upgrade(self):
        """Run openstack upgrade, but work out what to do.

        TODO: This is really inefficient at the moment, and doesn't (yet)
        determine which ubuntu version to work from.  Don't use until we can
        make it better.
        """
        # TODO: work out the most recent Ubuntu version; we assume this is the
        # version that OpenStack is running on.
        ubuntu_version = "focal"
        logging.info("Getting all principle applications ...")
        principle_services = upgrade_utils.get_all_principal_applications()
        logging.info(
            "Getting OpenStack vesions from principal applications ...")
        current_versions = openstack_utils.get_current_os_versions(
            principle_services)
        logging.info("current versions: %s" % current_versions)
        # Find the lowest value openstack release across all services and make
        # sure all servcies are upgraded to one release higher than the lowest
        from_version = upgrade_utils.get_lowest_openstack_version(
            current_versions)
        logging.info("from version: %s" % from_version)
        to_version = upgrade_utils.determine_next_openstack_release(
            from_version)[1]
        logging.info("to version: %s" % to_version)
        # TODO: need to determine the ubuntu base verion that is being upgraded
        target_source = upgrade_utils.determine_new_source(
            ubuntu_version, from_version, to_version, single_increment=True)
        logging.info("target source: %s" % target_source)
        assert target_source is not None
        openstack_upgrade.run_upgrade_tests(target_source)
