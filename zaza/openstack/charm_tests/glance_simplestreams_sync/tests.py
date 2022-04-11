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

"""Encapsulate glance-simplestreams-sync testing."""
import json
import logging
import requests
import tenacity

import zaza.model as zaza_model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


@tenacity.retry(
    retry=tenacity.retry_if_result(lambda images: len(images) < 4),
    wait=tenacity.wait_fixed(6),  # interval between retries
    stop=tenacity.stop_after_attempt(100))  # retry times
def retry_image_sync(glance_client):
    """Wait for image sync with retry."""
    # convert generator to list
    return list(glance_client.images.list())


@tenacity.retry(
    retry=tenacity.retry_if_exception_type(json.decoder.JSONDecodeError),
    wait=tenacity.wait_fixed(10), reraise=True,
    stop=tenacity.stop_after_attempt(10))
def get_product_streams(url):
    """Get product streams json data with retry."""
    # There is a race between the images being available in glance and any
    # metadata being written. Use tenacity to avoid this race.
    client = requests.session()
    json_data = client.get(url, verify=openstack_utils.get_cacert()).text
    try:
        return json.loads(json_data)
    except Exception as e:
        logging.error("Couldn't decode json, reason: %s, response text to "
                      "decode:\n%s", str(e), json_data)
        raise


class GlanceSimpleStreamsSyncTest(test_utils.OpenStackBaseTest):
    """Glance Simple Streams Sync Test."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running glance simple streams sync tests."""
        super(GlanceSimpleStreamsSyncTest, cls).setUpClass()
        # dict of OS_* env vars
        overcloud_auth = openstack_utils.get_overcloud_auth()
        cls.keystone_client = openstack_utils.get_keystone_client(
            overcloud_auth)
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session)

    def test_010_wait_for_image_sync(self):
        """Wait for images to be synced. Expect at least four."""
        self.assertTrue(retry_image_sync(self.glance_client))

    def test_050_gss_permissions_regression_check_lp1611987(self):
        """Assert the intended file permissions on gss config files.

        refer: https://bugs.launchpad.net/bugs/1611987
        """
        file_paths = [
            '/etc/glance-simplestreams-sync/identity.yaml',
            '/etc/glance-simplestreams-sync/mirrors.yaml',
            '/var/log/glance-simplestreams-sync.log',
        ]
        expected_perms = '640'

        application = 'glance-simplestreams-sync'
        for unit in zaza_model.get_units(application):
            for file_path in file_paths:
                cmd = 'stat -c %a {}'.format(file_path)
                result = zaza_model.run_on_unit(unit.name, cmd, timeout=30)
                # {'Code': '', 'Stderr': '', 'Stdout': '644\n'}
                perms = result.get('Stdout', '').strip()
                self.assertEqual(perms, expected_perms)
                logging.debug(
                    'Permissions on {}: {}'.format(file_path, perms))

    def test_110_local_product_stream(self):
        """Verify that the local product stream is accessible and has data."""
        logging.debug('Checking local product streams...')
        expected_images = [
            'com.ubuntu.cloud:server:14.04:amd64',
            'com.ubuntu.cloud:server:16.04:amd64',
            'com.ubuntu.cloud:server:18.04:amd64',
            'com.ubuntu.cloud:server:20.04:amd64',
        ]
        uri = "streams/v1/auto.sync.json"

        # There is a race between the images being available in glance and the
        # metadata being written for each image. Use tenacity to avoid this
        # race and make the test idempotent.
        @tenacity.retry(
            retry=tenacity.retry_if_exception_type(
                (AssertionError, KeyError)
            ),
            wait=tenacity.wait_fixed(10), reraise=True,
            stop=tenacity.stop_after_attempt(25))
        def _check_local_product_streams(expected_images):
            # Refresh from catalog as URL may change if swift in use.
            ps_interface = self.keystone_client.service_catalog.url_for(
                service_type='product-streams', interface='publicURL'
            )
            # the product-streams url registered seems to have added a '/' -
            # for the test, ensure that the URL is formatted correctly with
            # only 1 slash between the ps_interface URL and the uri
            if ps_interface.endswith("/"):
                url = "{}{}".format(ps_interface, uri)
            else:
                url = "{}/{}".format(ps_interface, uri)
            logging.info('Retrieving product stream information'
                         ' from {}'.format(url))
            product_streams = get_product_streams(url)
            logging.debug(product_streams)
            images = product_streams["products"]

            for image in expected_images:
                self.assertIn(image, images)

        _check_local_product_streams(expected_images)

        logging.debug("Local product stream successful")
