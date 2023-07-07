# Copyright 2023 Canonical Ltd.
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

"""RabbitMQ K8S Testing."""

import tenacity
import rabbitmq_admin

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.utilities.juju as juju_utils


class RabbitMQK8STest(test_utils.BaseCharmTest):
    """Tests for rabbit on K8s."""

    def get_service_account(self):
        """Get service account details."""
        result = zaza.model.run_action_on_leader(
            'rabbitmq',
            'get-operator-info',
            raise_on_failure=False).data['results']
        return (result['operator-user'], result['operator-password'])

    def get_mgr_endpoint(self):
        """Get url for management api."""
        public_address = juju_utils.get_application_status(
            'rabbitmq').public_address
        return "http://{}:{}".format(public_address, 15672)

    def get_connection(self):
        """Return an api connection."""
        username, password = self.get_service_account()
        mgmt_url = self.get_mgr_endpoint()
        connection = rabbitmq_admin.AdminAPI(
            url=mgmt_url, auth=(username, password)
        )
        return connection

    def test_get_operator_info_action(self):
        """Test running get-operator-info action."""
        user, password = self.get_service_account()
        self.assertEqual(user, "operator")

    @tenacity.retry(
        reraise=True,
        wait=tenacity.wait_fixed(30),
        stop=tenacity.stop_after_attempt(2))
    def test_query_api(self):
        """Test querying managment api."""
        conn = self.get_connection()
        self.assertEqual(conn.overview()['product_name'], "RabbitMQ")
