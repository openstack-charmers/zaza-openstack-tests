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
import os
import tenacity
import zaza
import zaza.openstack.charm_tests.neutron_arista.utils as arista_utils
import zaza.openstack.utilities.openstack as openstack_utils


def download_arista_image():
    """Download arista-cvx-virt-test.qcow2 from a web server.

    If TEST_ARISTA_IMAGE_LOCAL isn't set, set it to
    `/tmp/arista-cvx-virt-test.qcow2`. If TEST_ARISTA_IMAGE_REMOTE is set (e.g.
    to `http://example.com/swift/v1/images/arista-cvx-virt-test.qcow2`),
    download it to TEST_ARISTA_IMAGE_LOCAL.
    """
    try:
        os.environ['TEST_ARISTA_IMAGE_LOCAL']
    except KeyError:
        os.environ['TEST_ARISTA_IMAGE_LOCAL'] = ''
    if not os.environ['TEST_ARISTA_IMAGE_LOCAL']:
        os.environ['TEST_ARISTA_IMAGE_LOCAL'] \
            = '/tmp/arista-cvx-virt-test.qcow2'

    try:
        if os.environ['TEST_ARISTA_IMAGE_REMOTE']:
            logging.info('Downloading Arista image from {}'
                         .format(os.environ['TEST_ARISTA_IMAGE_REMOTE']))
            openstack_utils.download_image(
                os.environ['TEST_ARISTA_IMAGE_REMOTE'],
                os.environ['TEST_ARISTA_IMAGE_LOCAL'])
    except KeyError:
        pass

    logging.info('Arista image can be found at {}'
                 .format(os.environ['TEST_ARISTA_IMAGE_LOCAL']))


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
