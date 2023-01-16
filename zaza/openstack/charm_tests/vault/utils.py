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

"""Module of functions for interfacing with vault and the vault charm."""

import base64
import hvac
import logging
import requests
import tempfile
import time
import urllib3
import yaml
import tenacity

import collections

import zaza.model
import zaza.openstack.utilities.openstack
import zaza.utilities.networking as network_utils

AUTH_FILE = "vault_tests.yaml"
CharmVaultClient = collections.namedtuple(
    'CharmVaultClient', ['addr', 'hvac_client', 'vip_client'])


class VaultFacade:
    """Provide a facade for interacting with vault.

    For example to setup new vault deployment::

        vault_svc = VaultFacade()
        vault_svc.unseal()
        vault_svc.authorize()
    """

    def __init__(self, cacert=None, initialize=True):
        """Create a facade for interacting with vault.

        :param cacert: Path to CA cert used for vaults api cert.
        :type cacert: str
        :param initialize: Whether to initialize vault.
        :type initialize: bool
        """
        self.clients = get_clients(cacert=cacert)
        self.vip_client = get_vip_client(cacert=cacert)
        if self.vip_client:
            self.unseal_client = self.vip_client
        else:
            self.unseal_client = self.clients[0]
        if initialize:
            self.initialize()

    @property
    def is_initialized(self):
        """Check if vault is initialized."""
        return is_initialized(self.unseal_client)

    def initialize(self):
        """Initialise vault and store resulting credentials."""
        if self.is_initialized:
            self.vault_creds = get_credentials()
        else:
            self.vault_creds = init_vault(self.unseal_client)
            store_credentials(self.vault_creds)
            self.unseal_client = wait_and_get_initialized_client(self.clients)

    def unseal(self):
        """Unseal all the vaults clients."""
        unseal_all([self.unseal_client], self.vault_creds['keys'][0])
        wait_until_all_initialised(self.clients)
        unseal_all(self.clients, self.vault_creds['keys'][0])
        wait_for_ha_settled(self.clients)

    def authorize(self):
        """Authorize charm to perfom certain actions.

        Run vault charm action to authorize the charm to perform a limited
        set of calls against the vault API.
        """
        auth_all(self.clients, self.vault_creds['root_token'])
        wait_for_ha_settled(self.clients)
        run_charm_authorize(self.vault_creds['root_token'])


def get_unit_api_url(ip):
    """Return URL for api access.

    :param unit_ip: IP address to use in vault url
    :type unit_ip: str
    :returns: URL
    :rtype: atr
    """
    vault_config = zaza.model.get_application_config('vault')
    transport = 'http'
    if vault_config['ssl-cert']['value']:
        transport = 'https'
    return '{}://{}:8200'.format(transport, network_utils.format_addr(ip))


def get_hvac_client(vault_url, cacert=None):
    """Return an hvac client for the given URL.

    :param vault_url: Vault url to point client at
    :type vault_url: str
    :param cacert: Path to CA cert used for vaults api cert.
    :type cacert: str
    :returns: hvac client for given url
    :rtype: hvac.Client
    """
    return hvac.Client(url=vault_url, verify=cacert)


def get_vip_client(cacert=None):
    """Return CharmVaultClient for the vip if a vip is being used.

    :param cacert: Path to CA cert used for vaults api cert.
    :type cacert: str
    :returns: CharmVaultClient
    :rtype: CharmVaultClient or None
    """
    client = None
    vault_config = zaza.model.get_application_config('vault')
    vip = vault_config.get('vip', {}).get('value')
    if vip:
        client = CharmVaultClient(
            vip,
            get_hvac_client(get_unit_api_url(vip), cacert=cacert),
            True)
    return client


def get_cluster_leader(clients):
    """Get Vault cluster leader.

    We have to make sure we run api calls against the actual leader.

    :param clients: Clients list to get leader
    :type clients: List of CharmVaultClient
    :returns: CharmVaultClient
    :rtype: CharmVaultClient or None
    """
    if len(clients) == 1:
        return clients[0]

    for client in clients:
        if client.hvac_client.ha_status['is_self']:
            return client
    return None


def get_running_config(client):
    """Get Vault running config.

    The hvac library does not support getting info from endpoint
    /v1/sys/config/state/sanitized Therefore we implement it here

    :param client: Client used to get config
    :type client: CharmVaultClient
    :returns: dict from Vault api response
    :rtype: dict
    """
    return requests.get(
        client.hvac_client.adapter.base_uri + '/v1/sys/config/state/sanitized',
        headers={'X-Vault-Token': client.hvac_client.token}).json()


def init_vault(client, shares=1, threshold=1):
    """Initialise vault.

    :param client: Client to use for initiliasation
    :type client: CharmVaultClient
    :param shares: Number of key shares to create
    :type shares: int
    :param threshold: Number of keys needed to unseal vault
    :type threshold: int
    :returns: Token and key(s) for accessing vault
    :rtype: dict
    """
    return client.hvac_client.initialize(shares, threshold)


def get_clients(units=None, cacert=None):
    """Create a list of clients, one per vault server.

    :param units: List of IP addresses of vault endpoints
    :type units: [str, str, ...]
    :param cacert: Path to CA cert used for vaults api cert.
    :type cacert: str
    :returns: List of CharmVaultClients
    :rtype: [CharmVaultClient, ...]
    """
    if not units:
        units = zaza.model.get_app_ips('vault')
    clients = []
    for unit in units:
        vault_url = get_unit_api_url(unit)
        clients.append(CharmVaultClient(
            unit,
            get_hvac_client(vault_url, cacert=cacert),
            False))
    return clients


def extract_lead_unit_client(
        clients=None, application_name='vault', cacert=None):
    """Find the lead unit client.

    This returns the lead unit client from a list of clients.  If no clients
    are passed, then the clients are resolved using the cacert (if needed) and
    the application_name.  The client is then matched to the lead unit.  If
    clients are passed, but no leader is found in them, then the function
    raises a RuntimeError.

    :param clients: List of CharmVaultClient
    :type clients: List[CharmVaultClient]
    :param application_name: The application name
    :type application_name: str
    :param cacert: Path to CA cert used for vaults api cert.
    :type cacert: str
    :returns: The leader client
    :rtype: CharmVaultClient
    :raises: RuntimeError if the lead unit cannot be found
    """
    if clients is None:
        units = zaza.model.get_app_ips('vault')
        clients = get_clients(units, cacert)
    lead_ip = zaza.model.get_lead_unit_ip(application_name)
    for client in clients:
        if client.addr == lead_ip:
            return client
    raise RuntimeError("Leader client not found for application: {}"
                       .format(application_name))


@tenacity.retry(
    retry=tenacity.retry_if_exception_type((
        ConnectionRefusedError,
        urllib3.exceptions.NewConnectionError,
        urllib3.exceptions.MaxRetryError,
        requests.exceptions.ConnectionError)),
    reraise=True,  # if all retries failed, reraise the last exception
    wait=tenacity.wait_fixed(2),  # interval between retries
    stop=tenacity.stop_after_attempt(10))  # retry 10 times
def is_initialized(client):
    """Check if vault is initialized.

    :param client: Client to use to check if vault is initialized
    :type client: CharmVaultClient
    :returns: Whether vault is initialized
    :rtype: bool

    Raise the last exception if no value returned after retries.
    """
    return client.hvac_client.is_initialized()


def ensure_secret_backend(client):
    """Ensure that vault has a KV backend mounted at secret.

    :param client: Client to use to talk to vault
    :type client: CharmVaultClient
    """
    try:
        client.hvac_client.enable_secret_backend(
            backend_type='kv',
            description='Charm created KV backend',
            mount_point='secret',
            options={'version': 1})
    except hvac.exceptions.InvalidRequest:
        pass


def wait_for_ha_settled(clients):
    """Wait until vault ha is settled (for all passed clients).

    Raise an AssertionError if any are not settled within 2 minutes.
    This function is effectively a no-op for non-ha vault.
    Requires all vault units to be unsealed.

    :param clients: Clients to use to talk to vault
    :type clients: List[CharmVaultClient]
    :raises: AssertionError
    """
    for client in clients:
        for attempt in tenacity.Retrying(
            reraise=True,
            wait=tenacity.wait_fixed(10),
            stop=tenacity.stop_after_attempt(12),  # wait for max 2 minutes
        ):
            with attempt:
                # ha_status could also raise other errors,
                # eg. if unsealing still in progress.
                # This is why we're using tenacity here;
                # avoids needing to manually handle other exceptions.
                ha_status = client.hvac_client.ha_status
                if (
                    not ha_status.get('leader_address') and
                    ha_status.get('ha_enabled')
                ):
                    raise AssertionError('Timeout waiting for ha to settle')


def wait_until_all_initialised(clients):
    """Wait until vault is initialized (for all passed clients).

    Raise an AssertionError if any are not initialized within 2 minutes.

    :param clients: Clients to use to talk to vault
    :type clients: List[CharmVaultClient]
    :raises: AssertionError
    """
    for client in clients:
        for _ in range(12):
            if is_initialized(client):
                break
            time.sleep(10)  # max 2 minutes (12 x 10s)
        else:
            raise AssertionError("Timeout waiting for vault to initialize")


def wait_and_get_initialized_client(clients):
    """Wait until at least one vault unit is initialized.

    And return the initialized client.
    Raise an AssertionError
    if no initialized clients are found within 2 minutes.

    :param clients: Clients to use to talk to vault
    :type clients: List[CharmVaultClient]
    :raises: AssertionError
    :returns: an initialized client
    :rtype: CharmVaultClient
    """
    for _ in range(12):
        for client in clients:
            if is_initialized(client):
                return client
        time.sleep(10)  # max 2 minutes (12 x 10s)
    raise AssertionError("Timeout waiting for vault to initialize")


def find_unit_with_creds():
    """Find the unit thats has stored the credentials.

    :returns: unit name
    :rtype: str
    """
    unit = None
    for vault_unit in zaza.model.get_units('vault'):
        cmd = 'ls -l ~ubuntu/{}'.format(AUTH_FILE)
        resp = zaza.model.run_on_unit(vault_unit.name, cmd)
        if resp.get('Code') == '0':
            unit = vault_unit.name
            break
    return unit


def get_credentials():
    """Retrieve vault token and keys from unit.

    Retrieve vault token and keys from unit. These are stored on a unit
    during functional tests.

    :returns: Tokens and keys for accessing test environment
    :rtype: dict
    """
    unit = find_unit_with_creds()
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_file = '{}/{}'.format(tmpdirname, AUTH_FILE)
        zaza.model.scp_from_unit(
            unit,
            '~/{}'.format(AUTH_FILE),
            tmp_file)
        with open(tmp_file, 'r') as stream:
            creds = yaml.safe_load(stream)
    return creds


def store_credentials(creds):
    """Store the supplied credentials.

    Store the supplied credentials on a vault unit. ONLY USE FOR FUNCTIONAL
    TESTING.

    :param creds: Keys and token to store
    :type creds: dict
    """
    unit = zaza.model.get_first_unit_name('vault')
    with tempfile.NamedTemporaryFile(mode='w') as fp:
        fp.write(yaml.dump(creds))
        fp.flush()
        zaza.model.scp_to_unit(
            unit,
            fp.name,
            '~/{}'.format(AUTH_FILE))


def get_credentials_from_file(auth_file):
    """Read the vault credentials from the auth_file.

    :param auth_file: Path to file with credentials
    :type auth_file: str
    :returns: Token and keys
    :rtype: dict
    """
    with open(auth_file, 'r') as stream:
        vault_creds = yaml.safe_load(stream)
    return vault_creds


def write_credentials(auth_file, vault_creds):
    """Write the vault credentials to the auth_file.

    :param auth_file: Path to file to write credentials
    :type auth_file: str
    """
    with open(auth_file, 'w') as outfile:
        yaml.dump(vault_creds, outfile, default_flow_style=False)


def unseal_all(clients, key):
    """Unseal all the vaults with the given clients with the provided key.

    :param clients: List of clients
    :type clients: [CharmVaultClient, ...]
    :param key: key to unlock clients
    :type key: str
    """
    for client in clients:
        if client.hvac_client.is_sealed():
            client.hvac_client.unseal(key)


def auth_all(clients, token):
    """Authenticate all the given clients with the provided token.

    :param clients: List of clients
    :type clients: [CharmVaultClient, ...]
    :param token: Token to authorize clients
    :type token: str
    """
    for client in clients:
        client.hvac_client.token = token


def run_charm_authorize(token):
    """Authorize charm to perfom certain actions.

    Run vault charm action to authorize the charm to perform a limited
    set of calls against the vault API.

    :param token: Token to authorize action against vault.
    :type token: str
    :returns: Action object
    :rtype: juju.action.Action
    """
    return zaza.model.run_action_on_leader(
        'vault',
        'authorize-charm',
        action_params={'token': token})


def run_get_csr():
    """Retrieve CSR from vault.

    Run vault charm action to retrieve CSR from vault.

    :returns: Action object
    :rtype: juju.action.Action
    """
    return zaza.model.run_action_on_leader(
        'vault',
        'get-csr',
        action_params={})


def run_upload_signed_csr(pem, root_ca, allowed_domains):
    """Upload signed cert to vault.

    :param pem: Signed certificate text
    :type pem: str
    :param token: Root CA text.
    :type token: str
    :param allowed_domains: List of domains that may have certs issued from
                            certificate.
    :type allowed_domains: list
    :returns: Action object
    :rtype: juju.action.Action
    """
    return zaza.model.run_action_on_leader(
        'vault',
        'upload-signed-csr',
        action_params={
            'pem': base64.b64encode(pem).decode(),
            'root-ca': base64.b64encode(root_ca).decode(),
            'allowed-domains=': allowed_domains,
            'ttl': '24h'})


@tenacity.retry(
    reraise=True,
    wait=tenacity.wait_exponential(multiplier=2, min=2, max=10),
    stop=tenacity.stop_after_attempt(3))
def validate_ca(cacertificate, application="keystone", port=5000):
    """Validate Certificate Authority against application.

    :param cacertificate: PEM formatted CA certificate
    :type cacertificate: str
    :param application: Which application to validate against.
    :type application: str
    :param port: Port to validate against.
    :type port: int
    :returns: None
    :rtype: None
    """
    zaza.openstack.utilities.openstack.block_until_ca_exists(
        application,
        cacertificate.decode().strip())
    vip = (zaza.model.get_application_config(application)
           .get("vip").get("value"))
    if vip:
        ip = vip
    else:
        ip = zaza.model.get_app_ips(application)[0]
    with tempfile.NamedTemporaryFile(mode='w') as fp:
        fp.write(cacertificate.decode())
        fp.flush()
        keystone_url = 'https://{}:{}'.format(ip, str(port))
        logging.info(
            'Attempting to connect to {}'.format(keystone_url))
        requests.get(keystone_url, verify=fp.name)
