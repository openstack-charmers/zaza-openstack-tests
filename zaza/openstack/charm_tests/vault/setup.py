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

"""Run configuration phase."""

import functools
import requests
import tempfile

import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.openstack.charm_tests.vault.utils as vault_utils
import zaza.model
import zaza.openstack.utilities.cert
import zaza.openstack.utilities.openstack
import zaza.openstack.utilities.generic


def basic_setup(cacert=None, unseal_and_authorize=False):
    """Run basic setup for vault tests.

    :param cacert: Path to CA cert used for vaults api cert.
    :type cacert: str
    :param unseal_and_authorize: Whether to unseal and authorize vault.
    :type unseal_and_authorize: bool
    """
    vault_svc = vault_utils.VaultFacade(cacert=cacert)
    if unseal_and_authorize:
        vault_svc.unseal()
        vault_svc.authorize()


def basic_setup_and_unseal(cacert=None):
    """Initialize (if needed) and unseal vault.

    :param cacert: Path to CA cert used for vaults api cert.
    :type cacert: str
    """
    vault_svc = vault_utils.VaultFacade(cacert=cacert)
    vault_svc.unseal()
    for unit in zaza.model.get_units('vault'):
        zaza.model.run_on_unit(unit.name, './hooks/update-status')


def mojo_unseal_by_unit():
    """Unseal any units reported as sealed using mojo cacert."""
    cacert = zaza.openstack.utilities.generic.get_mojo_cacert()
    vault_creds = vault_utils.get_credentails()
    for client in vault_utils.get_clients(cacert=cacert):
        if client.hvac_client.is_sealed():
            client.hvac_client.unseal(vault_creds['keys'][0])
            unit_name = zaza.utilities.juju.get_unit_name_from_ip_address(
                client.addr,
                'vault')
            zaza.model.run_on_unit(unit_name, './hooks/update-status')


def auto_initialize(cacert=None, validation_application='keystone'):
    """Auto initialize vault for testing.

    Generate a csr and uploading a signed certificate.
    In a stack that includes and relies on certificates in vault, initialize
    vault by unsealing and creating a certificate authority.

    :param cacert: Path to CA cert used for vault's api cert.
    :type cacert: str
    :param validation_application: Name of application to be used as a
                                   client for validation.
    :type validation_application: str
    :returns: None
    :rtype: None
    """
    basic_setup(cacert=cacert, unseal_and_authorize=True)

    action = vault_utils.run_get_csr()
    intermediate_csr = action.data['results']['output']
    (cakey, cacertificate) = zaza.openstack.utilities.cert.generate_cert(
        'DivineAuthority',
        generate_ca=True)
    intermediate_cert = zaza.openstack.utilities.cert.sign_csr(
        intermediate_csr,
        cakey.decode(),
        cacertificate.decode(),
        generate_ca=True)
    action = vault_utils.run_upload_signed_csr(
        pem=intermediate_cert,
        root_ca=cacertificate,
        allowed_domains='openstack.local')

    zaza.model.wait_for_agent_status()
    test_config = lifecycle_utils.get_charm_config(fatal=False)
    zaza.model.wait_for_application_states(
        states=test_config.get('target_deploy_status', {}))

    if validation_application:
        validate_ca(cacertificate, application=validation_application)
        # Once validation has completed restart nova-compute to work around
        # bug #1826382
        cmd_map = {
            'nova-cloud-controller': ('systemctl restart '
                                      'nova-scheduler nova-conductor'),
            'nova-compute': 'systemctl restart nova-compute',
        }
        for app in ('nova-compute', 'nova-cloud-controller',):
            try:
                for unit in zaza.model.get_units(app):
                    result = zaza.model.run_on_unit(
                        unit.entity_id, cmd_map[app])
                    assert int(result['Code']) == 0, (
                        'Restart of services on {} failed'.format(
                            unit.entity_id))
            except KeyError:
                # Nothing todo if there are no app units
                pass


auto_initialize_no_validation = functools.partial(
    auto_initialize,
    validation_application=None)


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
    zaza.model.block_until_file_has_contents(
        application,
        zaza.openstack.utilities.openstack.KEYSTONE_REMOTE_CACERT,
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
        requests.get('https://{}:{}'.format(ip, str(port)), verify=fp.name)
