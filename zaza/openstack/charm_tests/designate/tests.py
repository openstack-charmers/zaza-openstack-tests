# Copyright 2018 Canonical Ltd.
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
import zaza.model as model
import zaza.openstack.utilities.juju as zaza_juju
from zaza.openstack.charm_tests.designate import (
    BaseDesignateTest,
)
import zaza.openstack.utilities.openstack as openstack_utils


class BaseTests(BaseDesignateTest):
    """Base Designate charm tests."""

    def test_100_services(self):
        """Verify expected services are running."""
        logging.debug('Checking system services on units...')

        model.block_until_service_status(
            self.application_name,
            self.designate_svcs,
            'running',
            self.model_name,
            timeout=30
        )

        logging.debug('OK')


class BindTests(BaseDesignateTest):
    """Designate Bind charm tests."""

    TEST_DOMAIN = 'amuletexample.com.'
    TEST_WWW_RECORD = "www.{}".format(TEST_DOMAIN)
    TEST_RECORD = {TEST_WWW_RECORD: '10.0.0.23'}

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
    def _wait_to_resolve_test_record(self, dns_ip):
        logging.info('Waiting for dns record to propagate @ {}'.format(dns_ip))
        lookup_cmd = [
            'dig', '+short', '@{}'.format(dns_ip),
            self.TEST_WWW_RECORD]
        cmd_out = subprocess.check_output(
            lookup_cmd, universal_newlines=True).rstrip()
        if not self.TEST_RECORD[self.TEST_WWW_RECORD] == cmd_out:
            raise Exception("Record Doesn't Exist")

    def test_205_designate_designate_bind_relation(self):
        """Verify the designate to designate-bind dns-backend relation data."""
        logging.debug('Checking designate:designate-bind dns-backend relation'
                      'data...')

        unit_name = 'designate/0'
        remote_unit_name = 'designate-bind/0'
        relation_name = 'dns-backend'
        remote_unit = model.get_unit_from_name(remote_unit_name)
        remote_ip = remote_unit.public_address
        relation = zaza_juju.get_relation_from_unit(
            unit_name,
            remote_unit_name,
            relation_name
        )
        # Get private-address in relation
        rel_private_ip = relation.get('private-address')
        # The private address in relation should match designate-bind/0 address
        self.assertEqual(rel_private_ip, remote_ip)

    def test_206_designate_bind_designate_relation(self):
        """Verify the designate_bind to designate dns-backend relation data."""
        logging.debug('Checking designate-bind:designate dns-backend relation'
                      'data...')

        unit_name = 'designate-bind/0'
        remote_unit_name = 'designate/0'
        relation_name = 'dns-backend'
        remote_unit = model.get_unit_from_name(remote_unit_name)
        remote_ip = remote_unit.public_address
        relation = zaza_juju.get_relation_from_unit(
            unit_name,
            remote_unit_name,
            relation_name
        )
        # Get private-address in relation
        rel_private_ip = relation.get('private-address')
        # The private address in relation should match designate-bind/0 address
        self.assertEqual(rel_private_ip, remote_ip)

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

        dns_ip = zaza_juju.get_relation_from_unit(
            'designate/0',
            'designate-bind/0',
            'dns-backend'
        ).get('private-address')
        self._wait_to_resolve_test_record(dns_ip)

        logging.debug('Tidy up delete test record')
        self.zones_delete(_domain_id)
        logging.debug('OK')
