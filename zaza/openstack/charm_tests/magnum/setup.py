#!/usr/bin/env python3
#
# Copyright 2021 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Code for configuring magnum."""

import logging
import os
import tenacity

import zaza.model
import zaza.openstack.utilities.openstack as openstack_utils

IMAGE_NAME = 'fedora-coreos'


def domain_setup(application_name='magnum'):
    """Run required action for a working Magnum application."""
    # Action is REQUIRED to run for a functioning magnum deployment
    logging.info('Running domain-setup action on magnum unit...')
    zaza.model.block_until_wl_status_info_starts_with(application_name,
                                                      "Unit is ready")
    zaza.model.run_action_on_leader(application_name, "domain-setup")
    zaza.model.block_until_wl_status_info_starts_with(application_name,
                                                      "Unit is ready")


def add_image(image_url=None):
    """Upload Magnum image.

    Upload the operating system images built for Kubernetes deployments.
    Fedora CoreOS image was tested by Magnum team.

    :param image_url: URL where the image resides
    :type image_url: str
    """
    image_url = image_url or os.environ.get(
        'TEST_MAGNUM_QCOW2_IMAGE_URL', None)
    if image_url is None:
        raise ValueError("Missing image_url")
    for attempt in tenacity.Retrying(
            stop=tenacity.stop_after_attempt(3),
            reraise=True):
        with attempt:
            keystone_session = openstack_utils.get_overcloud_keystone_session()
            glance_client = openstack_utils.get_glance_session_client(
                keystone_session)
            image_properties = {
                'os_distro': IMAGE_NAME
            }
            openstack_utils.create_image(glance_client, image_url, IMAGE_NAME,
                                         properties=image_properties)
