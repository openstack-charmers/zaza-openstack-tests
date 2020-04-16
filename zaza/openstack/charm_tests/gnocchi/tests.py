#!/usr/bin/env python3

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

"""Encapsulate Gnocchi testing."""

import logging

from gnocchiclient.v1 import client as gnocchi_client
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class GnocchiTest(test_utils.OpenStackBaseTest):
    """Encapsulate Gnocchi tests."""

    @property
    def services(self):
        """Return a list of services for the selected OpenStack release."""
        return ['haproxy', 'gnocchi-metricd', 'apache2']

    def test_200_api_connection(self):
        """Simple api calls to check service is up and responding."""
        logging.info('Instantiating gnocchi client...')
        overcloud_auth = openstack_utils.get_overcloud_auth()
        keystone = openstack_utils.get_keystone_client(overcloud_auth)
        gnocchi_ep = keystone.service_catalog.url_for(
            service_type='metric',
            interface='publicURL'
        )
        gnocchi = gnocchi_client.Client(
            session=openstack_utils.get_overcloud_keystone_session(),
            adapter_options={
                'endpoint_override': gnocchi_ep,
            }
        )

        logging.info('Checking api functionality...')
        assert(gnocchi.status.get() != [])

    def test_910_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started.
        """
        with self.pause_resume(self.services):
            logging.info("Testing pause and resume")
