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

"""Keystone Kerberos Tests."""

import logging

import zaza.model
from zaza.openstack.charm_tests.kerberos.setup import get_unit_full_hostname
from zaza.openstack.charm_tests.keystone import BaseKeystoneTest
from zaza.openstack.utilities import openstack as openstack_utils


class CharmKeystoneKerberosTest(BaseKeystoneTest):
    """Charm Keystone Kerberos Test."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone Kerberos charm tests."""
        super(CharmKeystoneKerberosTest, cls).setUpClass()

    def test_keystone_kerberos_authentication(self):
        """Validate auth to OpenStack through the kerberos method."""
        logging.info('Retrieving a kerberos token with kinit for admin user')

        ubuntu_test_host = zaza.model.get_units('ubuntu-test-host')[0]
        result = zaza.model.run_on_unit(ubuntu_test_host.name,
                                        "echo password123 | kinit admin")
        assert result['Code'] == '0', result['Stderr']

        logging.info('Changing token mod for user access')
        result = zaza.model.run_on_unit(
            ubuntu_test_host.name,
            "sudo install -m 777 /tmp/krb5cc_0 /tmp/krb5cc_1000"
        )
        assert result['Code'] == '0', result['Stderr']

        logging.info('Fetching user/project info in OpenStack')
        domain_name = 'k8s'
        project_name = 'k8s'
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        keystone_client = openstack_utils.get_keystone_session_client(
            keystone_session)
        domain_id = keystone_client.domains.find(name=domain_name).id
        project_id = keystone_client.projects.find(name=project_name).id
        keystone_hostname = get_unit_full_hostname('keystone')

        logging.info('Retrieving an OpenStack token to validate auth')
        cmd = 'openstack token issue -f value -c id ' \
              '--os-auth-url http://{}:5000/krb/v3 ' \
              '--os-project-id {} ' \
              '--os-project-name {} ' \
              '--os-project-domain-id {} ' \
              '--os-region-name RegionOne ' \
              '--os-interface public ' \
              '--os-identity-api-version 3 ' \
              '--os-auth-type v3kerberos'.format(keystone_hostname,
                                                 project_id,
                                                 project_name,
                                                 domain_id)

        result = zaza.model.run_on_unit(ubuntu_test_host.name, cmd)
        assert result['Code'] == '0', result['Stderr']
