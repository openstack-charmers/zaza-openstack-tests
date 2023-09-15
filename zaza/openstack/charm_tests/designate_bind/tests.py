# Copyright 2021 Canonical Ltd.
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

"""Encapsulate designate-bind testing."""
import logging
import os

from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

import zaza.model as zaza_model
import zaza.openstack.charm_tests.test_utils as test_utils


class DesignateBindServiceIPsTest(test_utils.OpenStackBaseTest):
    """Tests for configuration of Service IPs."""

    VIP = ""
    APPLICATION = "designate-bind"
    UNIT = "designate-bind/0"

    def setUp(self):
        """Verify that TEST_VIP00 env variable is set."""
        super().setUp()
        self.VIP = os.environ.get("TEST_VIP00", None)
        if self.VIP is None:
            self.fail("Environment variable 'TEST_VIP00' is required.")

    def test_configure_ips(self):
        """Configure and un-configure 'service_ips' option."""
        config = {"service_ips": self.VIP}

        logging.info("Configuring %s as a Service IP for %s unit.",
                     self.VIP, self.UNIT)
        zaza_model.set_application_config(self.APPLICATION, config)
        zaza_model.wait_for_application_states()

        for attempt in Retrying(wait=wait_fixed(2),
                                retry=retry_if_exception_type(AssertionError),
                                reraise=True,
                                stop=stop_after_attempt(10)):
            with attempt:
                configured_ips = zaza_model.run_on_unit(self.UNIT, "ip addr")
                self.assertIn(self.VIP, configured_ips["Stdout"])

        logging.info("Removing service IP configuration from %s unit.",
                     self.UNIT)
        config["service_ips"] = ""
        zaza_model.set_application_config(self.APPLICATION, config)
        zaza_model.wait_for_application_states()

        for attempt in Retrying(wait=wait_fixed(2),
                                retry=retry_if_exception_type(AssertionError),
                                reraise=True,
                                stop=stop_after_attempt(10)):
            with attempt:
                configured_ips = zaza_model.run_on_unit(self.UNIT, "ip addr")
                self.assertNotIn(self.VIP, configured_ips["Stdout"])
