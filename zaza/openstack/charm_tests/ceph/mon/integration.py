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
import requests
import tenacity
import yaml
import zaza.model
from juju import juju
from zaza import sync_wrapper
from zaza.openstack.charm_tests import test_utils as test_utils


async def async_find_cos_model():
    """Find a COS model.

    Look for models first on the current controller, then on a k8s controller.
    Return the first model with a name starting with "cos".
    """
    models = await zaza.controller.async_list_models()
    cos_models = [m for m in models if m.startswith("cos")]
    if cos_models:
        return cos_models[0]
    # Look for a k8s controller
    j = juju.Juju()
    k8s = [
        k for k, v in j.get_controllers().items() if v["type"] == "kubernetes"
    ]
    if not k8s:
        return
    ctrl = juju.Controller()
    await ctrl.connect(k8s[0])
    k8s_models = await ctrl.list_models()
    cos_models = [m for m in k8s_models if m.startswith("cos")]
    await ctrl.disconnect()
    if not cos_models:
        return
    return f"{k8s[0]}:{cos_models[0]}"


find_cos_model = sync_wrapper(async_find_cos_model)


def application_present(name):
    """Check if the application is present in the model."""
    try:
        zaza.model.get_application(name)
        return True
    except KeyError:
        return False


# retry a few times until osd count is larger than 0
@tenacity.retry(
    wait=tenacity.wait_fixed(5),
    retry=tenacity.retry_if_result(lambda result: result <= 0),
    stop=tenacity.stop_after_delay(180),
)
def get_up_osd_count(prometheus_url):
    """Get the number of up OSDs from prometheus."""
    query = "ceph_osd_up"
    response = requests.get(
        f"{prometheus_url}/query", params={"query": query}, verify=False
    )
    data = response.json()
    if data["status"] != "success":
        raise Exception(f"Query failed: {data.get('error', 'Unknown error')}")

    results = data["data"]["result"]
    up_osd_count = sum(int(result["value"][1]) for result in results)
    return up_osd_count


def extract_pool_names(prometheus_url):
    """Extract pool names from prometheus."""
    query = "ceph_pool_metadata"
    response = requests.get(
        f"{prometheus_url}/query", params={"query": query}, verify=False
    )
    data = response.json()
    if data["status"] != "success":
        raise Exception(f"Query failed: {data.get('error', 'Unknown error')}")

    pool_names = []
    results = data.get("data", {}).get("result", [])
    for result in results:
        metric = result.get("metric", {})
        pool_name = metric.get("name")
        if pool_name:
            pool_names.append(pool_name)

    return set(pool_names)


def get_alert_rules(prometheus_url):
    """Get the alert rules from prometheus."""
    response = requests.get(f"{prometheus_url}/rules", verify=False)
    data = response.json()
    if data["status"] != "success":
        raise Exception(f"Query failed: {data.get('error', 'Unknown error')}")

    alert_names = set()
    for obj in data["data"]["groups"]:
        rules = obj.get("rules", [])
        for rule in rules:
            name = rule.get("name")
            if name:
                alert_names.add(name)
    return alert_names


@tenacity.retry(
    wait=tenacity.wait_fixed(5), stop=tenacity.stop_after_delay(180)
)
def get_prom_api_url(grafana_agent):
    """Get the prometheus API URL from the grafana-agent config."""
    ga_yaml = zaza.model.file_contents(
        f"{grafana_agent}/leader", "/etc/grafana-agent.yaml"
    )
    ga = yaml.safe_load(ga_yaml)
    url = ga["integrations"]["prometheus_remote_write"][0]["url"]
    if url.endswith("/write"):
        url = url[:-6]  # lob off the /write
    return url


@tenacity.retry(
    wait=tenacity.wait_fixed(5), stop=tenacity.stop_after_delay(180)
)
def get_dashboards(url, user, passwd):
    """Retrieve a list of dashboards from Grafana."""
    response = requests.get(
        f"{url}/api/search?type=dash-db",
        auth=(user, passwd),
        verify=False,
    )
    if response.status_code != 200:
        raise Exception(f"Failed to retrieve dashboards: {response}")
    dashboards = response.json()
    return dashboards


class COSModelNotFound(Exception):
    """Exception raised when no COS model is found."""

    pass


class COSIntegrationTest(test_utils.BaseCharmTest):
    """Test COS integration with ceph-mon."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running cos integration testing."""
        # look for a cos model on the current controller
        cls.cos_model = find_cos_model()
        if not cls.cos_model:
            raise COSModelNotFound("No COS model found, cannot run tests")
        cls.grafana_details = zaza.model.run_action_on_leader(
            "grafana", "get-admin-password", model_name=cls.cos_model
        ).results
        cls.grafana_agent = "grafana-agent-container"
        super().setUpClass()

    def test_100_integration_setup(self):
        """Test: check that the grafana-agent is related to the ceph-mon."""
        async def have_rel():
            app = await zaza.model.async_get_application(self.application_name)
            spec = f"{self.grafana_agent}:cos-agent"
            return any(r.matches(spec) for r in app.relations)

        zaza.model.block_until(have_rel)

    def test_110_retrieve_metrics(self):
        """Test: retrieve metrics from prometheus."""
        prom_url = get_prom_api_url(self.grafana_agent)
        osd_count = get_up_osd_count(prom_url)
        self.assertGreater(osd_count, 0, "Expected at least one OSD to be up")

        pools = extract_pool_names(prom_url)
        self.assertTrue(".mgr" in pools, "Expected .mgr pool to be present")

    def test_120_retrieve_alert_rules(self):
        """Test: retrieve alert rules from prometheus."""
        prom_url = get_prom_api_url(self.grafana_agent)
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
