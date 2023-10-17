#!/usr/bin/env python3

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

"""Collection of tests for vault."""

import contextlib
import json
import logging
import subprocess
import unittest
import uuid

import tenacity
from hvac.exceptions import InternalServerError

import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.charm_tests.vault.utils as vault_utils
import zaza.openstack.utilities.cert
import zaza.openstack.utilities.openstack
import zaza.model


@tenacity.retry(
    retry=tenacity.retry_if_exception_type(InternalServerError),
    retry_error_callback=lambda retry_state: False,
    wait=tenacity.wait_fixed(2),  # interval between retries
    stop=tenacity.stop_after_attempt(10))  # retry 10 times
def retry_hvac_client_authenticated(client):
    """Check hvac client is authenticated with retry.

    If is_authenticated() raise exception for all retries,
    return False(which is done by `retry_error_callback`).
    Otherwise, return whatever the returned value.
    """
    return client.hvac_client.is_authenticated()


class BaseVaultTest(test_utils.OpenStackBaseTest):
    """Base class for vault tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Vault tests."""
        cls.model_name = zaza.model.get_juju_model()
        cls.lead_unit = zaza.model.get_lead_unit_name(
            "vault", model_name=cls.model_name)
        cls.clients = vault_utils.get_clients()
        cls.vip_client = vault_utils.get_vip_client()
        if cls.vip_client:
            cls.clients.append(cls.vip_client)
        cls.vault_creds = vault_utils.get_credentials()

        # This little dance is to ensure a correct init and unseal sequence,
        # for the case of vault with the raft backend.
        # It will also work fine in other cases.
        # The wait functions will raise AssertionErrors on timeouts.
        init_client = vault_utils.wait_and_get_initialized_client(cls.clients)
        vault_utils.unseal_all([init_client], cls.vault_creds['keys'][0])
        vault_utils.wait_until_all_initialised(cls.clients)
        vault_utils.unseal_all(cls.clients, cls.vault_creds['keys'][0])

        vault_utils.auth_all(cls.clients, cls.vault_creds['root_token'])
        vault_utils.wait_for_ha_settled(cls.clients)
        vault_utils.ensure_secret_backend(cls.clients[0])

    def tearDown(self):
        """Tun test cleanup for Vault tests."""
        vault_utils.unseal_all(self.clients, self.vault_creds['keys'][0])

    @contextlib.contextmanager
    def pause_resume(self, services, pgrep_full=False):
        """Override pause_resume for Vault behavior."""
        zaza.model.block_until_service_status(
            self.lead_unit,
            services,
            'running',
            model_name=self.model_name)
        zaza.model.block_until_unit_wl_status(
            self.lead_unit,
            'active',
            model_name=self.model_name)
        zaza.model.block_until_all_units_idle(model_name=self.model_name)
        zaza.model.run_action(
            self.lead_unit,
            'pause',
            model_name=self.model_name)
        zaza.model.block_until_service_status(
            self.lead_unit,
            services,
            'blocked',  # Service paused
            model_name=self.model_name)
        yield
        zaza.model.run_action(
            self.lead_unit,
            'resume',
            model_name=self.model_name)
        zaza.model.block_until_service_status(
            self.lead_unit,
            services,
            'blocked',  # Service sealed
            model_name=self.model_name)


class UnsealVault(BaseVaultTest):
    """Unseal Vault only.

    Useful for bootstrapping Vault when it is present in test bundles for other
    charms.
    """

    @classmethod
    def setUpClass(cls):
        """Run setup for UnsealVault class."""
        super(UnsealVault, cls).setUpClass()

    def test_unseal(self, test_config=None):
        """Unseal Vault.

        :param test_config: (Optional) Zaza test config
        :type test_config: charm_lifecycle.utils.get_charm_config()
        """
        vault_utils.run_charm_authorize(self.vault_creds['root_token'])
        if not test_config:
            test_config = lifecycle_utils.get_charm_config()
        try:
            del test_config['target_deploy_status']['vault']
        except KeyError:
            # Already removed
            pass
        zaza.model.wait_for_application_states(
            states=test_config.get('target_deploy_status', {}))


class VaultTest(BaseVaultTest):
    """Encapsulate vault tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Vault tests."""
        super(VaultTest, cls).setUpClass()

    def test_csr(self):
        """Test generating a csr and uploading a signed certificate."""
        vault_actions = zaza.model.get_actions(
            'vault')
        if 'get-csr' not in vault_actions:
            raise unittest.SkipTest('Action not defined')
        try:
            zaza.model.get_application(
                'keystone')
        except KeyError:
            raise unittest.SkipTest('No client to test csr')
        action = vault_utils.run_charm_authorize(
            self.vault_creds['root_token'])
        action = vault_utils.run_get_csr()

        intermediate_csr = action.data['results']['output']
        (cakey, cacert) = zaza.openstack.utilities.cert.generate_cert(
            'DivineAuthority',
            generate_ca=True)
        intermediate_cert = zaza.openstack.utilities.cert.sign_csr(
            intermediate_csr,
            cakey.decode(),
            cacert.decode(),
            generate_ca=True)
        action = vault_utils.run_upload_signed_csr(
            pem=intermediate_cert,
            root_ca=cacert,
            allowed_domains='openstack.local')

        test_config = lifecycle_utils.get_charm_config()
        try:
            del test_config['target_deploy_status']['vault']
        except KeyError:
            # Already removed
            pass
        zaza.model.wait_for_application_states(
            states=test_config.get('target_deploy_status', {}))

        vault_utils.validate_ca(cacert)

    def test_all_clients_authenticated(self):
        """Check all vault clients are authenticated."""
        for client in self.clients:
            self.assertTrue(retry_hvac_client_authenticated(client))

    def check_read(self, key, value):
        """Check reading the key from all vault units."""
        for client in self.clients:
            self.assertEqual(
                client.hvac_client.read('secret/uuids')['data']['uuid'],
                value)

    def test_consistent_read_write(self):
        """Test reading and writing data to vault."""
        key = 'secret/uuids'
        for client in self.clients:
            value = str(uuid.uuid1())
            client.hvac_client.write(key, uuid=value, lease='1h')
            # Now check all clients read the same value back
            self.check_read(key, value)

    @test_utils.skipIfNotHA('vault')
    def test_vault_ha_statuses(self):
        """Check Vault charm HA status."""
        leader = []
        leader_address = []
        leader_cluster_address = []
        for client in self.clients:
            self.assertTrue(client.hvac_client.ha_status['ha_enabled'])
            leader_address.append(
                client.hvac_client.ha_status['leader_address'])
            leader_cluster_address.append(
                client.hvac_client.ha_status['leader_cluster_address'])
            if (client.hvac_client.ha_status['is_self'] and not
                    client.vip_client):
                leader.append(client.addr)
        # Check there is exactly one leader
        self.assertEqual(len(leader), 1)
        # Check both cluster addresses match accross the cluster
        self.assertEqual(len(set(leader_address)), 1)
        self.assertEqual(len(set(leader_cluster_address)), 1)

    def test_check_vault_status(self):
        """Check Vault charm status."""
        for client in self.clients:
            self.assertFalse(client.hvac_client.seal_status['sealed'])
            self.assertTrue(client.hvac_client.seal_status['cluster_name'])

    def test_vault_authorize_charm_action(self):
        """Test the authorize_charm action."""
        vault_actions = zaza.model.get_actions(
            'vault')
        if 'authorize-charm' not in vault_actions:
            raise unittest.SkipTest('Action not defined')
        action = vault_utils.run_charm_authorize(
            self.vault_creds['root_token'])
        self.assertEqual(action.status, 'completed')
        client = self.clients[0]
        self.assertIn(
            'local-charm-policy',
            client.hvac_client.list_policies())

    def test_zzz_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped, then resume and check
        they are started.
        """
        vault_actions = zaza.model.get_actions(
            'vault')
        if 'pause' not in vault_actions or 'resume' not in vault_actions:
            raise unittest.SkipTest("The version of charm-vault tested does "
                                    "not have pause/resume actions")
        # this pauses and resumes the LEAD unit
        with self.pause_resume(['vault']):
            logging.info("Testing pause resume")
        lead_client = vault_utils.extract_lead_unit_client(self.clients)
        self.assertTrue(lead_client.hvac_client.seal_status['sealed'])

    def test_vault_reload(self):
        """Run reload tests.

        Reload service and check services were restarted
        by doing simple change in the running config by API.
        Then confirm that service is not sealed
        """
        vault_actions = zaza.model.get_actions(
            'vault')
        if 'reload' not in vault_actions:
            raise unittest.SkipTest("The version of charm-vault tested does "
                                    "not have reload action")

        container_results = zaza.model.run_on_leader(
            "vault", "systemd-detect-virt --container"
        )
        container_rc = json.loads(container_results["Code"])
        if container_rc == 0:
            raise unittest.SkipTest(
                "Vault unit is running in a container. Cannot use mlock."
            )

        lead_client = vault_utils.get_cluster_leader(self.clients)
        running_config = vault_utils.get_running_config(lead_client)
        value_to_set = not running_config['data']['disable_mlock']

        logging.info("Setting disable-mlock to {}".format(str(value_to_set)))
        zaza.model.set_application_config(
            'vault',
            {'disable-mlock': str(value_to_set)})

        logging.info("Waiting for model to be idle ...")
        zaza.model.block_until_all_units_idle(model_name=self.model_name)

        # Reload all vault units to ensure the new value is loaded.
        # Note that charm-vault since 4fccd710 will auto-reload
        # vault on config change, so this will be unecessary.
        for unit in zaza.model.get_units(
            application_name="vault",
            model_name=self.model_name
        ):
            zaza.model.run_action(
                unit.name, 'reload',
                model_name=self.model_name)

        logging.info("Getting new value ...")
        new_value = vault_utils.get_running_config(lead_client)[
            'data']['disable_mlock']

        logging.info(
            "Asserting new value {} is equal to set value {}"
            .format(new_value, value_to_set))
        self.assertEqual(
            value_to_set,
            new_value)

        logging.info("Asserting not sealed")
        self.assertFalse(lead_client.hvac_client.seal_status['sealed'])

    def test_vault_restart(self):
        """Run pause and resume tests.

        Restart service and check services are started.
        """
        vault_actions = zaza.model.get_actions(
            'vault')
        if 'restart' not in vault_actions:
            raise unittest.SkipTest("The version of charm-vault tested does "
                                    "not have restart action")
        logging.info("Testing restart")
        zaza.model.run_action_on_leader(
            'vault',
            'restart',
            action_params={})

        lead_client = vault_utils.extract_lead_unit_client(self.clients)
        self.assertTrue(lead_client.hvac_client.seal_status['sealed'])


class VaultCacheTest(BaseVaultTest):
    """Encapsulate vault tests."""

    @test_utils.skipIfNotHA('vault')
    def test_vault_caching_unified_view(self):
        """Verify that the vault applicate presents consisent certificates.

        On all of the relations to the clients.
        """
        try:
            application = zaza.model.get_application('keystone')
        except KeyError:
            self.skipTest("Application 'keystone' not available so skipping.")
        # data keys that are 'strs'
        key_str_values = ['ca', 'chain', 'client.cert', 'client.key']
        for unit in application.units:
            command = ['juju', 'show-unit', '--format=json', unit.entity_id]
            output = subprocess.check_output(command).decode()
            unit_info = json.loads(output)
            # verify that unit_info{unit.entity_id}{'relation-info'}[n],
            # where List item [n] is a {} where,
            # [n]{'endpoint'} == 'certificates' AND
            # [n]{'related_units'}{*}{'data'}{...} all match.
            #
            # first collect the list items that are 'certificates' endpoint.
            relation_info_list = [
                item
                for item in unit_info[unit.entity_id]['relation-info']
                if item['endpoint'] == 'certificates']
            # collect the data for each of the units.
            unit_data_list = [
                {key: value['data']
                 for key, value in item['related-units'].items()}
                for item in relation_info_list]
            # for each str key, verify that it's the same string on all lists.
            for str_key in key_str_values:
                values = set((v[str_key]
                              for unit_data in unit_data_list
                              for v in unit_data.values()))
                self.assertEqual(len(values), 1,
                                 "Not all {} items in data match: {}"
                                 .format(str_key, "\n".join(values)))
            # now validate that 'processed_requests' are the same.
            # they are json encoded, so need pulling out of the json; first get
            # the keys that look like "keystone_0.processed_requests".
            data_keys = set((k
                             for u in unit_data_list
                             for v in u.values()
                             for k in v.keys()))
            processed_request_keys = [
                k for k in data_keys if k.endswith(".processed_requests")]
            # now for each processed_request keys, fetch the associated databag
            # and json.loads it to get the values; they should match across the
            # relations. Using json.loads just in case the ordering of the
            # json.dumps is not determined.
            for processed_request_key in processed_request_keys:
                data_bags = [
                    (unit, json.loads(v[processed_request_key]))
                    for u in unit_data_list
                    for unit, v in u.items()]
                # data_bags: [(unit, processed_requests dict)]
                self.assertGreater(
                    len(data_bags), 1,
                    "Key {} is only in one bag".format(processed_request_key))
                first_bag = data_bags[0]
                for data_bag in data_bags[1:]:
                    self.assertEqual(
                        first_bag[1], data_bag[1],
                        "key {}: bag for: {} doesn't match bag for: {}"
                        .format(
                            processed_request_key, first_bag[0], data_bag[0]))


class VaultIntermediateCATest(BaseVaultTest):
    """Encapsulate vault tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for Vault tests."""
        super(VaultIntermediateCATest, cls).setUpClass()

    def test_generate_intermediate_ca(self):
        """Test generating an intermediate CA certificate."""
        action = vault_utils.run_charm_authorize(self.vault_creds['root_token'])
        action = zaza.model.run_action_on_leader(
            'vault', 'generate-root-ca', action_params={})

        action = zaza.model.run_action_on_leader(
            'vault',
            'generate-certificate',
            action_params={
                'common-name': 'test',
                'cert-type': 'intermediate',
                'sans': 'test,1.1.1.1',
            }
        )

        # NOTE(neoaggelos): action.data['results']['output'] format is a python dict
        # formatted as a string, so we cannot parse JSON. Instead, ensure that expected
        # keys are present.
        #
        # Example: "{'private_key': '...', 'ca_chain': '...', 'certificate': '...'}"
        assert "certificate" in action.data['results']['output']
        assert "ca_chain" in action.data['results']['output']
        assert "private_key" in action.data['results']['output']


if __name__ == '__main__':
    unittest.main()
