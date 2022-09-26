#!/usr/bin/env python3

# Copyright 2019 Canonical Ltd.
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

"""Encapsulate Cloudkitty testing."""

import logging

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils

from cloudkittyclient import client


class CloudkittyTest(test_utils.OpenStackBaseTest):
    """Encapsulate Cloudkitty tests."""

    CONF_FILE = '/etc/cloudkitty/cloudkitty.conf'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Cloudkitty tests."""
        super(CloudkittyTest, cls).setUpClass()
        cls.current_release = openstack_utils.get_os_release()

    def test_400_api_connection(self):
        """Simple api calls to check service is up and responding."""
        logging.info('Instantiating cloudkitty client...')
        client_version = '1'
        cloudkitty = client.Client(
            client_version,
            session=openstack_utils.get_overcloud_keystone_session()
        )
        cloudkitty.report.get_summary()
        pass
