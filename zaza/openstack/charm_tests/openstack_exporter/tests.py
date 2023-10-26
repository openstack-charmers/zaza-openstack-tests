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

"""Encapsulate Openstack Exporter testing."""

import requests
import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils


class OpenstackExporterTest(test_utils.OpenStackBaseTest):
    """Class for Openstack Exporter tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running hacluster tests."""
        cls.model_name = zaza.model.get_juju_model()
        cls.test_config = lifecycle_utils.get_charm_config(fatal=False)

    @staticmethod
    def get_internal_ips(application, model_name):
        """Return the internal ip addresses an application."""
        status = zaza.model.get_status(model_name=model_name)
        units = status["applications"][application]["units"]
        return [v.address for v in units.values()]

    def get_openstack_exporter_ips(self):
        """Return the internal ip addresses of the openstack exporter units."""
        return self.get_internal_ips("openstack-exporter", self.model_name)

    def test_openstack_exporter(self):
        """Test gathering metrics from openstack exporter."""
        for ip in self.get_openstack_exporter_ips():
            response = requests.get(f"http://{ip}:9180/metrics")
            response.raise_for_status()
