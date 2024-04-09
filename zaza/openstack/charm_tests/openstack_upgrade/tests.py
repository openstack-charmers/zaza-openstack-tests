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

import zaza.model
import zaza.global_options

from zaza.openstack.utilities import (
    cli as cli_utils,
    upgrade_utils as upgrade_utils,
    openstack as openstack_utils,
    openstack_upgrade as openstack_upgrade,
    exceptions,
    generic,
)
from zaza.openstack.charm_tests.nova.tests import LTSGuestCreateTest


class OpenStackUpgradeVMLaunchBase(unittest.TestCase):
    """A base class to peform a simple validation on the cloud.

    This wraps an OpenStack upgrade with a VM launch before and after the
    upgrade.

    This test requires a full OpenStack including at least: keystone, glance,
    nova-cloud-controller, nova-compute, neutron-gateway, neutron-api and
    neutron-openvswitch.

    This class can be used as a base class to the upgrade 'test'.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for OpenStack Upgrades."""
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
        super().setUpClass()
        cli_utils.setup_logging()

    def test_100_wait_for_happy_mysql_innodb_cluster(self):
        """Wait for mysql cluster to have at least one R/W node."""
        logging.info("Starting wait for an R/W unit.")
        openstack_upgrade.block_until_mysql_innodb_cluster_has_rw()
        logging.info("Done .. all seems well.")


class OpenStackUpgradeTestsByOption(unittest.TestCase):
    """A Principal Class to encapsulate OpenStack Upgrade Tests.

    A generic Test class that uses the options in the tests.yaml to use a charm
    to detect the Ubuntu and OpenStack versions and then workout what to
    upgrade to.

        tests_options:
          openstack-upgrade:
            detect-using-charm: keystone

    This will use the octavia application, detect the ubuntu version and then
    read the config to discover the current OpenStack version.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for OpenStack Upgrades."""
        super().setUpClass()
        cli_utils.setup_logging()

    def test_200_run_openstack_upgrade(self):
        """Run openstack upgrade, but work out what to do."""
        # get the tests_options / openstack-upgrade.detect-using-charm so that
        # the ubuntu version and OpenStack version can be detected.
        try:
            detect_charm = (
                zaza.global_options.get_options()
                .openstack_upgrade.detect_using_charm)
        except KeyError:
            raise exceptions.InvalidTestConfig(
                "Missing tests_options.openstack-upgrade.detect-using-charm "
                "config.")

        unit = zaza.model.get_lead_unit(detect_charm)
        ubuntu_version = generic.get_series(unit)
        logging.info("Current version detected from {} is {}"
                     .format(detect_charm, ubuntu_version))

        logging.info(
            "Getting OpenStack version from %s ..." % detect_charm)
        current_versions = openstack_utils.get_current_os_versions(
            [detect_charm])
        if not current_versions:
            raise exceptions.ApplicationNotFound(
                "No version found for {}?".format(detect_charm))

        logging.info("current version: %s" % current_versions[detect_charm])
        # Find the lowest value openstack release across all services and make
        # sure all servcies are upgraded to one release higher than the lowest
        from_version = upgrade_utils.get_lowest_openstack_version(
            current_versions)
        logging.info("from version: %s" % from_version)
        to_version = upgrade_utils.determine_next_openstack_release(
            from_version)[1]
        logging.info("to version: %s" % to_version)
        target_source = upgrade_utils.determine_new_source(
            ubuntu_version, from_version, to_version, single_increment=True)
        logging.info("target source: %s" % target_source)
        assert target_source is not None
        openstack_upgrade.run_upgrade_tests(target_source)
