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

"""Code for configuring ironic."""

import copy
import os

import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.utilities.openstack as openstack_utils
from zaza.openstack.utilities import (
    cli as cli_utils,
)
import zaza.model as zaza_model


FLAVORS = {
    'bm1.small': {
        'flavorid': 2,
        'ram': 2048,
        'disk': 20,
        'vcpus': 1,
        'properties': {
            "resources:CUSTOM_BAREMETAL1_SMALL": 1,
        },
    },
    'bm1.medium': {
        'flavorid': 3,
        'ram': 4096,
        'disk': 40,
        'vcpus': 2,
        'properties': {
            "resources:CUSTOM_BAREMETAL1_MEDIUM": 1,
        },
    },
    'bm1.large': {
        'flavorid': 4,
        'ram': 8192,
        'disk': 40,
        'vcpus': 4,
        'properties': {
            "resources:CUSTOM_BAREMETAL1_LARGE": 1,
        },
    },
    'bm1.tempest': {
        'flavorid': 6,
        'ram': 256,
        'disk': 1,
        'vcpus': 1,
        'properties': {
            "resources:CUSTOM_BAREMETAL1_TEMPEST": 1,
        },
    },
    'bm2.tempest': {
        'flavorid': 7,
        'ram': 512,
        'disk': 1,
        'vcpus': 1,
        'properties': {
            "resources:CUSTOM_BAREMETAL2_TEMPEST": 1,
        },
    },
}


def add_ironic_deployment_image(initrd_url=None, kernel_url=None):
    """Add Ironic deploy images to glance.

    :param initrd_url: URL where the ari image resides
    :type initrd_url: str
    :param kernel_url: URL where the aki image resides
    :type kernel_url: str
    """
    base_name = 'ironic-deploy'
    initrd_name = "{}-initrd".format(base_name)
    vmlinuz_name = "{}-vmlinuz".format(base_name)
    if not initrd_url:
        initrd_url = os.environ.get('TEST_IRONIC_DEPLOY_INITRD', None)
    if not kernel_url:
        kernel_url = os.environ.get('TEST_IRONIC_DEPLOY_VMLINUZ', None)
    if not all([initrd_url, kernel_url]):
        raise ValueError("Missing required deployment image URLs")
    glance_setup.add_image(
        initrd_url,
        image_name=initrd_name,
        backend="swift",
        disk_format="ari",
        container_format="ari")
    glance_setup.add_image(
        kernel_url,
        image_name=vmlinuz_name,
        backend="swift",
        disk_format="aki",
        container_format="aki")


def add_ironic_os_image(image_url=None):
    """Upload the operating system images built for bare metal deployments.

    :param image_url: URL where the image resides
    :type image_url: str
    """
    image_url = image_url or os.environ.get(
        'TEST_IRONIC_RAW_BM_IMAGE', None)
    image_name = "baremetal-ubuntu-image"
    if image_url is None:
        raise ValueError("Missing image_url")

    glance_setup.add_image(
        image_url,
        image_name=image_name,
        backend="swift",
        disk_format="raw",
        container_format="bare")


def set_temp_url_secret():
    """Run the set-temp-url-secret on the ironic-conductor leader.

    This is needed if direct boot method is enabled.
    """
    zaza_model.run_action_on_leader(
        'ironic-conductor',
        'set-temp-url-secret',
        action_params={})


def create_bm_flavors(nova_client=None):
    """Create baremetal flavors.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    """
    if not nova_client:
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        nova_client = openstack_utils.get_nova_session_client(
            keystone_session)
    cli_utils.setup_logging()
    names = [flavor.name for flavor in nova_client.flavors.list()]
    # Disable scheduling based on standard flavor properties
    default_properties = {
        "resources:VCPU": 0,
        "resources:MEMORY_MB": 0,
        "resources:DISK_GB": 0,
    }
    for flavor in FLAVORS.keys():
        if flavor not in names:
            properties = copy.deepcopy(default_properties)
            properties.update(FLAVORS[flavor]["properties"])
            bm_flavor = nova_client.flavors.create(
                name=flavor,
                ram=FLAVORS[flavor]['ram'],
                vcpus=FLAVORS[flavor]['vcpus'],
                disk=FLAVORS[flavor]['disk'],
                flavorid=FLAVORS[flavor]['flavorid'])
            bm_flavor.set_keys(properties)
