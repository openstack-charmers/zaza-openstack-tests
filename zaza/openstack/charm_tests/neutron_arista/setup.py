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

"""Code for setting up neutron-api-plugin-arista."""

import logging
import tenacity
import zaza
import zaza.openstack.charm_tests.neutron_arista.utils as arista_utils


def test_fixture():
    """Pass arista-virt-test-fixture's IP address to Neutron."""
    fixture_ip_addr = arista_utils.fixture_ip_addr()
    logging.info(
        "{}'s IP address is '{}'. Passing it to neutron-api-plugin-arista..."
        .format(arista_utils.FIXTURE_APP_NAME, fixture_ip_addr))
    zaza.model.set_application_config('neutron-api-plugin-arista',
                                      {'eapi-host': fixture_ip_addr})

    logging.info('Waiting for {} to become ready...'.format(
        arista_utils.FIXTURE_APP_NAME))
    for attempt in tenacity.Retrying(
            wait=tenacity.wait_fixed(10),  # seconds
            stop=tenacity.stop_after_attempt(30),
            reraise=True):
        with attempt:
            arista_utils.query_fixture_networks(fixture_ip_addr)
