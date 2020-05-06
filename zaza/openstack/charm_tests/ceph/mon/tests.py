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

"""Ceph-mon Testing for cinder-ceph."""

import logging

import zaza.model

from zaza.openstack.utilities import (
    generic as generic_utils,
    openstack as openstack_utils,
    exceptions as zaza_exceptions
)
import zaza.openstack.charm_tests.test_utils as test_utils


class CinderCephMonTest(test_utils.OpenStackBaseTest):
    """Verify that the ceph mon units are healthy."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph mon tests with cinder."""
        super().setUpClass()

    # ported from the cinder-ceph Amulet test
    def test_499_ceph_cmds_exit_zero(self):
        """Verify expected state with security-checklist."""
        logging.info("Checking exit values are 0 on ceph commands.")

        units = zaza.model.get_units("ceph-mon", model_name=self.model_name)
        current_release = openstack_utils.get_os_release()
        bionic_train = openstack_utils.get_os_release('bionic_train')
        if current_release < bionic_train:
            units.extend(zaza.model.get_units("cinder-ceph",
                                              model_name=self.model_name))

        commands = [
            'sudo ceph health',
            'sudo ceph mds stat',
            'sudo ceph pg stat',
            'sudo ceph osd stat',
            'sudo ceph mon stat',
        ]

        for unit in units:
            run_commands(unit.name, commands)

    # ported from the cinder-ceph Amulet test
    def test_500_ceph_alternatives_cleanup(self):
        """Check ceph alternatives removed when ceph-mon relation is broken."""
        # Skip this test if release is less than xenial_ocata as in that case
        # cinder HAS a relation with ceph directly and this test would fail
        current_release = openstack_utils.get_os_release()
        xenial_ocata = openstack_utils.get_os_release('xenial_ocata')
        if current_release < xenial_ocata:
            logging.info("Skipping test as release < xenial-ocata")
            return

        units = zaza.model.get_units("cinder-ceph",
                                     model_name=self.model_name)

        # check each unit prior to breaking relation
        for unit in units:
            dir_list = directory_listing(unit.name, "/etc/ceph")
            if 'ceph.conf' in dir_list:
                logging.debug(
                    "/etc/ceph/ceph.conf exists BEFORE relation-broken")
            else:
                raise zaza_exceptions.CephGenericError(
                    "unit: {} - /etc/ceph/ceph.conf does not exist "
                    "BEFORE relation-broken".format(unit.name))

        # remove the relation so that /etc/ceph/ceph.conf is removed
        logging.info("Removing ceph-mon:client <-> cinder-ceph:ceph relation")
        zaza.model.remove_relation(
            "ceph-mon", "ceph-mon:client" "cinder-ceph:ceph")
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()

        # check each unit after to breaking relation
        for unit in units:
            dir_list = directory_listing(unit.name, "/etc/ceph")
            if 'ceph.conf' not in dir_list:
                logging.debug(
                    "/etc/ceph/ceph.conf removed AFTER relation-broken")
            else:
                raise zaza_exceptions.CephGenericError(
                    "unit: {} - /etc/ceph/ceph.conf still exists "
                    "AFTER relation-broken".format(unit.name))

        # Restore cinder-ceph and ceph-mon relation to keep tests idempotent
        logging.info("Restoring ceph-mon:client <-> cinder-ceph:ceph relation")
        zaza.model.add_relation(
            "ceph-mon", "ceph-mon:client" "cinder-ceph:ceph")
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()
        logging.info("... Done.")


def run_commands(unit_name, commands):
    """Run commands on unit.

    Apply context to commands until all variables have been replaced, then
    run the command on the given unit.
    """
    errors = []
    for cmd in commands:
        try:
            generic_utils.assertRemoteRunOK(zaza.model.run_on_unit(
                unit_name,
                cmd))
        except Exception as e:
            errors.append("unit: {}, command: {}, error: {}"
                          .format(unit_name, cmd, str(e)))
    if errors:
        raise zaza_exceptions.CephGenericError("\n".join(errors))


def directory_listing(unit_name, directory):
    """Return a list of files/directories from a directory on a unit.

    :param unit_name: the unit to fetch the directory listing from
    :type unit_name: str
    :param directory: the directory to fetch the listing from
    :type directory: str
    :returns: A listing using "ls -1" on the unit
    :rtype: List[str]
    """
    result = zaza.model.run_on_unit(unit_name, "ls -1 {}".format(directory))
    return result['Stdout'].splitlines()
