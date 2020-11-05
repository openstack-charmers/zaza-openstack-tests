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

"""Code for configuring glance."""

import logging
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.utilities.deployment_env as deployment_env

CIRROS_IMAGE_NAME = "cirros"
CIRROS_ALT_IMAGE_NAME = "cirros_alt"
LTS_RELEASE = "bionic"
LTS_IMAGE_NAME = "bionic"


def basic_setup():
    """Run setup for testing glance.

    Glance setup for testing glance is currently part of glance functional
    tests. Image setup for other tests to use should go here.
    """


def _get_default_glance_client():
    """Create default Glance client using overcloud credentials."""
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    glance_client = openstack_utils.get_glance_session_client(keystone_session)
    return glance_client


def get_stores_info(glance_client=None):
    """Retrieve glance backing store info.

    :param glance_client: Authenticated glanceclient
    :type glance_client: glanceclient.Client
    """
    glance_client = glance_client or _get_default_glance_client()
    stores = glance_client.images.get_stores_info().get("stores", [])
    return stores


def get_store_ids(glance_client=None):
    """Retrieve glance backing store ids.

    :param glance_client: Authenticated glanceclient
    :type glance_client: glanceclient.Client
    """
    stores = get_stores_info(glance_client)
    return [store["id"] for store in stores]


def add_image(image_url, glance_client=None, image_name=None, tags=[],
              properties=None, backend=None, disk_format='qcow2',
              visibility='public', container_format='bare'):
    """Retrieve image from ``image_url`` and add it to glance.

    :param image_url: Retrievable URL with image data
    :type image_url: str
    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :param image_name: Label for the image in glance
    :type image_name: str
    :param tags: List of tags to add to image
    :type tags: list of str
    :param properties: Properties to add to image
    :type properties: dict
    """
    glance_client = glance_client or _get_default_glance_client()
    if backend is not None:
        stores = get_store_ids(glance_client)
        if backend not in stores:
            raise ValueError("Invalid backend: %(backend)s "
                             "(available: %(available)s)" % {
                                 "backend": backend,
                                 "available": ", ".join(stores)})
    if image_name:
        image = openstack_utils.get_images_by_name(
            glance_client, image_name)

    if image:
        logging.warning('Using existing glance image "{}" ({})'
                        .format(image_name, image[0].id))
    else:
        logging.info('Downloading image {}'.format(image_name or image_url))
        openstack_utils.create_image(
            glance_client,
            image_url,
            image_name,
            tags=tags,
            properties=properties,
            backend=backend,
            disk_format=disk_format,
            visibility=visibility,
            container_format=container_format)


def add_cirros_image(glance_client=None, image_name=None):
    """Add a cirros image to the current deployment.

    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :param image_name: Label for the image in glance
    :type image_name: str
    """
    image_name = image_name or CIRROS_IMAGE_NAME
    image_url = openstack_utils.find_cirros_image(arch='x86_64')
    add_image(image_url,
              glance_client=glance_client,
              image_name=image_name)


def add_cirros_alt_image(glance_client=None, image_name=None):
    """Add alt cirros image to the current deployment.

    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :param image_name: Label for the image in glance
    :type image_name: str
    """
    image_name = image_name or CIRROS_ALT_IMAGE_NAME
    add_cirros_image(glance_client, image_name)


def add_lts_image(glance_client=None, image_name=None, release=None,
                  properties=None):
    """Add an Ubuntu LTS image to the current deployment.

    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :param image_name: Label for the image in glance
    :type image_name: str
    :param release: Name of ubuntu release.
    :type release: str
    :param properties: Custom image properties
    :type properties: dict
    """
    deploy_ctxt = deployment_env.get_deployment_context()
    image_arch = deploy_ctxt.get('TEST_IMAGE_ARCH', 'amd64')
    arch_image_properties = {
        'arm64': {'hw_firmware_type': 'uefi'},
        'ppc64el': {'architecture': 'ppc64'}}
    properties = properties or arch_image_properties.get(image_arch)
    logging.info("Image architecture set to {}".format(image_arch))
    image_name = image_name or LTS_IMAGE_NAME
    release = release or LTS_RELEASE
    image_url = openstack_utils.find_ubuntu_image(
        release=release,
        arch=image_arch)
    add_image(image_url,
              glance_client=glance_client,
              image_name=image_name,
              properties=properties)
