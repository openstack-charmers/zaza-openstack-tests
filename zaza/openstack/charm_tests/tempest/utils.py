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

"""Utility code for working with tempest workspaces."""

import jinja2
import logging
import os
from pathlib import Path
import shutil
import subprocess
import urllib.parse

from neutronclient.common import exceptions as neutronexceptions

import zaza.model as model
import zaza.utilities.deployment_env as deployment_env
import zaza.openstack.utilities.juju as juju_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.magnum.setup as magnum_setup

SETUP_ENV_VARS = {
    'neutron': ['TEST_GATEWAY', 'TEST_CIDR_EXT', 'TEST_FIP_RANGE',
                'TEST_NAME_SERVER', 'TEST_CIDR_PRIV'],
    'swift': ['TEST_SWIFT_IP'],
}

IGNORABLE_VARS = ['TEST_CIDR_PRIV']

TEMPEST_FLAVOR_NAME = 'm1.tempest'
TEMPEST_ALT_FLAVOR_NAME = 'm2.tempest'
TEMPEST_SVC_LIST = ['ceilometer', 'cinder', 'glance', 'heat', 'horizon',
                    'ironic', 'manila', 'neutron', 'nova', 'octavia',
                    'sahara', 'swift', 'trove', 'zaqar']


def render_tempest_config_keystone_v2():
    """Render tempest config for Keystone V2 API.

    :returns: None
    :rtype: None
    """
    _setup_tempest('tempest_v2.j2', 'accounts.j2')


def render_tempest_config_keystone_v3(minimal=False):
    """Render tempest config for Keystone V3 API.

    :param minimal: Run in minimal mode eg ignore missing setup
    :type minimal: bool
    :returns: None
    :rtype: None
    """
    _setup_tempest(
        'tempest_v3.j2',
        'accounts.j2',
        minimal=minimal)


def get_workspace():
    """Get tempest workspace name and path.

    :returns: A tuple containing tempest workspace name and workspace path
    :rtype: Tuple[str, str]
    """
    home = str(Path.home())
    workspace_name = model.get_juju_model()
    workspace_path = os.path.join(home, '.tempest', workspace_name)
    return (workspace_name, workspace_path)


def destroy_workspace(workspace_name, workspace_path):
    """Delete tempest workspace.

    :param workspace_name: name of workspace
    :type workspace_name: str
    :param workspace_path: directory path where workspace is stored
    :type workspace_path: str
    :returns: None
    :rtype: None
    """
    try:
        subprocess.check_call(['tempest', 'workspace', 'remove', '--rmdir',
                               '--name', workspace_name])
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    if os.path.isdir(workspace_path):
        shutil.rmtree(workspace_path)


def _init_workspace(workspace_path):
    """Initialize tempest workspace.

    :param workspace_path: directory path where workspace is stored
    :type workspace_path: str
    :returns: None
    :rtype: None
    """
    try:
        subprocess.check_call(['tempest', 'init', workspace_path])
    except subprocess.CalledProcessError:
        pass


def _setup_tempest(tempest_template, accounts_template, minimal=False):
    """Initialize tempest and render tempest config.

    :param tempest_template: tempest.conf template
    :type tempest_template: module
    :param accounts_template: accounts.yaml template
    :type accounts_template: module
    :param minimal: Run in minimal mode eg ignore missing setup
    :type minimal: bool
    :returns: None
    :rtype: None
    """
    workspace_name, workspace_path = get_workspace()
    destroy_workspace(workspace_name, workspace_path)
    _init_workspace(workspace_path)
    context = _get_tempest_context(workspace_path, missing_fatal=not minimal)
    _render_tempest_config(
        os.path.join(workspace_path, 'etc/tempest.conf'),
        context,
        tempest_template)
    _render_tempest_config(
        os.path.join(workspace_path, 'etc/accounts.yaml'),
        context,
        accounts_template)


def _get_tempest_context(workspace_path, missing_fatal=True):
    """Generate the tempest config context.

    :param workspace_path: path to workspace directory
    :type workspace_path: str
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
    :returns: Context dictionary
    :rtype: dict
    """
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    ctxt = {}
    ctxt['workspace_path'] = workspace_path
    ctxt_funcs = {
        'nova': _add_nova_config,
        'neutron': _add_neutron_config,
        'glance': _add_glance_config,
        'cinder': _add_cinder_config,
        'keystone': _add_keystone_config,
        'magnum': _add_magnum_config,
    }
    ctxt['enabled_services'] = _get_service_list(keystone_session)
    if set(['cinderv2', 'cinderv3']) \
            .intersection(set(ctxt['enabled_services'])):
        ctxt['enabled_services'].append('cinder')
    ctxt['disabled_services'] = list(
        set(TEMPEST_SVC_LIST) - set(ctxt['enabled_services']))
    _add_application_ips(ctxt)
    for svc_name, ctxt_func in ctxt_funcs.items():
        if svc_name in ctxt['enabled_services']:
            ctxt_func(
                ctxt,
                keystone_session,
                missing_fatal=missing_fatal)
    _add_environment_var_config(
        ctxt,
        ctxt['enabled_services'],
        missing_fatal=missing_fatal)
    _add_auth_config(ctxt)
    if 'octavia' in ctxt['enabled_services']:
        _add_octavia_config(ctxt)
    return ctxt


def _render_tempest_config(target_file, ctxt, template_name):
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


def _add_application_ips(ctxt):
    """Add application access IPs to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :returns: None
    :rtype: None
    """
    ctxt['keystone'] = juju_utils.get_application_ip('keystone')
    ctxt['dashboard'] = juju_utils.get_application_ip('openstack-dashboard')
    ctxt['ncc'] = juju_utils.get_application_ip('nova-cloud-controller')


def _add_nova_config(ctxt, keystone_session, missing_fatal=True):
    """Add nova config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
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


def _add_neutron_config(ctxt, keystone_session, missing_fatal=True):
    """Add neutron config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
    :returns: None
    :rtype: None
    """
    neutron_client = openstack_utils.get_neutron_session_client(
        keystone_session)
    try:
        net = neutron_client.find_resource("network", "ext_net")
        ctxt['ext_net'] = net['id']
        router = neutron_client.find_resource("router",
                                              openstack_utils.PROVIDER_ROUTER)
        ctxt['provider_router_id'] = router['id']
    except neutronexceptions.NotFound:
        if missing_fatal:
            raise
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


def _add_glance_config(ctxt, keystone_session, missing_fatal=True):
    """Add glance config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
    :returns: None
    :rtype: None
    """
    _add_image_id(ctxt, keystone_session,
                  glance_setup.CIRROS_IMAGE_NAME, 'image_id',
                  missing_fatal)
    _add_image_id(ctxt, keystone_session,
                  glance_setup.CIRROS_ALT_IMAGE_NAME, 'image_alt_id',
                  missing_fatal)


def _add_image_id(ctxt, keystone_session, image_name, ctxt_key,
                  missing_fatal=True):
    """Add an image id to the context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :param image_name: Image's name to search in glance.
    :type image_name: str
    :param ctxt_key: key to use when adding the image id to the context.
    :type ctxt_key: str
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
    """
    glance_client = openstack_utils.get_glance_session_client(
        keystone_session)
    image = openstack_utils.get_images_by_name(glance_client, image_name)
    if image:
        ctxt[ctxt_key] = image[0].id
    else:
        msg = 'Image %s not found' % image_name
        logging.warning(msg)
        if missing_fatal:
            raise Exception(msg)


def _add_cinder_config(ctxt, keystone_session, missing_fatal=True):
    """Add cinder config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
    :returns: None
    :rtype: None
    """
    # The most most recent API version must be listed first.
    volume_types = ['volumev3', 'volumev2']
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    for volume_type in volume_types:
        service = keystone_client.services.list(type=volume_type)
        if service:
            ctxt['catalog_type'] = volume_type
            break


def _add_keystone_config(ctxt, keystone_session, missing_fatal=True):
    """Add keystone config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
    :returns: None
    :rtype: None
    """
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    domain = keystone_client.domains.find(name="admin_domain")
    ctxt['default_domain_id'] = domain.id


def _add_octavia_config(ctxt, missing_fatal=True):
    """Add octavia config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
    :returns: None
    :rtype: None
    :raises: subprocess.CalledProcessError
    """
    subprocess.check_call([
        'curl',
        "{}:80/swift/v1/fixtures/test_server.bin".format(
            ctxt['test_swift_ip']),
        '-o', "{}/test_server.bin".format(ctxt['workspace_path'])
    ])
    subprocess.check_call([
        'chmod', '+x',
        "{}/test_server.bin".format(ctxt['workspace_path'])
    ])


def _add_magnum_config(ctxt, keystone_session, missing_fatal=True):
    """Add magnum config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
    :returns: None
    :rtype: None
    :raises: subprocess.CalledProcessError
    """
    _add_image_id(ctxt, keystone_session,
                  magnum_setup.IMAGE_NAME, 'fedora_coreos_id',
                  missing_fatal)
    test_registry_prefix = os.environ.get('TEST_REGISTRY_PREFIX')
    if test_registry_prefix:
        ctxt['test_registry_prefix'] = test_registry_prefix
    else:
        logging.warning('Environment variable TEST_REGISTRY_PREFIX not found')


def _add_environment_var_config(ctxt, services, missing_fatal=True):
    """Add environment variable config to context.

    :param ctxt: Context dictionary
    :type ctxt: dict
    :param services: List of services
    :type services: List[str]
    :param missing_fatal: Raise an exception if a resource is missing
    :type missing_fatal: bool
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
    if missing_vars and missing_fatal:
        raise ValueError(
            ("Environment variables [{}] must all be set to run this"
             " test").format(', '.join(missing_vars)))


def _add_auth_config(ctxt):
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


def _get_service_list(keystone_session):
    """Retrieve list of services from keystone.

    :param keystone_session: keystoneauth1.session.Session object
    :type: keystoneauth1.session.Session
    :returns: None
    :rtype: None
    """
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)
    return [s.name for s in keystone_client.services.list() if s.enabled]
