# Copyright 2024 Canonical Ltd.
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

"""Integration tests for ceph-mon."""

import unittest

import zaza.model
from zaza.openstack.charm_tests import test_utils as test_utils

from openstack.charm_tests.ceph.mon.tests import (
    get_prom_api_url,
    get_up_osd_count,
    extract_pool_names,
    get_alert_rules,
    get_dashboards,
)


class COSIntegrationTest(test_utils.BaseCharmTest):
    """Test COS integration with ceph-mon."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running cos integration testing."""
        # skip if there are no COS models
        cos_models = [
            m for m in zaza.controller.list_models() if m.startswith("cos")
        ]
        if not cos_models:
            raise unittest.SkipTest("No COS models found")

        cls.cos_model = cos_models[0]

        cls.grafana_details = zaza.model.run_action_on_leader(
            "grafana", "get-admin-password", model_name=cls.cos_model
        ).results

        super().setUpClass()

    def test_100_integration_setup(self):
        """Test: check that the grafana-agent is related to the ceph-mon."""
        async def have_rel():
            app = await zaza.model.async_get_application(self.application_name)
            spec = "grafana-agent:cos-agent"
            return any(r.matches(spec) for r in app.relations)

        zaza.model.block_until(have_rel)

    def test_110_retrieve_metrics(self):
        """Test: retrieve metrics from prometheus."""
        prom_url = get_prom_api_url()
        osd_count = get_up_osd_count(prom_url)
        self.assertGreater(osd_count, 0, "Expected at least one OSD to be up")

        pools = extract_pool_names(prom_url)
        self.assertTrue(".mgr" in pools, "Expected .mgr pool to be present")

    def test_120_retrieve_alert_rules(self):
        """Test: retrieve alert rules from prometheus."""
        prom_url = get_prom_api_url()
        alert_rules = get_alert_rules(prom_url)
        self.assertTrue(
            "CephHealthError" in alert_rules,
            "Expected CephHealthError alert rule",
        )

    def test_200_dashboards(self):
        """Test: retrieve dashboards from Grafana."""
        dashboards = get_dashboards(
            self.grafana_details["url"],
            "admin",
            self.grafana_details["admin-password"],
        )
        dashboard_set = {d["title"] for d in dashboards}
        expect_dashboards = [
            "Ceph Cluster - Advanced",
            "Ceph OSD Host Details",
            "Ceph OSD Host Overview",
            "Ceph Pool Details",
            "Ceph Pools Overview",
            "MDS Performance",
            "OSD device details",
            "OSD Overview",
            "RBD Details",
            "RBD Overview",
            "RGW Instance Detail",
            "RGW Overview",
            "RGW Sync Overview",
        ]
        for d in expect_dashboards:
            self.assertIn(
                d, dashboard_set, f"Expected dashboard {d} not found"
            )
