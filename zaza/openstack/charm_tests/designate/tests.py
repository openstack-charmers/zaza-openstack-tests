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
import re
import logging
import tenacity
import subprocess
import designateclient.v1.domains as domains
import designateclient.v1.records as records
import designateclient.v1.servers as servers
import zaza.model as model
import zaza.openstack.utilities.juju as zaza_juju
from zaza.openstack.charm_tests.designate import (
    BaseDesignateTest,
)


class BaseTests(BaseDesignateTest):
    """Base Designate charm tests."""

    def test_100_services(self):
        """Verify expected services are running."""
        logging.debug('Checking system services on units...')

        model.block_until_service_status(
            self.lead_unit,
            self.designate_svcs,
            'running',
            self.model_name,
            timeout=30
        )

        logging.debug('OK')


class ApiTests(BaseDesignateTest):
    """Designate charm api tests."""

    VALID_INTERFACE = [
        'admin',
        'public',
        'internal'
    ]

    VALID_URL = re.compile(
            r'^(?:http|ftp)s?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # noqa
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S+)$',
            re.IGNORECASE)

    def test_110_service_catalog(self):
        """Verify that the service catalog endpoint data is valid."""
        logging.debug('Checking keystone service catalog data...')
        actual = self.keystone.service_catalog.get_endpoints()
        dns_endpoints = actual['dns']

        for ep in dns_endpoints:
            logging.debug(ep)
            self.assertIsNotNone(ep.get('id'))
            self.assertEqual(ep.get('region'), "RegionOne")
            self.assertIn(ep.get('interface'), self.VALID_INTERFACE)
            self.assertRegexpMatches(ep.get('url'), self.VALID_URL)

    def test_114_designate_api_endpoint(self):
        """Verify the designate api endpoint data."""
        logging.debug('Checking designate api endpoint data...')
        endpoints = self.keystone.endpoints.list()

        for ep in endpoints:
            logging.debug(ep)
            self.assertIsNotNone(ep.id)
            self.assertEqual(ep.region, "RegionOne")
            self.assertIsNotNone(ep.service_id)
            self.assertIn(ep.interface, self.VALID_INTERFACE)
            self.assertRegexpMatches(ep.url, self.VALID_URL)


class KeystoneIdentityRelationTests(BaseDesignateTest):
    """Designate Keystone identity relations charm tests."""

    def test_200_designate_identity_relation(self):
        """Verify the designate to keystone identity-service relation data."""
        logging.debug('Checking designate to keystone identity-service '
                      'relation data...')

        unit_name = 'designate/0'
        remote_unit_name = 'keystone/0'
        relation_name = 'identity-service'
        remote_unit = model.get_unit_from_name(remote_unit_name)
        remote_ip = remote_unit.public_address
        relation = zaza_juju.get_relation_from_unit(
            unit_name,
            remote_unit_name,
            relation_name
        )

        designate_endpoint = "http://{}:9001".format(remote_ip)
        expected = {
            'admin_url': designate_endpoint,
            'internal_url': designate_endpoint,
            'private-address': remote_ip,
            'public_url': designate_endpoint,
            'region': 'RegionOne',
            'service': 'designate',
        }

        for token, value in expected.items():
            r_val = relation.get(token)
            self.assertEqual(
                r_val, value, "token({}) doesn't match".format(token)
            )

    def test_201_keystone_designate_identity_relation(self):
        """Verify the keystone to designate identity-service relation data."""
        logging.debug('Checking keystone:designate identity relation data...')

        unit_name = 'keystone/0'
        remote_unit_name = 'designate/0'
        relation_name = 'identity-service'
        remote_unit = model.get_unit_from_name(remote_unit_name)
        remote_ip = remote_unit.public_address
        relation = zaza_juju.get_relation_from_unit(
            unit_name,
            remote_unit_name,
            relation_name
        )
        expected = {
            'admin_token': 'ubuntutesting',
            'auth_host': remote_ip,
            'auth_port': "35357",
            'auth_protocol': 'http',
            'private-address': remote_ip,
            'service_host': remote_ip,
            'service_port': "5000",
            'service_protocol': 'http',
            'service_tenant': 'services',
            'service_username': 'designate',
        }

        for token, value in expected.items():
            r_val = relation.get(token)
            self.assertEqual(
                r_val, value, "token({}) doesn't match".format(token)
            )

        self.assertIsNotNone(
            relation.get('service_password'),
            "service_password missing"
        )

        self.assertIsNotNone(
            relation.get('service_tenant_id'),
            "service_tenant_id missing"
        )


class AmqpRelationTests(BaseDesignateTest):
    """Designate Rabbit MQ relations charm tests."""

    def test_203_designate_amqp_relation(self):
        """Verify the designate to rabbitmq-server amqp relation data."""
        logging.debug('Checking designate:amqp rabbitmq relation data...')

        unit_name = 'designate/0'
        remote_unit_name = 'rabbitmq-server/0'
        relation_name = 'amqp'
        remote_unit = model.get_unit_from_name(remote_unit_name)
        remote_ip = remote_unit.public_address
        relation = zaza_juju.get_relation_from_unit(
            unit_name,
            remote_unit_name,
            relation_name
        )
        # Get private-address in relation
        rel_private_ip = relation.get('private-address')
        username = relation.get('username')
        vhost = relation.get('vhost')

        self.assertEqual(rel_private_ip, remote_ip)
        self.assertEqual(username, 'designate')
        self.assertEqual(vhost, 'openstack')

    def test_204_amqp_designate_relation(self):
        """Verify the rabbitmq-server to designate amqp relation data."""
        logging.debug('Checking rabbitmq:amqp designate relation data...')

        unit_name = 'rabbitmq-server/0'
        remote_unit_name = 'designate/0'
        relation_name = 'amqp'
        remote_unit = model.get_unit_from_name(remote_unit_name)
        remote_ip = remote_unit.public_address
        relation = zaza_juju.get_relation_from_unit(
            unit_name,
            remote_unit_name,
            relation_name
        )
        # Get private-address in relation
        rel_private_ip = relation.get('private-address')
        username = relation.get('username')
        vhost = relation.get('vhost')

        self.assertEqual(rel_private_ip, remote_ip)
        self.assertEqual(username, 'designate')
        self.assertEqual(vhost, 'openstack')


class NeutronApiRelationTests(BaseDesignateTest):
    """Designate Neutron API relations charm tests."""

    def test_207_designate_neutron_api_relation(self):
        """Verify the designate to neutron-api external-dns relation data."""
        logging.debug('Checking designate:dnsaas relation data...')
        unit_name = 'designate/0'
        remote_unit_name = 'neutron-api/0'
        relation_name = 'dnsaas'
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

    def test_208_neutron_api_designate_relation(self):
        """Verify the neutron-api to designate dnsaas relation data."""
        logging.debug('Checking neutron-api:external-dns relation data...')
        unit_name = 'neutron-api/0'
        remote_unit_name = 'designate/0'
        relation_name = 'external-dns'
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


class BindRelationTests(BaseDesignateTest):
    """Designate Bind relations charm tests."""

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


class ResetAndPauseTests(BaseDesignateTest):
    """Designate charm restart and pause tests."""

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


class ServerCreationTest(BaseDesignateTest):
    """Designate charm server creation tests."""

    TEST_NS1_RECORD = 'ns1.amuletexample.com.'
    TEST_NS2_RECORD = 'ns2.amuletexample.com.'

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


class DomainCreationTests(BaseDesignateTest):
    """Designate charm domain creation tests."""

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
