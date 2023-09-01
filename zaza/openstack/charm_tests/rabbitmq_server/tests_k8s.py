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

import logging
import pika
import tenacity
import urllib
import rabbitmq_admin

import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.utilities.juju as juju_utils


class RabbitMQK8STest(test_utils.BaseCharmTest):
    """Tests for rabbit on K8s."""

    TEST_USER = "zazauser"
    TEST_PASSWORD = "password"
    TEST_VHOST = "/"
    TEST_QUEUE = "zaza"
    APPLICATION_NAME = "rabbitmq"

    @tenacity.retry(
        reraise=True,
        wait=tenacity.wait_fixed(30),
        stop=tenacity.stop_after_attempt(2),
    )
    def check_mgr_api(self):
        """Test querying managment api."""
        conn = self.get_mgr_connection()
        self.assertEqual(conn.overview()["product_name"], "RabbitMQ")

    def setUp(self):
        """Run class setup for running tests."""
        super(RabbitMQK8STest, self).setUp()
        self.check_mgr_api()
        mgr_conn = self.get_mgr_connection()
        mgr_conn.create_user(self.TEST_USER, self.TEST_PASSWORD)
        mgr_conn.create_user_permission(
            self.TEST_USER,
            self.TEST_VHOST,
            configure=".*",
            write=".*",
            read=".*",
        )

    @property
    def expected_statuses(self):
        """Collect expected statuses from config."""
        test_config = lifecycle_utils.get_charm_config(fatal=False)
        return test_config.get("target_deploy_status", {})

    def get_service_account(self):
        """Get service account details."""
        result = zaza.model.run_action_on_leader(
            self.APPLICATION_NAME, "get-operator-info", raise_on_failure=False
        ).data["results"]
        return (result["operator-user"], result["operator-password"])

    def get_mgr_endpoint(self):
        """Get url for management api."""
        public_address = juju_utils.get_k8s_ingress_ip(self.APPLICATION_NAME)
        return "http://{}:{}".format(public_address, 15672)

    def get_client_endpoint(self):
        """Get url for management api."""
        public_address = juju_utils.get_k8s_ingress_ip(self.APPLICATION_NAME)
        return (public_address, 5672)

    def get_mgr_connection(self):
        """Return an api connection."""
        username, password = self.get_service_account()
        mgmt_url = self.get_mgr_endpoint()
        connection = rabbitmq_admin.AdminAPI(
            url=mgmt_url, auth=(username, password)
        )
        return connection

    def get_client_connection(self):
        """Return an api connection."""
        credentials = pika.PlainCredentials(self.TEST_USER, self.TEST_PASSWORD)
        ip, port = self.get_client_endpoint()
        parameters = pika.ConnectionParameters(ip, port, "/", credentials)
        connection = pika.BlockingConnection(parameters)
        return connection

    def get_queue(self, conn, vhost, queue):
        """Return a list of nodes in the RabbitMQ cluster."""
        return conn._api_get(
            "/api/queues/{}/{}".format(
                urllib.parse.quote_plus(vhost), urllib.parse.quote_plus(queue)
            )
        )

    def _test_010_get_operator_info_action(self):
        """Test running get-operator-info action."""
        user, password = self.get_service_account()
        self.assertEqual(user, "operator")

    def get_test_queue_members(self, mgr_conn):
        """Return list of members of the test queue."""
        return self.get_queue(mgr_conn, self.TEST_VHOST, self.TEST_QUEUE)[
            "members"
        ]

    def create_test_queue(self):
        """Create test queue."""
        client_conn = self.get_client_connection()
        channel = client_conn.channel()
        channel.queue_declare(
            queue=self.TEST_QUEUE,
            durable=True,
            arguments={"x-queue-type": "quorum"},
        )

    def test_quorum_queue_management(self):
        """Test charm management for quorum queues."""
        if len(zaza.model.get_units("rabbitmq")) != 1:
            self.skipTest(
                "Unexpected number of units. There most be only one unit for "
                "this test to run."
            )
        logging.info("Creating test queue")
        self.create_test_queue()

        logging.info("Ensuring test queue has 1 member.")
        mgr_conn = self.get_mgr_connection()
        self.assertEqual(len(self.get_test_queue_members(mgr_conn)), 1)

        logging.info("Adding 3 units")
        # Add 3 additional units. The queue should automatically have the new
        # units added as members
        zaza.model.scale(self.APPLICATION_NAME, scale_change=3, wait=True)
        logging.info("Waiting till model is idle")
        zaza.model.block_until_all_units_idle()
        logging.info("Wait for status ready")
        zaza.model.wait_for_application_states(states=self.expected_statuses)

        logging.info("Checking queue has replicas on 3 of the 4 units.")
        members = self.get_test_queue_members(mgr_conn)
        self.assertEqual(len(members), 3)

        # target_member is the member going to be removed from queue and then
        # added back
        target_member = members[0]
        target_unit = (
            target_member.split("@")[-1].split(".")[0].replace("-", "/")
        )
        logging.info(
            "Running action to remove unit {} from queue {}".format(
                target_unit, self.TEST_QUEUE
            )
        )
        zaza.model.run_action_on_leader(
            "rabbitmq",
            "delete-member",
            action_params={
                "queue-name": self.TEST_QUEUE,
                "unit-name": target_unit,
                "vhost": self.TEST_VHOST,
            },
        )
        logging.info(
            "Waiting for leader to warn a queue exists with insufficent "
            "members"
        )
        zaza.model.block_until_unit_wl_message_match(
            zaza.model.get_lead_unit(self.APPLICATION_NAME).name,
            "WARNING.*insufficient members",
        )
        self.assertNotIn(target_member, self.get_test_queue_members(mgr_conn))

        logging.info(
            "Running action to add unit {} to queue {}".format(
                target_unit, self.TEST_QUEUE
            )
        )
        zaza.model.run_action_on_leader(
            self.APPLICATION_NAME,
            "add-member",
            action_params={
                "queue-name": self.TEST_QUEUE,
                "unit-name": target_unit,
                "vhost": self.TEST_VHOST,
            },
        )
        logging.info(
            "Waiting for leader to remove insufficent members warning"
        )
        zaza.model.block_until_unit_wl_message_match(
            zaza.model.get_lead_unit(self.APPLICATION_NAME).name, "^$"
        )
        self.assertIn(target_member, self.get_test_queue_members(mgr_conn))
