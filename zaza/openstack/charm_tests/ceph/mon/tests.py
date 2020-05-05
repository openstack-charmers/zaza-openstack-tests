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
import unittest

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
