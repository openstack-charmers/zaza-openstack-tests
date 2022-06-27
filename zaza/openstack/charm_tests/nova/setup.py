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

"""Code for configuring nova."""

import logging
import tenacity

from zaza import model
import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.openstack.utilities.openstack as openstack_utils
from zaza.openstack.utilities import (
    cli as cli_utils,
    generic as generic_utils,
)
import zaza.openstack.charm_tests.nova.utils as nova_utils


@tenacity.retry(stop=tenacity.stop_after_attempt(3),
                wait=tenacity.wait_exponential(
                multiplier=1, min=2, max=10))
def create_flavors(nova_client=None):
    """Create basic flavors.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    """
    if not nova_client:
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        nova_client = openstack_utils.get_nova_session_client(
            keystone_session)
    cli_utils.setup_logging()
    names = [flavor.name for flavor in nova_client.flavors.list()]
    for flavor in nova_utils.FLAVORS.keys():
        if flavor not in names:
            nova_flavor = nova_client.flavors.create(
                name=flavor,
                ram=nova_utils.FLAVORS[flavor]['ram'],
                vcpus=nova_utils.FLAVORS[flavor]['vcpus'],
                disk=nova_utils.FLAVORS[flavor]['disk'],
                flavorid=nova_utils.FLAVORS[flavor]['flavorid'])
            if 'extra-specs' in nova_utils.FLAVORS[flavor]:
                nova_flavor.set_keys(nova_utils.FLAVORS[flavor]['extra-specs'])


@tenacity.retry(stop=tenacity.stop_after_attempt(3),
                wait=tenacity.wait_exponential(
                multiplier=1, min=2, max=10))
def manage_ssh_key(nova_client=None):
    """Create basic flavors.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    """
    if not nova_client:
        keystone_session = openstack_utils.get_overcloud_keystone_session()
        nova_client = openstack_utils.get_nova_session_client(
            keystone_session)
    cli_utils.setup_logging()
    if not openstack_utils.valid_key_exists(nova_client,
                                            nova_utils.KEYPAIR_NAME):
        key = openstack_utils.create_ssh_key(
            nova_client,
            nova_utils.KEYPAIR_NAME,
            replace=True)
        openstack_utils.write_private_key(
            nova_utils.KEYPAIR_NAME,
            key.private_key)


def reboot_sriov_computes():
    """Reboot nova-compute SR-IOV units."""
    options = (lifecycle_utils
               .get_charm_config(fatal=False)
               .get('configure_options', {}))
    sriov_compute = options.get('sriov_compute_application_name', None)

    for unit in model.get_units(sriov_compute):
        generic_utils.reboot(unit.entity_id)
    logging.info("Waiting for {} units to reboot".format(sriov_compute))
    model.block_until_wl_status_info_starts_with(sriov_compute,
                                                 'Unit is ready')
    logging.info("Waiting for all units to be idle")
    model.block_until_all_units_idle()
    logging.info("All units are idle")
