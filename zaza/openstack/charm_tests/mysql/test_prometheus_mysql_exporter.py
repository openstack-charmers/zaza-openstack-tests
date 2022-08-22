# Copyright 2022 Canonical Ltd.
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

"""MySQL Prometheus Exporter Testing."""

import json

import zaza.model as zaza_model
from zaza.openstack.charm_tests.mysql.tests import MySQLBaseTest


class PrometheusMySQLExporterTest(MySQLBaseTest):
    """Functional tests check prometheus exporter."""

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running mysql tests."""
        super().setUpClass(application_name="mysql-innodb-cluster")
        cls.application = "mysql-innodb-cluster"

    def _exporter_http_check(
        self,
        cmd,
        expected,
    ):
        """Exec check cmd on each unit in the application.

        :param cmd: The check command run on unit
        :type cmd: str
        :param expected: Expected result code
        :type expected: str
        """
        for unit in zaza_model.get_units(self.application):
            result = zaza_model.run_on_unit(unit.name, cmd)
            self.assertEqual(result.get("Code"), expected)

    def _check_service_status_is(
        self,
        active=True,
    ):
        cmd = "systemctl is-active {}".format(
            "snap.mysql-prometheus-exporter.mysqld-exporter.service"
        )
        excepted = "active\n"
        if not active:
            excepted = "inactive\n"
        for unit in zaza_model.get_units(self.application):
            result = zaza_model.run_on_unit(unit.name, cmd)
            self.assertEqual(result.get("stdout"), excepted)

    def test_01_exporter_http_check(self):
        """Check exporter endpoint is working."""
        self._exporter_http_check(
            cmd="curl http://localhost:9104",
            expected="0",
        )

    def test_02_exporter_metrics_http_check(self):
        """Check metrics API is working."""
        cmd = "curl http://localhost:9104/metrics"
        self._exporter_http_check(cmd=cmd, expected="0")

    def test_03_exporter_service_relation_trigger(self):
        """Relation trigger exporter service start/stop."""
        zaza_model.remove_relation(
            self.application,
            "prometheus2:target",
            "mysql-innodb-cluster:prometheus",
        )
        for unit in zaza_model.get_units(self.application):
            zaza_model.block_until_unit_wl_status(unit.name, "active")
        zaza_model.block_until_all_units_idle()
        self._check_service_status_is(active=False)

        # Recover
        zaza_model.add_relation(
            self.application,
            "prometheus2:target",
            "mysql-innodb-cluster:prometheus",
        )
        for unit in zaza_model.get_units(self.application):
            zaza_model.block_until_unit_wl_status(unit.name, "active")
        zaza_model.block_until_all_units_idle()
        self._check_service_status_is(active=True)

    def test_04_snap_config(self):
        """Check snap set config is working."""
        cmd = "sudo snap get mysql-prometheus-exporter mysql -d"
        for unit in zaza_model.get_units(self.application):
            result = zaza_model.run_on_unit(unit.name, cmd)
            json_mysql_config = json.loads(
                result.get("stdout")).get("mysql")
            json_mysql_config.pop("pwd")
            self.assertEqual(
                json_mysql_config,
                {
                    "host": unit.public_address,
                    "port": 3306,
                    "user": "prom_exporter"
                }
            )
