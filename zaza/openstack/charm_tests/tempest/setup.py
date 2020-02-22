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

"""Code for configuring tempest."""
import urllib.parse
import os

import zaza.model
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.tempest.templates.tempest_v3 as tempest_v3

SETUP_ENV_VARS = [
    'OS_TEST_GATEWAY',
    'OS_TEST_CIDR_EXT',
    'OS_TEST_FIP_RANGE',
    'OS_TEST_NAMESERVER',
    'OS_TEST_CIDR_PRIV',
    'OS_TEST_SWIFT_IP',
]


def get_app_access_ip(application_name):
    try:
        app_config = zaza.model.get_application_config(application_name)
    except KeyError:
        return ''
    vip = app_config.get("vip").get("value")
    if vip:
        ip = vip
    else:
        unit = zaza.model.get_units(application_name)[0]
        ip = unit.public_address
    return ip


def add_application_ips(ctxt):
    ctxt['keystone'] = get_app_access_ip('keystone')
    ctxt['dashboard'] = get_app_access_ip('openstack-dashboard')
    ctxt['ncc'] = get_app_access_ip('nova-cloud-controller')


def add_neutron_config(ctxt, keystone_session):
    neutron_client = openstack_utils.get_neutron_session_client(
        keystone_session)
    for net in neutron_client.list_networks()['networks']:
        if net['name'] == 'ext_net':
            ctxt['ext_net'] = net['id']
            break
    for router in neutron_client.list_routers()['routers']:
        if router['name'] == 'provider-router':
            ctxt['provider_router_id'] = router['id']
            break


def add_glance_config(ctxt, keystone_session):
    glance_client = openstack_utils.get_glance_session_client(
        keystone_session)
    image = openstack_utils.get_images_by_name(
        glance_client, glance_setup.CIRROS_IMAGE_NAME)
    image_alt = openstack_utils.get_images_by_name(
        glance_client, glance_setup.CIRROS_ALT_IMAGE_NAME)
    if image:
        ctxt['image_id'] = image[0].id
    if image_alt:
        ctxt['image_alt_id'] = image_alt[0].id


def add_keystone_config(ctxt, keystone_session):
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    for domain in keystone_client.domains.list():
        if domain.name == 'admin_domain':
            ctxt['default_domain_id'] = domain.id
            break


def add_environment_var_config(ctxt):
    for var in SETUP_ENV_VARS:
        value = os.environ.get(var)
        if value:
            ctxt[var.lower()] = value
        else:
            raise ValueError(
                ("Environment variables {} must all be set to run this"
                 " test").format(', '.join(SETUP_ENV_VARS)))


def add_access_protocol(ctxt):
    overcloud_auth = openstack_utils.get_overcloud_auth()
    ctxt['proto'] = urllib.parse.urlparse(overcloud_auth['OS_AUTH_URL']).scheme


def get_tempest_context():
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    ctxt = {}
    add_application_ips(ctxt)
    add_neutron_config(ctxt, keystone_session)
    add_glance_config(ctxt, keystone_session)
    add_keystone_config(ctxt, keystone_session)
    add_environment_var_config(ctxt)
    add_access_protocol(ctxt)
    return ctxt


def render_tempest_config(target_file, ctxt, tempest_template):
    with open(target_file, 'w') as f:
        f.write(tempest_template.file_contents.format(**ctxt))


def setup_tempest(tempest_template):
    try:
        os.mkdir('tempest')
    except FileExistsError:
        pass
    render_tempest_config(
        'tempest/tempest.conf',
        get_tempest_context(),
        tempest_template)


def tempest_keystone_v3():
    setup_tempest(tempest_v3)
