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
import unittest
import tenacity
import subprocess

import designateclient.v1.domains as domains
import designateclient.v1.records as records
import designateclient.v1.servers as servers

import zaza.model
import zaza.utilities.juju as juju_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.designate.utils as designate_utils
import zaza.charm_lifecycle.utils as lifecycle_utils


class BaseDesignateTest(test_utils.OpenStackBaseTest):
    """Base for Designate charm tests."""

    DESIGNATE_CONF = '/etc/designate/designate.conf'

    @classmethod
    def setUpClass(cls, application_name=None, model_alias=None):
        """Run class setup for running Designate charm operation tests."""
        application_name = application_name or "designate"
        model_alias = model_alias or ""
        super(BaseDesignateTest, cls).setUpClass(application_name, model_alias)
        os_release = openstack_utils.get_os_release

        if os_release() >= os_release('bionic_rocky'):
            cls.designate_svcs = [
                'designate-agent', 'designate-api', 'designate-central',
                'designate-mdns', 'designate-worker', 'designate-sink',
                'designate-producer',
            ]
        else:
            cls.designate_svcs = [
                'designate-agent', 'designate-api', 'designate-central',
                'designate-mdns', 'designate-pool-manager', 'designate-sink',
                'designate-zone-manager',
            ]

        # Get keystone session
        cls.post_xenial_queens = os_release() >= os_release('xenial_queens')
        overcloud_auth = openstack_utils.get_overcloud_auth()
        keystone = openstack_utils.get_keystone_client(overcloud_auth)

        keystone_session = openstack_utils.get_overcloud_keystone_session()
        if cls.post_xenial_queens:
            cls.designate = openstack_utils.get_designate_session_client(
                session=keystone_session
            )
            cls.domain_list = cls.designate.zones.list
            cls.domain_delete = cls.designate.zones.delete
            cls.domain_create = cls.designate.zones.create
        else:
            # Authenticate admin with designate endpoint
            designate_ep = keystone.service_catalog.url_for(
                service_type='dns',
                interface='publicURL')
            keystone_ep = keystone.service_catalog.url_for(
                service_type='identity',
                interface='publicURL')
            cls.designate = openstack_utils.get_designate_session_client(
                version=1,
                auth_url=keystone_ep,
                token=keystone_session.get_token(),
                tenant_name="admin",
                endpoint=designate_ep)
            cls.domain_list = cls.designate.domains.list
            cls.domain_delete = cls.designate.domains.delete
            cls.domain_create = cls.designate.domains.create
            cls.server_list = cls.designate.servers.list
            cls.server_create = cls.designate.servers.create
            cls.server_delete = cls.designate.servers.delete

    @tenacity.retry(
        retry=tenacity.retry_if_result(lambda ret: ret is not None),
        # sleep for 2mins to allow 1min cron job to run...
        wait=tenacity.wait_fixed(120),
        stop=tenacity.stop_after_attempt(2))
    def _retry_check_commands_on_units(self, cmds, units):
        return generic_utils.check_commands_on_units(cmds, units)


class DesignateAPITests(BaseDesignateTest):
    """Tests interact with designate api."""

    TEST_DOMAIN = 'amuletexample.com.'
    TEST_NS1_RECORD = 'ns1.{}'.format(TEST_DOMAIN)
    TEST_NS2_RECORD = 'ns2.{}'.format(TEST_DOMAIN)
    TEST_WWW_RECORD = "www.{}".format(TEST_DOMAIN)
    TEST_RECORD = {TEST_WWW_RECORD: '10.0.0.23'}
    TEST_DOMAIN_EMAIL = 'fred@amuletexample.com'

    def _get_server_id(self, server_name=None, server_id=None):
        for srv in self.server_list():
            if isinstance(srv, dict):
                if srv['id'] == server_id or srv['name'] == server_name:
                    return srv['id']
            elif srv.name == server_name or srv.id == server_id:
                return srv.id
        return None

    def _wait_on_server_gone(self, server_id):
        @tenacity.retry(
            wait=tenacity.wait_exponential(multiplier=1, min=5, max=10),
            reraise=True
        )
        def wait():
            logging.debug('Waiting for server %s to disappear', server_id)
            if self._get_server_id(server_id=server_id):
                raise Exception("Server Exists")
        self.server_delete(server_id)
        return wait()

    def test_300_default_soa_config_options(self):
        """Configure default SOA options."""
        test_domain = "test_300_example.com."
        DEFAULT_TTL = 60
        alternate_config = {'default-soa-minimum': 600,
                            'default-ttl': DEFAULT_TTL,
                            'default-soa-refresh-min': 300,
                            'default-soa-refresh-max': 400,
                            'default-soa-retry': 30}
        with self.config_change({}, alternate_config, "designate",
                                reset_to_charm_default=True):
            for key, value in alternate_config.items():
                config_key = key.replace('-', '_')
                logging.info('Blocking until %s has key %s',
                             self.DESIGNATE_CONF, config_key)
                expected = "\n%s = %s\n" % (config_key, value)
                zaza.model.block_until_file_has_contents(self.application_name,
                                                         self.DESIGNATE_CONF,
                                                         expected)
            logging.info('Creating domain %s', test_domain)
            domain = domains.Domain(name=test_domain,
                                    email=self.TEST_DOMAIN_EMAIL)

            if self.post_xenial_queens:
                new_domain = self.domain_create(
                    name=domain.name, email=domain.email)
                domain_id = new_domain['id']
            else:
                new_domain = self.domain_create(domain)
                domain_id = new_domain.id

            self.assertIsNotNone(new_domain)
            self.assertEqual(new_domain['ttl'], DEFAULT_TTL)

            logging.info('Tidy up delete test record %s', domain_id)
            self._wait_on_domain_gone(domain_id)
            logging.info('Done with deletion of domain %s', domain_id)

    def test_400_server_creation(self):
        """Simple api calls to create a server."""
        # Designate does not allow the last server to be deleted so ensure
        # that ns1 is always present
        if self.post_xenial_queens:
            logging.info('Skipping server creation tests for Queens and above')
            return

        if not self._get_server_id(server_name=self.TEST_NS1_RECORD):
            server = servers.Server(name=self.TEST_NS1_RECORD)
            new_server = self.server_create(server)
            self.assertIsNotNone(new_server)

        logging.debug('Checking if server exists before trying to create it')
        old_server_id = self._get_server_id(server_name=self.TEST_NS2_RECORD)
        if old_server_id:
            logging.debug('Deleting old server')
            self._wait_on_server_gone(old_server_id)

        logging.debug('Creating new server')
        server = servers.Server(name=self.TEST_NS2_RECORD)
        new_server = self.server_create(server)
        self.assertIsNotNone(new_server, "Failed to Create Server")
        self._wait_on_server_gone(self._get_server_id(self.TEST_NS2_RECORD))

    def _get_domain_id(self, domain_name=None, domain_id=None):
        for dom in self.domain_list():
            if isinstance(dom, dict):
                if dom['id'] == domain_id or dom['name'] == domain_name:
                    return dom['id']
            elif dom.id == domain_id or dom.name == domain_name:
                return dom.id
        return None

    def _wait_on_domain_gone(self, domain_id):
        @tenacity.retry(
            wait=tenacity.wait_exponential(multiplier=1, min=5, max=10),
            reraise=True
        )
        def wait():
            logging.info('Waiting for domain %s to disappear', domain_id)
            if self._get_domain_id(domain_id=domain_id):
                raise Exception("Domain Exists")
        self.domain_delete(domain_id)
        wait()

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=5, max=10),
        reraise=True
    )
    def _wait_to_resolve_test_record(self):
        dns_ip = juju_utils.get_relation_from_unit(
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
        old_dom_id = self._get_domain_id(domain_name=self.TEST_DOMAIN)
        if old_dom_id:
            logging.debug('Deleting old domain')
            self._wait_on_domain_gone(old_dom_id)

        logging.debug('Creating new domain')
        domain = domains.Domain(
            name=self.TEST_DOMAIN,
            email=self.TEST_DOMAIN_EMAIL)

        if self.post_xenial_queens:
            new_domain = self.domain_create(
                name=domain.name, email=domain.email)
        else:
            new_domain = self.domain_create(domain)
        self.assertIsNotNone(new_domain)

        logging.debug('Creating new test record')
        _record = records.Record(
            name=self.TEST_WWW_RECORD,
            type="A",
            data=self.TEST_RECORD[self.TEST_WWW_RECORD])

        if self.post_xenial_queens:
            domain_id = new_domain['id']
            self.designate.recordsets.create(
                domain_id, _record.name, _record.type, [_record.data])
        else:
            domain_id = new_domain.id
            self.designate.records.create(domain_id, _record)

        self._wait_to_resolve_test_record()

        logging.debug('Tidy up delete test record')
        self._wait_on_domain_gone(domain_id)
        logging.debug('OK')


class DesignateCharmTests(BaseDesignateTest):
    """Designate charm restart and pause tests."""

    def test_900_restart_on_config_change(self):
        """Checking restart happens on config change.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result
        """
        # Services which are expected to restart upon config change,
        # and corresponding config files affected by the change
        conf_file = '/etc/designate/designate.conf'

        # Make config change, check for service restarts
        self.restart_on_changed_debug_oslo_config_file(
            conf_file,
            self.designate_svcs,
        )

    def test_910_pause_and_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started
        """
        with self.pause_resume(
                self.designate_svcs,
                pgrep_full=False):
            logging.info("Testing pause resume")


class DesignateMonitoringTests(BaseDesignateTest):
    """Designate charm monitoring tests."""

    def test_nrpe_configured(self):
        """Confirm that the NRPE service check files are created."""
        units = zaza.model.get_units(self.application_name)
        cmds = []
        for check_name in self.designate_svcs:
            cmds.append(
                'egrep -oh /usr/local.* /etc/nagios/nrpe.d/'
                'check_{}.cfg'.format(check_name)
            )
        ret = self._retry_check_commands_on_units(cmds, units)
        if ret:
            logging.info(ret)
        self.assertIsNone(ret, msg=ret)


class DesignateTests(DesignateAPITests, DesignateCharmTests,
                     DesignateMonitoringTests):
    """Collection of all Designate test classes."""

    pass


class DesignateBindExpand(BaseDesignateTest):
    """Test expanding and shrinking bind."""

    TEST_DOMAIN = 'zazabindtesting.com.'
    TEST_NS1_RECORD = 'ns1.{}'.format(TEST_DOMAIN)
    TEST_NS2_RECORD = 'ns2.{}'.format(TEST_DOMAIN)
    TEST_WWW_RECORD = "www.{}".format(TEST_DOMAIN)
    TEST_RECORD = {TEST_WWW_RECORD: '10.0.0.24'}

    def test_expand_and_contract(self):
        """Test expanding and shrinking bind."""
        test_config = lifecycle_utils.get_charm_config(fatal=False)
        states = test_config.get("target_deploy_status", {})
        if not self.post_xenial_queens:
            raise unittest.SkipTest("Test not supported before Queens")

        domain = designate_utils.create_or_return_zone(
            self.designate,
            name=self.TEST_DOMAIN,
            email="test@zaza.com")

        designate_utils.create_or_return_recordset(
            self.designate,
            domain['id'],
            'www',
            'A',
            [self.TEST_RECORD[self.TEST_WWW_RECORD]])

        # Test record is in bind and designate
        designate_utils.check_dns_entry(
            self.designate,
            self.TEST_RECORD[self.TEST_WWW_RECORD],
            self.TEST_DOMAIN,
            record_name=self.TEST_WWW_RECORD)

        logging.info('Adding a designate-bind unit')
        zaza.model.add_unit('designate-bind', wait_appear=True)
        zaza.model.block_until_all_units_idle()
        zaza.model.wait_for_application_states(states=states)

        logging.info('Performing DNS lookup on all units')
        designate_utils.check_dns_entry(
            self.designate,
            self.TEST_RECORD[self.TEST_WWW_RECORD],
            self.TEST_DOMAIN,
            record_name=self.TEST_WWW_RECORD)

        units = zaza.model.get_status().applications['designate-bind']['units']
        doomed_unit = sorted(units.keys())[0]
        logging.info('Removing {}'.format(doomed_unit))
        zaza.model.destroy_unit(
            'designate-bind',
            doomed_unit,
            wait_disappear=True)
        zaza.model.block_until_all_units_idle()
        zaza.model.wait_for_application_states(states=states)

        logging.info('Performing DNS lookup on all units')
        designate_utils.check_dns_entry(
            self.designate,
            self.TEST_RECORD[self.TEST_WWW_RECORD],
            self.TEST_DOMAIN,
            record_name=self.TEST_WWW_RECORD)
