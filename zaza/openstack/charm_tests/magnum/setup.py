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

TEST_SWIFT_IP = os.environ.get('TEST_SWIFT_IP')
IMAGE_NAME = 'fedora-coreos'

# https://docs.openstack.org/magnum/latest/user/index.html#supported-versions
# List of published image available at:
# https://builds.coreos.fedoraproject.org/browser?stream=stable&arch=x86_64
#
# Source images:
# https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/35.20220424.3.0/x86_64/fedora-coreos-35.20220424.3.0-openstack.x86_64.qcow2.xz  # noqa
# https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/31.20200517.3.0/x86_64/fedora-coreos-31.20200517.3.0-openstack.x86_64.qcow2.xz  # noqa
# https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/32.20201104.3.0/x86_64/fedora-coreos-32.20201104.3.0-openstack.x86_64.qcow2.xz  # noqa
FEDORA_COREOS_31 = 'http://%s/magnum/images/fedora-coreos-31.qcow2' % TEST_SWIFT_IP  # noqa
FEDORA_COREOS_32 = 'http://%s/magnum/images/fedora-coreos-32.qcow2' % TEST_SWIFT_IP  # noqa
FEDORA_COREOS_35 = 'http://%s/magnum/images/fedora-coreos-35.qcow2' % TEST_SWIFT_IP  # noqa
DEFAULT_FEDORA_COREOS_IMAGE_URL = FEDORA_COREOS_35
FEDORA_COREOS_IMAGE = {
    'ussuri': FEDORA_COREOS_32,
    'victoria': FEDORA_COREOS_31,
    'wallaby': FEDORA_COREOS_31,
    'xena': FEDORA_COREOS_31,
    'yoga': FEDORA_COREOS_35,
    'zed': FEDORA_COREOS_35,
}


def domain_setup(application_name='magnum'):
    """Run required action for a working Magnum application."""
    # Action is REQUIRED to run for a functioning magnum deployment
    logging.info('Running domain-setup action on magnum unit...')
    zaza.model.block_until_wl_status_info_starts_with(application_name,
                                                      "Unit is ready")
    zaza.model.run_action_on_leader(application_name, "domain-setup")
    zaza.model.block_until_wl_status_info_starts_with(application_name,
                                                      "Unit is ready")


def get_fedora_coreos_image_url(os_release: str = None) -> str:
    """Get Fedora CoreOS image url compatible with the Magnum release deployed.

    :param os_release: OpenStack release codename (e.g. ussuri).
    :returns: url where the image can be GET.
    """
    if not os_release:
        pair = openstack_utils.get_current_os_release_pair('keystone')
        os_release = pair.split('_', 1)[1]
    if os_release in FEDORA_COREOS_IMAGE:
        return FEDORA_COREOS_IMAGE[os_release]
    else:
        logging.warning(
            'No image found for OpenStack %s, using default image %s',
            os_release, DEFAULT_FEDORA_COREOS_IMAGE_URL
        )
        return DEFAULT_FEDORA_COREOS_IMAGE_URL


def add_image(image_url=None):
    """Upload Magnum image.

    Upload the operating system images built for Kubernetes deployments.
    Fedora CoreOS image was tested by Magnum team.

    :param image_url: URL where the image resides
    :type image_url: str
    """
    image_url = image_url or os.environ.get(
        'TEST_MAGNUM_QCOW2_IMAGE_URL', None) or get_fedora_coreos_image_url()

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
