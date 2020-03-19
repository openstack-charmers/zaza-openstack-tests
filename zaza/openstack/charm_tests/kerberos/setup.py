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

import json
import keystoneauth1
import os
import tempfile

import zaza.charm_lifecycle.utils as charm_lifecycle_utils
import zaza.model
from zaza.openstack.utilities import (
    cert as cert_utils,
    cli as cli_utils,
    openstack as openstack_utils,
)
from zaza.openstack.charm_tests.keystone import (
    BaseKeystoneTest,
    DEMO_TENANT,
    DEMO_DOMAIN,
    DEMO_PROJECT,
    DEMO_ADMIN_USER,
    DEMO_ADMIN_USER_PASSWORD,
    DEMO_USER,
    DEMO_PASSWORD,
)

# at this point, the kerberos-test-fixture and the bundle should be deployed
# with an empty keytab file
# Steps
# - Find keystone hostname

def _get_unit_full_hostname(unit_name):
    #currently works for one unit deployed
    unit_hostname = {}
    for unit in zaza.model.get_units(unit_name):
        result = zaza.model.run_on_unit(unit.entity_id, 'hostname -f')
        hostname = result['Stdout'].rstrip()
        unit_hostname[unit] = hostname
        logging.info('hostname: "{}"'.format(hostname))
    return unit_hostname

def _get_unit_ip(unit_name):

# - adding entry to etc/hosts of keystone

def add_dns_entry_to_keystone(kerberos_hostname="kerberos.testubuntu.com"):
    """In the keystone server, add a dns entry in /etc/hosts for the kerberos
    test server.

    :param kerberos_hostname: FQDN of Kerberos server
    :type kerberos_hostname: string
    """
    kerberos_ip = zaza.model.get_app_ips("kerberos-test-fixture")[0]
    cmd = "sudo sed -i '/localhost/i\\{}\t{}' /etc/hosts"\
        .format(kerberos_ip, kerberos_hostname)
    keystone_units = zaza.model.get_units("keystone")
    for keystone_unit in keystone_units:
        zaza.model.run_on_unit(keystone_unit.entity_id, cmd)

#
# - In kerberos server, configure host, service, add host to service (and alias)
def configure_keystone_service_in_kerberos():
    # with paramiko ? need to execute the commands as root on the kerberos server
    #https: // docs.paramiko.org / en / stable / api / client.html  # paramiko.client.SSHClient.exec_command
    unit = zaza.model.get_units('kerberos-test-fixture')
    run_as_root = "sudo su -"
    zaza.model.run_on_unit(unit.name, run_as_root)

    #doit avoir eu une auth kadmin.local successful prealablement
    run_cmd_add_princ = 'sudo kadmin.local -q "addprinc -randkey HTTP/juju-6c92ea-test1-1.project.serverstack"'
    zaza.model.run_on_unit(unit.name, run_cmd_add_princ)

    run_cmd_keytab = 'sudo kadmin.local -q "ktadd -k keystone.keytab HTTP/juju-6c92ea-test1-1.project.serverstack"'
    zaza.model.run_on_unit(unit.name, run_cmd_keytab)

    run_change_perm = 'sudo chmod 777 keystone.keytab'
    zaza.model.run_on_unit(unit.name, run_change_perm)


#   and retrieve keytab
# - add resource to keystone server with juju attach-resource
def retrieve_and_attach_keytab():
    kerberos_app_name = "kerberos-test-fixture"
    kerberos_server = zaza.model.get_unit_from_name(kerberos_app_name)

    dump_file = "keystone.keytab"
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_file = "{}/{}".format(tmpdirname, dump_file)
        zaza.model.scp_from_unit(
            kerberos_server.name,
            remote_file,
            tmp_file)

        zaza.model.attach_resource('keystone-kerberos',
                                   'keystone_keytab',
                                   tmp_file)



# - in Openstack, (create domain if no keystone-ldap)
#   create project in kerberos domain (k8s), add a user to the project, role admin
def openstack_setup_kerberos():
    KERBEROS_DOMAIN = 'k8s'
    KERBEROS_PROJECT = 'k8s'
    KERBEROS_USER = 'user_kerberos'
    ROLE = 'admin'

    keystone_session = openstack_utils.get_overcloud_keystone_session()
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    domain = keystone_client.domains.create(KERBEROS_DOMAIN,
                                            description='Kerberos Domain',
                                            enabled=True)
    project = keystone_client.projects.create(KERBEROS_PROJECT,
                                              domain,
                                              description='Test project',
                                              enabled=True)
    demo_user = keystone_client.users.create(KERBEROS_USER,
                                             domain=domain,
                                             project=project,
                                             password=DEMO_PASSWORD,
                                             email='demo@demo.com',
                                             description='Demo User',
                                             enabled=True)
    admin_role = keystone_client.roles.find(name='Admin')
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


# - source and test authentication
#that will go in the test section
#   will need the extra packages installed to run that test