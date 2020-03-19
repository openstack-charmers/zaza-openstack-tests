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

"""Keystone Kerberos Testing"""

import logging
from lxml import etree
import requests

import zaza.model
from zaza.openstack.charm_tests.keystone import BaseKeystoneTest
import zaza.charm_lifecycle.utils as lifecycle_utils

class FailedToReachKerberos(Exception):
    """Custom Exception for failing to reach the Kerberos Server."""

    pass

class CharmKeystoneKerberosTest(BaseKeystoneTest):
    """Charm Keystone Kerberos Test"""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone Kerberos charm tests"""
        super(CharmKeystoneKerberosTest, cls).setUpClass()
        # Note: The BaseKeystoneTest class sets the application_name to
        # "keystone" which breaks subordinate charm actions. Explicitly set
        # application name here.
        cls.test_config = lifecycle_utils.get_charm_config()
        cls.application_name = cls.test_config['charm_name']

    def test_get_keystone_session(self):
        self.patch_object(openstack_utils, "session")
        self.patch_object(openstack_utils, "v3")
        _auth = mock.MagicMock()
        self.v2.Password.return_value = _auth
        _openrc = {
            "OS_AUTH_URL": "https://{}:5000/krb/v3".format(keystone_hostname),
            "OS_PROJECT_ID": test_project_id,
            "OS_PROJECT_NAME": test_project_name,
            "OS_PROJECT_DOMAIN_ID": test_domain_id,
            "OS_REGION_NAME": "RegionOne",
            "OS_INTERFACE": "public",
            "OS_IDENTITY_API_VERSION": 3,
            "OS_AUTH_TYPE": "v3kerberos",
        }
        openstack_utils.get_keystone_session(_openrc)
        self.session.Session.assert_called_once_with(auth=_auth, verify=None)
