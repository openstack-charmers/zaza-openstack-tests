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
import mock
import subprocess

import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.openstack.utilities.exceptions as zaza_exceptions
from zaza.openstack.charm_tests.kerberos.setup import get_unit_full_hostname
from zaza.openstack.charm_tests.keystone import BaseKeystoneTest
from zaza.openstack.utilities import openstack as openstack_utils


class FailedToReachKerberos(Exception):
    """Custom Exception for failing to reach the Kerberos Server."""

    pass


class CharmKeystoneKerberosTest(BaseKeystoneTest):
    """Charm Keystone Kerberos Test."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone Kerberos charm tests."""
        super(CharmKeystoneKerberosTest, cls).setUpClass()
        # Note: The BaseKeystoneTest class sets the application_name to
        # "keystone" which breaks subordinate charm actions. Explicitly set
        # application name here.
        cls.test_config = lifecycle_utils.get_charm_config()
        cls.application_name = cls.test_config['charm_name']


    def test_100_keystone_kerberos_authentication_keytab(self):
        """Validate authentication to the kerberos principal server with keytab."""
        logging.info('Retrieving a kerberos token with kinit')
        host_keytab_path = '/home/ubuntu/krb5.keytab'
        cmd = ['kinit', '-kt', host_keytab_path ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True)
        assert result.returncode == 0, result.stderr


    def test_get_keystone_session(self):
        """Run test to retrieve a keystone session."""
        self.patch_object(openstack_utils, "session")
        self.patch_object(openstack_utils, "v3")
        _auth = mock.MagicMock()
        self.v3.Password.return_value = _auth

        domain_name = 'k8s'
        project_name = 'k8s'
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        keystone_client = openstack_utils.get_keystone_session_client(
            keystone_session)
        domain_id = keystone_client.domain.find(name=domain_name).id
        project_id = keystone_client.project.find(name=project_name).id
        keystone_hostname = get_unit_full_hostname('keystone')

        _openrc = {
            "OS_AUTH_URL": "https://{}:5000/krb/v3".format(keystone_hostname),
            "OS_PROJECT_ID": project_id,
            "OS_PROJECT_NAME": project_name,
            "OS_PROJECT_DOMAIN_ID": domain_id,
            "OS_REGION_NAME": "RegionOne",
            "OS_INTERFACE": "public",
            "OS_IDENTITY_API_VERSION": 3,
            "OS_AUTH_TYPE": "v3kerberos",
        }
        user_session = openstack_utils.get_keystone_session(_openrc)
        self.session.Session.assert_called_once_with(auth=_auth, verify=None)
        user_client = openstack_utils.get_keystone_session_client(user_session)
        token =user_session.get_token()
        if len(token) < 180:
            raise zaza_exceptions.KeystoneWrongTokenProvider(
                'We expected a Fernet token and got this: "{}"'
                    .format(token))

        logging.info('token: "{}"'.format(pprint.pformat(token)))


