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

"""Encapsulate designate testing."""
import logging
import tenacity
import subprocess
import designateclient.v1.domains as domains
import designateclient.v1.records as records
import designateclient.v1.servers as servers
import zaza.openstack.utilities.juju as zaza_juju
from zaza.openstack.charm_tests.designate import BaseDesignateTest


class DesignateTests(BaseDesignateTest):
    """Designate charm restart and pause tests."""

    TEST_DOMAIN = 'amuletexample.com.'
    TEST_NS1_RECORD = 'ns1.{}'.format(TEST_DOMAIN)
    TEST_NS2_RECORD = 'ns2.{}'.format(TEST_DOMAIN)
    TEST_WWW_RECORD = "www.{}".format(TEST_DOMAIN)
    TEST_RECORD = {TEST_WWW_RECORD: '10.0.0.23'}

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change disk format and assert then change propagates to the correct
        file and that services are restarted as a result
        """
        # Expected default and alternate values
        set_default = {'debug': 'False'}
        set_alternate = {'debug': 'True'}

        # Services which are expected to restart upon config change,
        # and corresponding config files affected by the change
        conf_file = '/etc/designate/designate.conf'

        # Make config change, check for service restarts
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            {'DEFAULT': {'debug': ['False']}},
            {'DEFAULT': {'debug': ['True']}},
            self.designate_svcs)

    def test_910_pause_and_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(
                self.designate_svcs,
                pgrep_full=False):
            logging.info("Testing pause resume")

    def _get_server_id(self, server_name):
        server_id = None
        for server in self.designate.servers.list():
            if server.name == server_name:
                server_id = server.id
                break
        return server_id

    def _get_test_server_id(self):
        return self._get_server_id(self.TEST_NS2_RECORD)

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=5, max=10),
        reraise=True
    )
    def _wait_on_server_gone(self):
        logging.debug('Waiting for server to disappear')
        return not self._get_test_server_id()

    def test_400_server_creation(self):
        """Simple api calls to create domain."""
        # Designate does not allow the last server to be delete so ensure ns1
        # always present
        if self.post_xenial_queens:
            logging.info('Skipping server creation tests for Queens and above')
            return

        if not self._get_server_id(self.TEST_NS1_RECORD):
            server = servers.Server(name=self.TEST_NS1_RECORD)
            new_server = self.designate.servers.create(server)
            self.assertIsNotNone(new_server)

        logging.debug('Checking if server exists before trying to create it')
        old_server_id = self._get_test_server_id()
        if old_server_id:
            logging.debug('Deleting old server')
            self.designate.servers.delete(old_server_id)
        self._wait_on_server_gone()

        logging.debug('Creating new server')
        server = servers.Server(name=self.TEST_NS2_RECORD)
        new_server = self.designate.servers.create(server)
        self.assertIsNotNone(new_server)

    def _get_domain_id(self, domain_name):
        domain_id = None
        for dom in self.zones_list():
            if isinstance(dom, dict):
                if dom['name'] == domain_name:
                    domain_id = dom['name']
                    break
            else:
                if dom.name == domain_name:
                    domain_id = dom.id
                    break
        return domain_id

    def _get_test_domain_id(self):
        return self._get_domain_id(self.TEST_DOMAIN)

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=5, max=10),
        reraise=True
    )
    def _wait_on_domain_gone(self):
        logging.debug('Waiting for domain to disappear')
        if self._get_test_domain_id():
            raise Exception("Domain Exists")

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=5, max=10),
        reraise=True
    )
    def _wait_to_resolve_test_record(self):
        dns_ip = zaza_juju.get_relation_from_unit(
            'designate/0',
            'designate-bind/0',
            'dns-backend'
        ).get('private-address')

        logging.info('Waiting for dns record to propagate @ {}'.format(dns_ip))
        lookup_cmd = [
            'dig', '+short', '@{}'.format(dns_ip),
            self.TEST_WWW_RECORD]
        cmd_out = subprocess.check_output(
            lookup_cmd, universal_newlines=True).rstrip()
        if not self.TEST_RECORD[self.TEST_WWW_RECORD] == cmd_out:
            raise Exception("Record Doesn't Exist")

    def test_400_domain_creation(self):
        """Simple api calls to create domain."""
        logging.debug('Checking if domain exists before trying to create it')
        old_dom_id = self._get_test_domain_id()
        if old_dom_id:
            logging.debug('Deleting old domain')
            self.zones_delete(old_dom_id)
            self._wait_on_domain_gone()

        logging.debug('Creating new domain')
        domain = domains.Domain(
            name=self.TEST_DOMAIN,
            email="fred@amuletexample.com")

        if self.post_xenial_queens:
            new_domain = self.designate.zones.create(
                name=domain.name, email=domain.email)
        else:
            new_domain = self.designate.domains.create(domain)
        self.assertIsNotNone(new_domain)

        logging.debug('Creating new test record')
        _record = records.Record(
            name=self.TEST_WWW_RECORD,
            type="A",
            data=self.TEST_RECORD[self.TEST_WWW_RECORD])

        if self.post_xenial_queens:
            _domain_id = new_domain['id']
            self.designate.recordsets.create(
                _domain_id, _record.name, _record.type, [_record.data])
        else:
            _domain_id = new_domain.id
            self.designate.records.create(_domain_id, _record)

        self._wait_to_resolve_test_record()

        logging.debug('Tidy up delete test record')
        self.zones_delete(_domain_id)
        logging.debug('OK')
