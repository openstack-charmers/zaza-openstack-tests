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

"""Setup for keystone-kerberos tests."""

import logging
import tempfile
import tenacity
from keystoneauth1.exceptions.connection import ConnectFailure

import zaza.model
from zaza.openstack.utilities import openstack as openstack_utils
from zaza.openstack.charm_tests.kerberos import KerberosConfigurationError


def get_unit_full_hostname(unit_name):
    """Retrieve the full hostname of a unit."""
    for unit in zaza.model.get_units(unit_name):
        result = zaza.model.run_on_unit(unit.entity_id, 'hostname -f')
        hostname = result['Stdout'].rstrip()
    return hostname


def add_empty_resource_file_to_keystone_kerberos():
    """Add an empty resource to keystone kerberos to complete the setup."""
    logging.info('Attaching an empty keystone keytab to the keystone-kerberos'
                 ' unit')
    tmp_file = '/tmp/empty.keytab'
    with open(tmp_file, 'w'):
        pass

    zaza.model.attach_resource('keystone-kerberos',
                               'keystone_keytab',
                               tmp_file)
    logging.info('Waiting for keystone-kerberos unit to be active and idle')
    unit_name = zaza.model.get_units('keystone-kerberos')[0].name
    zaza.model.block_until_unit_wl_status(unit_name, "active")
    zaza.model.block_until_all_units_idle()


def add_dns_entry(kerberos_hostname="kerberos.testubuntu.com"):
    """Add a dns entry in /etc/hosts for the kerberos test server.

    :param kerberos_hostname: FQDN of Kerberos server
    :type kerberos_hostname: string
    """
    logging.info('Retrieving kerberos IP and hostname')
    kerberos_ip = zaza.model.get_app_ips("kerberos-server")[0]
    cmd = "sudo sed -i '/localhost/i\\{}\t{}' /etc/hosts"\
        .format(kerberos_ip, kerberos_hostname)

    app_names = ['keystone', 'ubuntu-test-host']
    for app_name in app_names:
        logging.info('Adding dns entry to the {} unit'.format(app_name))
        zaza_unit = zaza.model.get_units(app_name)[0]
        zaza.model.run_on_unit(zaza_unit.entity_id, cmd)


def configure_keystone_service_in_kerberos():
    """Configure the keystone service in Kerberos.

    A principal needs to be added to the kerberos server to get a keytab for
    this service. The keytab is used for the authentication of the keystone
    service.
    """
    logging.info('Configure keystone service in Kerberos')
    unit = zaza.model.get_units('kerberos-server')[0]
    keystone_hostname = get_unit_full_hostname('keystone')
    commands = ['sudo kadmin.local -q "addprinc -randkey -clearpolicy '
                'HTTP/{}"'.format(keystone_hostname),
                'sudo kadmin.local -q "ktadd '
                '-k /home/ubuntu/keystone.keytab '
                'HTTP/{}"'.format(keystone_hostname),
                'sudo chmod 777 /home/ubuntu/keystone.keytab']

    try:
        for command in commands:
            logging.info(
                'Sending command to the kerberos-server: {}'.format(command))
            result = zaza.model.run_on_unit(unit.name, command)
            if result['Stderr']:
                raise KerberosConfigurationError
            elif result['Stdout']:
                logging.info('Stdout: {}'.format(result['Stdout']))
    except KerberosConfigurationError:
        logging.error('An error occured : {}'.format(result['Stderr']))


def retrieve_and_attach_keytab():
    """Retrieve and attach the keytab to the keystone-kerberos unit."""
    kerberos_server = zaza.model.get_units('kerberos-server')[0]

    dump_file = "keystone.keytab"
    remote_file = "/home/ubuntu/keystone.keytab"
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_file = "{}/{}".format(tmpdirname, dump_file)
        logging.info('Retrieving keystone.keytab from the kerberos server.')
        zaza.model.scp_from_unit(
            kerberos_server.name,
            remote_file,
            tmp_file)
        logging.info('Attaching the keystone_keytab resource to '
                     'keystone-kerberos')
        zaza.model.attach_resource('keystone-kerberos',
                                   'keystone_keytab',
                                   tmp_file)

    # cs:ubuntu charm has changed behaviour and we can't rely on the workload
    # staus message.  Thus, ignore it.
    states = {
        "ubuntu-test-host": {
            "workload-status": "active",
            "workload-status-message": "",
        }
    }
    zaza.model.wait_for_application_states(states=states)
    zaza.model.block_until_all_units_idle()


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=2, max=60),
                reraise=True, stop=tenacity.stop_after_attempt(5),
                retry=tenacity.retry_if_exception_type(ConnectFailure))
def openstack_setup_kerberos():
    """Create a test domain, project, and user for kerberos tests."""
    kerberos_domain = 'k8s'
    kerberos_project = 'k8s'
    kerberos_user = 'admin'
    kerberos_password = 'password123'
    role = 'admin'

    logging.info('Retrieving a keystone session and client.')
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    logging.info('Creating domain, project and user for Kerberos tests.')
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


def setup_kerberos_configuration_for_test_host():
    """Retrieve the keytab and krb5.conf to setup the ubuntu test host."""
    kerberos_server = zaza.model.get_units('kerberos-server')[0]
    ubuntu_test_host = zaza.model.get_units('ubuntu-test-host')[0]

    dump_file = "krb5.keytab"
    remote_file = "/etc/krb5.keytab"
    host_keytab_path = '/home/ubuntu/krb5.keytab'
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_file = "{}/{}".format(tmpdirname, dump_file)
        logging.info("Retrieving {} from {}.".format(remote_file,
                                                     kerberos_server.name))
        zaza.model.scp_from_unit(
            kerberos_server.name,
            remote_file,
            tmp_file)

        logging.info("SCP {} to {} on {}.".format(tmp_file,
                                                  host_keytab_path,
                                                  ubuntu_test_host.name))
        zaza.model.scp_to_unit(
            ubuntu_test_host.name,
            tmp_file,
            host_keytab_path)

    dump_file = "krb5.conf"
    remote_file = "/etc/krb5.conf"
    temp_krb5_path = "/home/ubuntu/krb5.conf"
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_file = "{}/{}".format(tmpdirname, dump_file)
        logging.info("Retrieving {} from {}".format(remote_file,
                                                    kerberos_server.name))
        zaza.model.scp_from_unit(
            kerberos_server.name,
            remote_file,
            tmp_file)

        logging.info("SCP {} to {} on {}.".format(tmp_file,
                                                  temp_krb5_path,
                                                  ubuntu_test_host))
        zaza.model.scp_to_unit(
            ubuntu_test_host.name,
            tmp_file,
            temp_krb5_path)
        logging.info('Moving {} to {} on {}.'.format(temp_krb5_path,
                     remote_file, ubuntu_test_host.name))
        zaza.model.run_on_unit(ubuntu_test_host.name, ('sudo mv {} {}'.
                               format(temp_krb5_path, remote_file)))


def install_apt_packages_on_ubuntu_test_host():
    """Install apt packages on a zaza unit."""
    ubuntu_test_host = zaza.model.get_units('ubuntu-test-host')[0]
    packages = ['krb5-user', 'python3-openstackclient',
                'python3-requests-kerberos']
    for package in packages:
        logging.info('Installing {}'.format(package))
        result = zaza.model.run_on_unit(ubuntu_test_host.name,
                                        "apt install {} -y".format(package))
        assert result['Code'] == '0', result['Stderr']


def run_all_configuration_steps():
    """Execute all the necessary functions for the tests setup."""
    add_empty_resource_file_to_keystone_kerberos()
    add_dns_entry()
    configure_keystone_service_in_kerberos()
    retrieve_and_attach_keytab()
    openstack_setup_kerberos()
    setup_kerberos_configuration_for_test_host()
    install_apt_packages_on_ubuntu_test_host()
