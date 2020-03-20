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

"""Setup for keystone-kerberos tests."""

import logging
import tempfile
import zaza.model
from zaza.openstack.utilities import openstack as openstack_utils

# at this point, the kerberos-test-fixture and the bundle should be deployed
# with an empty keytab file
# Steps
# - Find keystone hostname


class KerberosConfigurationError(Exception):
    """Custom exception for Kerberos test server."""

    pass


def _get_unit_full_hostname(unit_name):
    """Retrieve the full hostname of a unit."""
    for unit in zaza.model.get_units(unit_name):
        result = zaza.model.run_on_unit(unit.entity_id, 'hostname -f')
        hostname = result['Stdout'].rstrip()
        logging.info('{} full hostname: "{}"'.format(unit_name, hostname))
    return hostname


def add_empty_resource_file_to_keystone_kerberos():
    """Add an empty resource to keystone kerberos to complete the setup."""
    logging.info('Attaching an empty keystone keytab to the keystone-kerberos'
                 ' unit')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.keytab') as tmp_file:
        tmp_file.write('')
        tmp_file.flush()
        zaza.model.attach_resource('keystone-kerberos',
                                   'keystone_keytab',
                                   tmp_file)
    zaza.model.block_until_all_units_idle()


def add_dns_entry_to_keystone(kerberos_hostname="kerberos.testubuntu.com"):
    """In keystone, add a dns entry in /etc/hosts for the kerberos test server.

    :param kerberos_hostname: FQDN of Kerberos server
    :type kerberos_hostname: string
    """
    logging.info('Retrieving kerberos IP and hostname')
    kerberos_ip = zaza.model.get_app_ips("kerberos-server")[0]
    cmd = "sudo sed -i '/localhost/i\\{}\t{}' /etc/hosts"\
        .format(kerberos_ip, kerberos_hostname)
    keystone_units = zaza.model.get_units("keystone")
    for keystone_unit in keystone_units:
        zaza.model.run_on_unit(keystone_unit.entity_id, cmd)
        logging.info('DNS entry added to unit {}: {} {}'
                     .format(keystone_unit.name,
                             kerberos_ip,
                             kerberos_hostname))


def configure_keystone_service_in_kerberos():
    """Configure the keystone service in Kerberos.

    A principal needs to be added to the kerberos server to get a keytab for
    this service. The keytab is used for the authentication of the keystone
    service.
    """
    logging.info('Configure keystone service in Kerberos')
    unit = zaza.model.get_units('kerberos-server')[0]
    keystone_hostname = _get_unit_full_hostname('keystone')
    commands = ['sudo su -',
                'sudo kadmin.local -q "addprinc -randkey '
                'HTTP/{}"'.format(keystone_hostname),
                'sudo kadmin.local -q "ktadd '
                '-k /home/ubuntu/keystone.keytab '
                'HTTP/{}"'.format(keystone_hostname),
                'sudo chmod 777 /home/ubuntu/keystone.keytab']

    try:
        for command in commands:
            logging.info(
                'Command to send to kerberos-server: {}'.format(command))
            result = zaza.model.run_on_unit(unit.name, command)
            logging.info('Stdout: {}'.format(result['Stdout']))
            if result['Stderr']:
                raise KerberosConfigurationError

    except KerberosConfigurationError:
        logging.error('Stdout: {}'.format(result['Stderr']))


#   and retrieve keytab
# - add resource to keystone server with juju attach-resource
def retrieve_and_attach_keytab():
    """Retrieve and attach the keytab to the keystone-kerberos unit."""
    kerberos_server = zaza.model.get_units('kerberos-server')[0]

    dump_file = "keystone.keytab"
    remote_file = "/home/ubuntu/keystone.keytab"
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_file = "{}/{}".format(tmpdirname, dump_file)
        zaza.model.scp_from_unit(
            kerberos_server.name,
            remote_file,
            tmp_file)

        zaza.model.attach_resource('keystone-kerberos',
                                   'keystone_keytab',
                                   tmp_file)


def openstack_setup_kerberos():
    """Create a test domain, project, and user for kerberos tests."""
    kerberos_domain = 'k8s'
    kerberos_project = 'k8s'
    kerberos_user = 'user_kerberos'
    kerberos_password = 'password123'
    role = 'admin'

    keystone_session = openstack_utils.get_overcloud_keystone_session()
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    domain = keystone_client.domains.create(kerberos_domain,
                                            description='Kerberos Domain',
                                            enabled=True)
    project = keystone_client.projects.create(kerberos_project,
                                              domain,
                                              description='Test project',
                                              enabled=True)
    demo_user = keystone_client.users.create(kerberos_user,
                                             domain=domain,
                                             project=project,
                                             password=kerberos_password,
                                             email='demo@demo.com',
                                             description='Demo User',
                                             enabled=True)
    admin_role = keystone_client.roles.find(name=role)
    keystone_client.roles.grant(
        admin_role,
        user=demo_user,
        project_domain=domain,
        project=project
    )
    keystone_client.roles.grant(
        admin_role,
        user=demo_user,
        domain=domain
    )


def retrieve_token_and_conf_for_test_host():
    """Retrieve the admin keytab and krb5.conf to setup the test host."""
    kerberos_server = zaza.model.get_units('kerberos-server')[0]

    dump_file = "keystone.keytab"
    remote_file = "/etc/krb5.conf"
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_file = "{}/{}".format(tmpdirname, dump_file)
        zaza.model.scp_from_unit(
            kerberos_server.name,
            remote_file,
            tmp_file)

        zaza.model.attach_resource('keystone-kerberos',
                                   'keystone_keytab',
                                   tmp_file)

# source and test authentication
# that will go in the test section
# will need the extra packages installed to run that test
