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

"""Code for configuring and initializing tempest."""

import jinja2
import urllib.parse
import os
import subprocess

import zaza.utilities.deployment_env as deployment_env
import zaza.openstack.utilities.juju as juju_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.tempest.utils as tempest_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup

SETUP_ENV_VARS = {
    'neutron': ['TEST_GATEWAY', 'TEST_CIDR_EXT', 'TEST_FIP_RANGE',
                'TEST_NAME_SERVER', 'TEST_CIDR_PRIV'],
    'swift': ['TEST_SWIFT_IP'],
}

IGNORABLE_VARS = ['TEST_CIDR_PRIV']

TEMPEST_FLAVOR_NAME = 'm1.tempest'
TEMPEST_ALT_FLAVOR_NAME = 'm2.tempest'
TEMPEST_SVC_LIST = ['ceilometer', 'cinder', 'glance', 'heat', 'horizon',
                    'ironic', 'neutron', 'nova', 'octavia', 'sahara', 'swift',
                    'trove', 'zaqar']


def add_application_ips(ctxt):
    """Add application access IPs to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :returns: None
    :rtype: None
    """
    ctxt['keystone'] = juju_utils.get_application_ip('keystone')
    ctxt['dashboard'] = juju_utils.get_application_ip('openstack-dashboard')
    ctxt['ncc'] = juju_utils.get_application_ip('nova-cloud-controller')


def add_nova_config(ctxt, keystone_session):
    """Add nova config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :returns: None
    :rtype: None
    """
    nova_client = openstack_utils.get_nova_session_client(
        keystone_session)
    for flavor in nova_client.flavors.list():
        if flavor.name == TEMPEST_FLAVOR_NAME:
            ctxt['flavor_ref'] = flavor.id
        if flavor.name == TEMPEST_ALT_FLAVOR_NAME:
            ctxt['flavor_ref_alt'] = flavor.id


def add_neutron_config(ctxt, keystone_session):
    """Add neutron config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :returns: None
    :rtype: None
    """
    current_release = openstack_utils.get_os_release()
    focal_ussuri = openstack_utils.get_os_release('focal_ussuri')
    neutron_client = openstack_utils.get_neutron_session_client(
        keystone_session)
    net = neutron_client.find_resource("network", "ext_net")
    ctxt['ext_net'] = net['id']
    router = neutron_client.find_resource("router", "provider-router")
    ctxt['provider_router_id'] = router['id']
    # For focal+ with OVN, we use the same settings as upstream gate.
    # This is because the l3_agent_scheduler extension is only
    # applicable for OVN when conventional layer-3 agent enabled:
    # https://docs.openstack.org/networking-ovn/2.0.1/features.html
    # This enables test_list_show_extensions to run successfully.
    if current_release >= focal_ussuri:
        extensions = ('address-scope,agent,allowed-address-pairs,'
                      'auto-allocated-topology,availability_zone,'
                      'binding,default-subnetpools,external-net,'
                      'extra_dhcp_opt,multi-provider,net-mtu,'
                      'network_availability_zone,network-ip-availability,'
                      'port-security,provider,quotas,rbac-address-scope,'
                      'rbac-policies,standard-attr-revisions,security-group,'
                      'standard-attr-description,subnet_allocation,'
                      'standard-attr-tag,standard-attr-timestamp,trunk,'
                      'quota_details,router,extraroute,ext-gw-mode,'
                      'fip-port-details,pagination,sorting,project-id,'
                      'dns-integration,qos')
        ctxt['neutron_api_extensions'] = extensions
    else:
        ctxt['neutron_api_extensions'] = 'all'


def add_glance_config(ctxt, keystone_session):
    """Add glance config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :returns: None
    :rtype: None
    """
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


def add_cinder_config(ctxt, keystone_session):
    """Add cinder config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :returns: None
    :rtype: None
    """
    volume_types = ['volumev2', 'volumev3']
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    for volume_type in volume_types:
        service = keystone_client.services.list(type=volume_type)
        if service:
            ctxt['catalog_type'] = volume_type
            break


def add_keystone_config(ctxt, keystone_session):
    """Add keystone config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :returns: None
    :rtype: None
    """
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    domain = keystone_client.domains.find(name="admin_domain")
    ctxt['default_domain_id'] = domain.id


def add_octavia_config(ctxt):
    """Add octavia config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :returns: None
    :rtype: None
    :raises: subprocess.CalledProcessError
    """
    subprocess.check_call([
        'curl',
        "{}:80/swift/v1/fixtures/test_server.bin".format(
            ctxt['test_swift_ip']),
        '-o', "{}test_server.bin".format(ctxt['workspace_path'])
    ])


def get_service_list(keystone_session):
    """Retrieve list of services from keystone.

    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :returns: None
    :rtype: None
    """
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    return [s.name for s in keystone_client.services.list() if s.enabled]


def add_environment_var_config(ctxt, services):
    """Add environment variable config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :returns: None
    :rtype: None
    """
    deploy_env = deployment_env.get_deployment_context()
    missing_vars = []
    for svc, env_vars in SETUP_ENV_VARS.items():
        if svc in services:
            for var in env_vars:
                value = deploy_env.get(var)
                if value:
                    ctxt[var.lower()] = value
                else:
                    if var not in IGNORABLE_VARS:
                        missing_vars.append(var)
    if missing_vars:
        raise ValueError(
            ("Environment variables [{}] must all be set to run this"
             " test").format(', '.join(missing_vars)))


def add_auth_config(ctxt):
    """Add authorization config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :returns: None
    :rtype: None
    """
    overcloud_auth = openstack_utils.get_overcloud_auth()
    ctxt['proto'] = urllib.parse.urlparse(overcloud_auth['OS_AUTH_URL']).scheme
    ctxt['admin_username'] = overcloud_auth['OS_USERNAME']
    ctxt['admin_password'] = overcloud_auth['OS_PASSWORD']
    if overcloud_auth['API_VERSION'] == 3:
        ctxt['admin_project_name'] = overcloud_auth['OS_PROJECT_NAME']
        ctxt['admin_domain_name'] = overcloud_auth['OS_DOMAIN_NAME']
        ctxt['default_credentials_domain_name'] = (
            overcloud_auth['OS_PROJECT_DOMAIN_NAME'])


def get_tempest_context(workspace_path):
    """Generate the tempest config context.

    :returns: Context dictionary
    :rtype: dict
    """
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    ctxt = {}
    ctxt['workspace_path'] = workspace_path
    ctxt_funcs = {
        'nova': add_nova_config,
        'neutron': add_neutron_config,
        'glance': add_glance_config,
        'cinder': add_cinder_config,
        'keystone': add_keystone_config}
    ctxt['enabled_services'] = get_service_list(keystone_session)
    if set(['cinderv2', 'cinderv3']) \
            .intersection(set(ctxt['enabled_services'])):
        ctxt['enabled_services'].append('cinder')
    ctxt['disabled_services'] = list(
        set(TEMPEST_SVC_LIST) - set(ctxt['enabled_services']))
    add_application_ips(ctxt)
    for svc_name, ctxt_func in ctxt_funcs.items():
        if svc_name in ctxt['enabled_services']:
            ctxt_func(ctxt, keystone_session)
    add_environment_var_config(ctxt, ctxt['enabled_services'])
    add_auth_config(ctxt)
    add_octavia_config(ctxt)
    return ctxt


def render_tempest_config(target_file, ctxt, template_name):
    """Render tempest config for specified config file and template.

    :param target_file: Name of file to render config to
    :type target_file: str
    :param ctxt: Context dictionary
    :type ctxt: dict
    :param template_name: Name of template file
    :type template_name: str
    :returns: None
    :rtype: None
    """
    jenv = jinja2.Environment(loader=jinja2.PackageLoader(
        'zaza.openstack',
        'charm_tests/tempest/templates'))
    template = jenv.get_template(template_name)
    with open(target_file, 'w') as f:
        f.write(template.render(ctxt))


def setup_tempest(tempest_template, accounts_template):
    """Initialize tempest and render tempest config.

    :param tempest_template: tempest.conf template
    :type tempest_template: module
    :param accounts_template: accounts.yaml template
    :type accounts_template: module
    :returns: None
    :rtype: None
    """
    workspace_name, workspace_path = tempest_utils.get_workspace()
    tempest_utils.destroy_workspace(workspace_name, workspace_path)
    tempest_utils.init_workspace(workspace_path)
    context = get_tempest_context(workspace_path)
    render_tempest_config(
        os.path.join(workspace_path, 'etc/tempest.conf'),
        context,
        tempest_template)
    render_tempest_config(
        os.path.join(workspace_path, 'etc/accounts.yaml'),
        context,
        accounts_template)


def render_tempest_config_keystone_v2():
    """Render tempest config for Keystone V2 API.

    :returns: None
    :rtype: None
    """
    setup_tempest('tempest_v2.j2', 'accounts.j2')


def render_tempest_config_keystone_v3():
    """Render tempest config for Keystone V3 API.

    :returns: None
    :rtype: None
    """
    setup_tempest('tempest_v3.j2', 'accounts.j2')
