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

"""Module for interacting with OpenStack.

This module contains a number of functions for interacting with OpenStack.
"""
import collections
import copy
import datetime
import enum
import io
import itertools
import juju_wait
import logging
import os
import paramiko
import re
import shutil
import six
import subprocess
import sys
import tempfile
import tenacity
import textwrap
import urllib


from .os_versions import (
    CompareOpenStack,
    OPENSTACK_CODENAMES,
    SWIFT_CODENAMES,
    OVN_CODENAMES,
    PACKAGE_CODENAMES,
    OPENSTACK_RELEASES_PAIRS,
)

from openstack import connection

from aodhclient.v2 import client as aodh_client
from cinderclient import client as cinderclient
from heatclient import client as heatclient
from magnumclient import client as magnumclient
from glanceclient import Client as GlanceClient
from designateclient.client import Client as DesignateClient

from keystoneclient.v2_0 import client as keystoneclient_v2
from keystoneclient.v3 import client as keystoneclient_v3
from keystoneauth1 import session
from keystoneauth1.identity import (
    v3,
    v2,
)
import zaza.openstack.utilities.cert as cert
import zaza.utilities.deployment_env as deployment_env
import zaza.utilities.juju as juju_utils
import zaza.utilities.maas
from novaclient import client as novaclient_client
from neutronclient.v2_0 import client as neutronclient
from neutronclient.common import exceptions as neutronexceptions
from octaviaclient.api.v2 import octavia as octaviaclient
from swiftclient import client as swiftclient
from manilaclient import client as manilaclient

from juju.errors import JujuError

import zaza

from zaza import model
from zaza.openstack.utilities import (
    exceptions,
    generic as generic_utils,
)
import zaza.utilities.networking as network_utils


CIRROS_RELEASE_URL = 'http://download.cirros-cloud.net/version/released'
CIRROS_IMAGE_URL = 'http://download.cirros-cloud.net'
UBUNTU_IMAGE_URLS = {
    'bionic': ('http://cloud-images.ubuntu.com/{release}/current/'
               '{release}-server-cloudimg-{arch}.img'),
    'focal': ('http://cloud-images.ubuntu.com/{release}/current/'
              '{release}-server-cloudimg-{arch}.img'),
    'default': ('http://cloud-images.ubuntu.com/{release}/current/'
                '{release}-server-cloudimg-{arch}.img'),
}

CHARM_TYPES = {
    'neutron': {
        'pkg': 'neutron-common',
        'origin_setting': 'openstack-origin'
    },
    'nova': {
        'pkg': 'nova-common',
        'origin_setting': 'openstack-origin'
    },
    'glance': {
        'pkg': 'glance-common',
        'origin_setting': 'openstack-origin'
    },
    'cinder': {
        'pkg': 'cinder-common',
        'origin_setting': 'openstack-origin'
    },
    'keystone': {
        'pkg': 'keystone',
        'origin_setting': 'openstack-origin'
    },
    'openstack-dashboard': {
        'pkg': 'openstack-dashboard',
        'origin_setting': 'openstack-origin'
    },
    'ceilometer': {
        'pkg': 'ceilometer-common',
        'origin_setting': 'openstack-origin'
    },
    'designate': {
        'pkg': 'designate-common',
        'origin_setting': 'openstack-origin'
    },
    'ovn-central': {
        'pkg': 'ovn-common',
        'origin_setting': 'source'
    },
    'ceph-mon': {
        'pkg': 'ceph-common',
        'origin_setting': 'source'
    },
    'placement': {
        'pkg': 'placement-common',
        'origin_setting': 'openstack-origin'
    },
}

# Older tests use the order the services appear in the list to imply
# the order they should be upgraded in. This approach has been superceded and
# zaza.openstack.utilities.openstack_upgrade.get_upgrade_groups should be used
# instead.
UPGRADE_SERVICES = [
    {'name': 'keystone', 'type': CHARM_TYPES['keystone']},
    {'name': 'neutron-api', 'type': CHARM_TYPES['neutron']},
    {'name': 'nova-cloud-controller', 'type': CHARM_TYPES['nova']},
    {'name': 'glance', 'type': CHARM_TYPES['glance']},
    {'name': 'cinder', 'type': CHARM_TYPES['cinder']},
    {'name': 'neutron-gateway', 'type': CHARM_TYPES['neutron']},
    {'name': 'ceilometer', 'type': CHARM_TYPES['ceilometer']},
    {'name': 'designate', 'type': CHARM_TYPES['designate']},
    {'name': 'nova-compute', 'type': CHARM_TYPES['nova']},
    {'name': 'openstack-dashboard',
     'type': CHARM_TYPES['openstack-dashboard']},
    {'name': 'ovn-central', 'type': CHARM_TYPES['ovn-central']},
    {'name': 'ceph-mon', 'type': CHARM_TYPES['ceph-mon']},
    {'name': 'placement', 'type': CHARM_TYPES['placement']},
]


WORKLOAD_STATUS_EXCEPTIONS = {
    'vault': {
        'workload-status': 'blocked',
        'workload-status-message': 'Vault needs to be initialized'},
    'easyrsa': {
        'workload-status-message': 'Certificate Authority connected.'},
    'etcd': {
        'workload-status-message': 'Healthy'},
    'memcached': {
        'workload-status': 'unknown',
        'workload-status-message': ''},
    'mongodb': {
        'workload-status': 'unknown',
        'workload-status-message': ''},
    'postgresql': {
        'workload-status-message': 'Live'},
    'ceilometer': {
        'workload-status': 'blocked',
        'workload-status-message':
            ('Run the ceilometer-upgrade action on the leader to initialize '
             'ceilometer and gnocchi')}}

# For vault TLS certificates
CACERT_FILENAME_FORMAT = "{}_juju_ca_cert.crt"
CERT_PROVIDERS = ['vault']
REMOTE_CERT_DIR = "/usr/local/share/ca-certificates"
KEYSTONE_CACERT = "keystone_juju_ca_cert.crt"
KEYSTONE_REMOTE_CACERT = (
    "/usr/local/share/ca-certificates/{}".format(KEYSTONE_CACERT))

# Network/router names
EXT_NET = os.environ.get('TEST_EXT_NET', 'ext_net')
EXT_NET_SUBNET = os.environ.get('TEST_EXT_NET_SUBNET', 'ext_net_subnet')
PRIVATE_NET = os.environ.get('TEST_PRIVATE_NET', 'private')
PRIVATE_NET_SUBNET = os.environ.get('TEST_PRIVATE_NET_SUBNET',
                                    'private_subnet')
PROVIDER_ROUTER = os.environ.get('TEST_PROVIDER_ROUTER', 'provider-router')

# Image names
CIRROS_IMAGE_NAME = os.environ.get('TEST_CIRROS_IMAGE_NAME', 'cirros')
BIONIC_IMAGE_NAME = os.environ.get('TEST_BIONIC_IMAGE_NAME', 'bionic')
FOCAL_IMAGE_NAME = os.environ.get('TEST_FOCAL_IMAGE_NAME', 'focal')
JAMMY_IMAGE_NAME = os.environ.get('TEST_JAMMY_IMAGE_NAME', 'jammy')


async def async_block_until_ca_exists(application_name, ca_cert,
                                      model_name=None, timeout=2700):
    """Block until a CA cert is on all units of application_name.

    :param application_name: Name of application to check
    :type application_name: str
    :param ca_cert: The certificate content.
    :type ca_cert: str
    :param model_name: Name of model to query.
    :type model_name: str
    :param timeout: How long in seconds to wait
    :type timeout: int
    """
    async def _check_ca_present(model, ca_files):
        units = model.applications[application_name].units
        for ca_file in ca_files:
            for unit in units:
                try:
                    output = await unit.run('cat {}'.format(ca_file))
                    contents = output.data.get('results').get('Stdout', '')
                    if ca_cert not in contents:
                        break
                # libjuju throws a generic error for connection failure. So we
                # cannot differentiate between a connectivity issue and a
                # target file not existing error. For now just assume the
                # latter.
                except JujuError:
                    break
            else:
                # The CA was found in `ca_file` on all units.
                return True
        else:
            return False
    ca_files = await _async_get_remote_ca_cert_file_candidates(
        application_name,
        model_name=model_name)
    async with zaza.model.run_in_model(model_name) as model:
        await zaza.model.async_block_until(
            lambda: _check_ca_present(model, ca_files), timeout=timeout)

block_until_ca_exists = zaza.model.sync_wrapper(async_block_until_ca_exists)


def get_cacert_absolute_path(filename):
    """Build string containing location of the CA Certificate file.

    :param filename: Expected filename for CA Certificate file.
    :type filename: str
    :returns: Absolute path to file containing CA Certificate
    :rtype: str
    """
    return os.path.join(
        deployment_env.get_tmpdir(), filename)


def get_cacert():
    """Return path to CA Certificate bundle for verification during test.

    :returns: Path to CA Certificate bundle or None.
    :rtype: Union[str, None]
    """
    for _provider in CERT_PROVIDERS:
        _cert = get_cacert_absolute_path(
            CACERT_FILENAME_FORMAT.format(_provider))
        if os.path.exists(_cert):
            return _cert
    _keystone_local_cacert = get_cacert_absolute_path(KEYSTONE_CACERT)
    if os.path.exists(_keystone_local_cacert):
        return _keystone_local_cacert


# OpenStack Client helpers
def get_ks_creds(cloud_creds, scope='PROJECT'):
    """Return the credentials for authenticating against keystone.

    :param cloud_creds: OpenStack RC environment credentials
    :type cloud_creds: dict
    :param scope: Authentication scope: PROJECT or DOMAIN
    :type scope: string
    :returns: Credentials dictionary
    :rtype: dict
    """
    if cloud_creds.get('API_VERSION', 2) == 2:
        auth = {
            'username': cloud_creds['OS_USERNAME'],
            'password': cloud_creds['OS_PASSWORD'],
            'auth_url': cloud_creds['OS_AUTH_URL'],
            'tenant_name': (cloud_creds.get('OS_PROJECT_NAME') or
                            cloud_creds['OS_TENANT_NAME']),
        }
    else:
        if scope == 'DOMAIN':
            auth = {
                'username': cloud_creds['OS_USERNAME'],
                'password': cloud_creds['OS_PASSWORD'],
                'auth_url': cloud_creds['OS_AUTH_URL'],
                'user_domain_name': cloud_creds['OS_USER_DOMAIN_NAME'],
                'domain_name': cloud_creds['OS_DOMAIN_NAME'],
            }
        else:
            auth = {
                'username': cloud_creds['OS_USERNAME'],
                'password': cloud_creds['OS_PASSWORD'],
                'auth_url': cloud_creds['OS_AUTH_URL'],
                'project_domain_name': cloud_creds['OS_PROJECT_DOMAIN_NAME'],
                'project_name': cloud_creds['OS_PROJECT_NAME'],
            }
            # the FederationBaseAuth class doesn't support the
            # 'user_domain_name' argument, so only setting it in the 'auth'
            # dict when it's passed in the cloud_creds.
            if cloud_creds.get('OS_USER_DOMAIN_NAME'):
                auth['user_domain_name'] = cloud_creds['OS_USER_DOMAIN_NAME']

        if cloud_creds.get('OS_AUTH_TYPE') == 'v3oidcpassword':
            auth.update({
                'identity_provider': cloud_creds['OS_IDENTITY_PROVIDER'],
                'protocol': cloud_creds['OS_PROTOCOL'],
                'client_id': cloud_creds['OS_CLIENT_ID'],
                'client_secret': cloud_creds['OS_CLIENT_SECRET'],
                # optional configuration options:
                'access_token_endpoint': cloud_creds.get(
                    'OS_ACCESS_TOKEN_ENDPOINT'),
                'discovery_endpoint': cloud_creds.get('OS_DISCOVERY_ENDPOINT')
            })
    return auth


def get_glance_session_client(session):
    """Return glanceclient authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :returns: Authenticated glanceclient
    :rtype: glanceclient.Client
    """
    return GlanceClient('2', session=session)


def get_designate_session_client(**kwargs):
    """Return designateclient authenticated by keystone session.

    :param kwargs: Designate Client Arguments
    :returns: Authenticated designateclient
    :rtype: DesignateClient
    """
    version = kwargs.pop('version', None) or 2
    return DesignateClient(version=str(version),
                           **kwargs)


def get_nova_session_client(session, version=2):
    """Return novaclient authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :param version: Version of client to request.
    :type version: float
    :returns: Authenticated novaclient
    :rtype: novaclient.Client object
    """
    return novaclient_client.Client(version, session=session)


def get_neutron_session_client(session):
    """Return neutronclient authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :returns: Authenticated neutronclient
    :rtype: neutronclient.Client object
    """
    return neutronclient.Client(session=session)


def get_swift_session_client(session,
                             region_name='RegionOne',
                             cacert=None):
    """Return swiftclient authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :param region_name: Optional region name to use
    :type region_name: str
    :param cacert: Path to CA Certificate
    :type cacert: Optional[str]
    :returns: Authenticated swiftclient
    :rtype: swiftclient.Client object
    """
    return swiftclient.Connection(session=session,
                                  os_options={'region_name': region_name},
                                  cacert=cacert)


def get_octavia_session_client(session, service_type='load-balancer',
                               interface='internal'):
    """Return octavia client authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :param service_type: Service type to look for in catalog
    :type service_type: str
    :param interface: Interface to look for in catalog
    :type interface: str
    :returns: Authenticated octaviaclient
    :rtype: octaviaclient.OctaviaAPI object
    """
    keystone_client = get_keystone_session_client(session)
    lbaas_service = keystone_client.services.list(type=service_type)
    for service in lbaas_service:
        lbaas_endpoint = keystone_client.endpoints.list(service=service,
                                                        interface='internal')
        for endpoint in lbaas_endpoint:
            break
    return octaviaclient.OctaviaAPI(session=session,
                                    service_type=service_type,
                                    endpoint=endpoint.url)


def get_heat_session_client(session, version=1):
    """Return heatclient authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :param version: Heat API version
    :type version: int
    :returns: Authenticated cinderclient
    :rtype: heatclient.Client object
    """
    return heatclient.Client(session=session, version=version)


def get_magnum_session_client(session, version='1'):
    """Return magnumclient authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :param version: Magnum API version
    :type version: string
    :returns: Authenticated magnumclient
    :rtype: magnumclient.Client object
    """
    return magnumclient.Client(version, session=session)


def get_cinder_session_client(session, version=3):
    """Return cinderclient authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :param version: Cinder API version
    :type version: int
    :returns: Authenticated cinderclient
    :rtype: cinderclient.Client object
    """
    return cinderclient.Client(session=session, version=version)


def get_masakari_session_client(session, interface='internal',
                                region_name='RegionOne'):
    """Return masakari client authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :param interface: Interface to look for in catalog
    :type interface: str
    :param region_name: Region name to use in catalogue lookup
    :type region_name: str
    :returns: Authenticated masakari client
    :rtype: openstack.instance_ha.v1._proxy.Proxy
    """
    conn = connection.Connection(session=session,
                                 interface=interface,
                                 region_name=region_name)
    return conn.instance_ha


def get_aodh_session_client(session):
    """Return aodh client authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :returns: Authenticated aodh client
    :rtype: openstack.instance_ha.v1._proxy.Proxy
    """
    return aodh_client.Client(session=session)


def get_manila_session_client(session, version='2'):
    """Return Manila client authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :param version: Manila API version
    :type version: str
    :returns: Authenticated manilaclient
    :rtype: manilaclient.Client
    """
    return manilaclient.Client(session=session, client_version=version)


def get_keystone_scope(model_name=None):
    """Return Keystone scope based on OpenStack release of the overcloud.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: String keystone scope
    :rtype: string
    """
    return "PROJECT"


def get_keystone_session(openrc_creds, scope='PROJECT', verify=None):
    """Return keystone session.

    :param openrc_creds: OpenStack RC credentials
    :type openrc_creds: dict
    :param verify: Control TLS certificate verification behaviour
    :type verify: any (True  - use system certs,
                       False - do not verify,
                       None  - defer to requests library to find certs,
                       str   - path to a CA cert bundle)
    :param scope: Authentication scope: PROJECT or DOMAIN
    :type scope: string
    :returns: Keystone session object
    :rtype: keystoneauth1.session.Session object
    """
    keystone_creds = get_ks_creds(openrc_creds, scope=scope)
    if not verify and openrc_creds.get('OS_CACERT'):
        verify = openrc_creds['OS_CACERT']
    if openrc_creds.get('API_VERSION', 2) == 2:
        auth = v2.Password(**keystone_creds)
    else:
        if openrc_creds.get('OS_AUTH_TYPE') == 'v3oidcpassword':
            auth = v3.OidcPassword(**keystone_creds)
        else:
            auth = v3.Password(**keystone_creds)
    return session.Session(auth=auth, verify=verify)


def get_overcloud_keystone_session(verify=None, model_name=None):
    """Return Over cloud keystone session.

    :param verify: Control TLS certificate verification behaviour
    :type verify: any
    :param model_name: Name of model to query.
    :type model_name: str
    :returns keystone_session: keystoneauth1.session.Session object
    :rtype: keystoneauth1.session.Session
    """
    return get_keystone_session(
        get_overcloud_auth(model_name=model_name),
        scope=get_keystone_scope(model_name=model_name),
        verify=verify)


def get_undercloud_keystone_session(verify=None):
    """Return Under cloud keystone session.

    :param verify: Control TLS certificate verification behaviour
    :type verify: any
    :returns keystone_session: keystoneauth1.session.Session object
    :rtype: keystoneauth1.session.Session
    """
    return get_keystone_session(get_undercloud_auth(),
                                verify=verify)


def get_keystone_session_client(session, client_api_version=3):
    """Return keystoneclient authenticated by keystone session.

    :param session: Keystone session object
    :type session: keystoneauth1.session.Session object
    :param client_api_version: Whether you want a v2 or v3 Keystone Client
    :type client_api_version: int
    :returns: Authenticated keystoneclient
    :rtype: keystoneclient.v3.Client object
    """
    if client_api_version == 2:
        return keystoneclient_v2.Client(session=session)
    else:
        return keystoneclient_v3.Client(session=session)


def get_keystone_client(openrc_creds, verify=None):
    """
    Return authenticated keystoneclient and set auth_ref for service_catalog.

    :param openrc_creds: OpenStack RC credentials
    :type openrc_creds: dict
    :param verify: Control TLS certificate verification behaviour
    :type verify: any
    :returns: Authenticated keystoneclient
    :rtype: keystoneclient.v3.Client object
    """
    session = get_keystone_session(openrc_creds, verify=verify)
    client = get_keystone_session_client(session)
    keystone_creds = get_ks_creds(openrc_creds)
    if openrc_creds.get('API_VERSION', 2) == 2:
        auth = v2.Password(**keystone_creds)
    else:
        auth = v3.Password(**keystone_creds)
    # This populates the client.service_catalog
    client.auth_ref = auth.get_access(session)
    return client


def get_project_id(ks_client, project_name, api_version=2, domain_name=None):
    """Return project ID.

    :param ks_client: Authenticated keystoneclient
    :type ks_client: keystoneclient.v3.Client object
    :param project_name: Name of the project
    :type project_name: string
    :param api_version: API version number
    :type api_version: int
    :param domain_name: Name of the domain
    :type domain_name: string or None
    :returns: Project ID
    :rtype: string or None
    """
    domain_id = None
    if domain_name:
        domain_id = ks_client.domains.list(name=domain_name)[0].id
    all_projects = ks_client.projects.list(domain=domain_id)
    for p in all_projects:
        if p._info['name'] == project_name:
            return p._info['id']
    return None


def get_domain_id(ks_client, domain_name):
    """Return domain ID.

    :param ks_client: Authenticated keystoneclient
    :type ks_client: keystoneclient.v3.Client object
    :param domain_name: Name of the domain
    :type domain_name: string
    :returns: Domain ID
    :rtype: string or None
    """
    all_domains = ks_client.domains.list(name=domain_name)
    if all_domains:
        return all_domains[0].id
    return None


# Neutron Helpers
def get_gateway_uuids():
    """Return machine uuids for neutron-gateway(s).

    :returns: List of uuids
    :rtype: Iterator[str]
    """
    return juju_utils.get_machine_uuids_for_application('neutron-gateway')


def get_ovs_uuids():
    """Return machine uuids for neutron-openvswitch(s).

    :returns: List of uuids
    :rtype: Iterator[str]
    """
    return juju_utils.get_machine_uuids_for_application('neutron-openvswitch')


def get_ovn_uuids():
    """Provide machine uuids for OVN Chassis.

    :returns: List of uuids
    :rtype: Iterator[str]
    """
    return itertools.chain(
        juju_utils.get_machine_uuids_for_application('ovn-chassis'),
        juju_utils.get_machine_uuids_for_application('ovn-dedicated-chassis'),
    )


def dvr_enabled():
    """Check whether DVR is enabled in deployment.

    :returns: True when DVR is enabled, False otherwise
    :rtype: bool
    """
    try:
        return get_application_config_option('neutron-api', 'enable-dvr')
    except KeyError:
        return False


def ngw_present():
    """Check whether Neutron Gateway is present in deployment.

    :returns: True when Neutron Gateway is present, False otherwise
    :rtype: bool
    """
    try:
        model.get_application('neutron-gateway')
        return True
    except KeyError:
        pass
    return False


def ovn_present():
    """Check whether OVN is present in deployment.

    :returns: True when OVN is present, False otherwise
    :rtype: bool
    """
    app_presence = []
    for name in ('ovn-chassis', 'ovn-dedicated-chassis'):
        try:
            model.get_application(name)
            app_presence.append(True)
        except KeyError:
            app_presence.append(False)
    return any(app_presence)


BRIDGE_MAPPINGS = 'bridge-mappings'
NEW_STYLE_NETWORKING = 'physnet1:br-ex'


def deprecated_external_networking():
    """Determine whether deprecated external network mode is in use.

    :returns: True or False
    :rtype: boolean
    """
    bridge_mappings = None
    if dvr_enabled():
        bridge_mappings = get_application_config_option('neutron-openvswitch',
                                                        BRIDGE_MAPPINGS)
    elif ovn_present():
        return False
    else:
        bridge_mappings = get_application_config_option('neutron-gateway',
                                                        BRIDGE_MAPPINGS)

    if bridge_mappings == NEW_STYLE_NETWORKING:
        return False
    return True


def get_net_uuid(neutron_client, net_name):
    """Determine whether deprecated external network mode is in use.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param net_name: Network name
    :type net_name: string
    :returns: Network ID
    :rtype: string
    """
    network = neutron_client.list_networks(name=net_name)['networks'][0]
    return network['id']


def get_admin_net(neutron_client):
    """Return admin netowrk.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :returns: Admin network object
    :rtype: dict
    """
    for net in neutron_client.list_networks()['networks']:
        if net['name'].endswith('_admin_net'):
            return net


def add_interface_to_netplan(server_name, mac_address):
    """In guest server_name, add nic with mac_address to netplan.

    :param server_name: Hostname of instance
    :type server_name: string
    :param mac_address: mac address of nic to be added to netplan
    :type mac_address: string
    """
    if dvr_enabled():
        application_names = ('neutron-openvswitch',)
    elif ovn_present():
        # OVN chassis is a subordinate to nova-compute
        application_names = ('nova-compute', 'ovn-dedicated-chassis')
    else:
        application_names = ('neutron-gateway',)

    for app_name in application_names:
        unit_name = juju_utils.get_unit_name_from_host_name(
            server_name, app_name)
        if unit_name:
            break
    else:
        raise RuntimeError('Unable to find unit to run commands on.')
    run_cmd_nic = "ip -f link -br -o addr|grep {}".format(mac_address)
    interface = model.run_on_unit(unit_name, run_cmd_nic)
    interface = interface['Stdout'].split(' ')[0]

    run_cmd_netplan = """sudo egrep -iR '{}|{}$' /etc/netplan/
                        """.format(mac_address, interface)

    netplancfg = model.run_on_unit(unit_name, run_cmd_netplan)

    if (mac_address in str(netplancfg)) or (interface in str(netplancfg)):
        logging.warn("mac address {} or nic {} already exists in "
                     "/etc/netplan".format(mac_address, interface))
        return
    body_value = textwrap.dedent("""\
        network:
            ethernets:
                {0}:
                    dhcp4: false
                    dhcp6: true
                    optional: true
                    match:
                        macaddress: {1}
                    set-name: {0}
            version: 2
    """.format(interface, mac_address))
    logging.debug("plumb guest interface debug info:")
    logging.debug("body_value: {}\nunit_name: {}\ninterface: {}\nmac_address:"
                  "{}\nserver_name: {}".format(body_value, unit_name,
                                               interface, mac_address,
                                               server_name))
    for attempt in tenacity.Retrying(
            stop=tenacity.stop_after_attempt(3),
            wait=tenacity.wait_exponential(
            multiplier=1, min=2, max=10)):
        with attempt:
            with tempfile.NamedTemporaryFile(mode="w") as netplan_file:
                netplan_file.write(body_value)
                netplan_file.flush()
                model.scp_to_unit(
                    unit_name, netplan_file.name,
                    '/home/ubuntu/60-dataport.yaml', user="ubuntu")
            run_cmd_mv = "sudo mv /home/ubuntu/60-dataport.yaml /etc/netplan/"
            model.run_on_unit(unit_name, run_cmd_mv)
            model.run_on_unit(unit_name, "sudo netplan apply")


class OpenStackNetworkingTopology(enum.Enum):
    """OpenStack Charms Network Topologies."""

    ML2_OVS = 'ML2+OVS'
    ML2_OVS_DVR = 'ML2+OVS+DVR'
    ML2_OVS_DVR_SNAT = 'ML2+OVS+DVR, no dedicated GWs'
    ML2_OVN = 'ML2+OVN'


CharmedOpenStackNetworkingData = collections.namedtuple(
    'CharmedOpenStackNetworkingData',
    [
        'topology',
        'application_names',
        'unit_machine_ids',
        'port_config_key',
        'other_config',
    ])


def get_charm_networking_data(limit_gws=None):
    """Inspect Juju model, determine networking topology and return data.

    :param limit_gws: Limit the number of gateways that get a port attached
    :type limit_gws: Optional[int]
    :rtype: CharmedOpenStackNetworkingData[
                OpenStackNetworkingTopology,
                List[str],
                Iterator[str],
                str,
                Dict[str,str]]
    :returns: Named Tuple with networking data, example:
        CharmedOpenStackNetworkingData(
            OpenStackNetworkingTopology.ML2_OVN,
            ['ovn-chassis', 'ovn-dedicated-chassis'],
            ['machine-id-1', 'machine-id-2'],         # generator object
            'bridge-interface-mappings',
            {'ovn-bridge-mappings': 'physnet1:br-ex'})
    :raises: RuntimeError
    """
    # Initialize defaults, these will be amended to fit the reality of the
    # model in the checks below.
    topology = OpenStackNetworkingTopology.ML2_OVS
    other_config = {}
    port_config_key = (
        'data-port' if not deprecated_external_networking() else 'ext-port')
    unit_machine_ids = []
    application_names = []

    if dvr_enabled():
        if ngw_present():
            application_names = ['neutron-gateway', 'neutron-openvswitch']
            topology = OpenStackNetworkingTopology.ML2_OVS_DVR
        else:
            application_names = ['neutron-openvswitch']
            topology = OpenStackNetworkingTopology.ML2_OVS_DVR_SNAT
        unit_machine_ids = itertools.islice(
            itertools.chain(
                get_ovs_uuids(),
                get_gateway_uuids()),
            limit_gws)
    elif ngw_present():
        unit_machine_ids = itertools.islice(
            get_gateway_uuids(), limit_gws)
        application_names = ['neutron-gateway']
    elif ovn_present():
        topology = OpenStackNetworkingTopology.ML2_OVN
        unit_machine_ids = itertools.islice(get_ovn_uuids(), limit_gws)
        application_names = ['ovn-chassis']
        try:
            ovn_dc_name = 'ovn-dedicated-chassis'
            model.get_application(ovn_dc_name)
            application_names.append(ovn_dc_name)
        except KeyError:
            # ovn-dedicated-chassis not in deployment
            pass
        port_config_key = 'bridge-interface-mappings'
        other_config.update({'ovn-bridge-mappings': 'physnet1:br-ex'})
    else:
        raise RuntimeError('Unable to determine charm network topology.')

    return CharmedOpenStackNetworkingData(
        topology,
        application_names,
        unit_machine_ids,
        port_config_key,
        other_config)


def create_additional_port_for_machines(novaclient, neutronclient, net_id,
                                        unit_machine_ids,
                                        add_dataport_to_netplan=False):
    """Create additional port for machines for use with external networking.

    :param novaclient: Undercloud Authenticated novaclient.
    :type novaclient: novaclient.Client object
    :param neutronclient: Undercloud Authenticated neutronclient.
    :type neutronclient: neutronclient.Client object
    :param net_id: Network ID to create ports on.
    :type net_id: string
    :param unit_machine_ids: Juju provider specific machine IDs for which we
                             should add ports on.
    :type unit_machine_ids: Iterator[str]
    :param add_dataport_to_netplan: Whether the newly created port should be
                                    added to instance system configuration so
                                    that it is brought up on instance reboot.
    :type add_dataport_to_netplan: Optional[bool]
    :returns: List of MAC addresses for created ports.
    :rtype: List[str]
    :raises: RuntimeError
    """
    eligible_machines = 0
    for uuid in unit_machine_ids:
        eligible_machines += 1
        server = novaclient.servers.get(uuid)
        ext_port_name = "{}_ext-port".format(server.name)
        for port in neutronclient.list_ports(device_id=server.id)['ports']:
            if port['name'] == ext_port_name:
                logging.warning(
                    'Instance {} already has additional port, skipping.'
                    .format(server.id))
                break
        else:
            logging.info('Attaching additional port to instance ("{}"), '
                         'connected to net id: {}'
                         .format(uuid, net_id))
            body_value = {
                "port": {
                    "admin_state_up": True,
                    "name": ext_port_name,
                    "network_id": net_id,
                    "port_security_enabled": False,
                }
            }
            port = neutronclient.create_port(body=body_value)
            server.interface_attach(port_id=port['port']['id'],
                                    net_id=None, fixed_ip=None)
            if add_dataport_to_netplan:
                mac_address = get_mac_from_port(port, neutronclient)
                add_interface_to_netplan(server.name,
                                         mac_address=mac_address)
    if not eligible_machines:
        # NOTE: unit_machine_ids may be an iterator so testing it for contents
        # or length prior to iterating over it is futile.
        raise RuntimeError('Unable to determine UUIDs for machines to attach '
                           'external networking to.')

    # Retrieve the just created ports from Neutron so that we can provide our
    # caller with their MAC addresses.
    return [
        port['mac_address']
        for port in neutronclient.list_ports(network_id=net_id)['ports']
        if 'ext-port' in port['name']
    ]


def configure_networking_charms(networking_data, macs, use_juju_wait=True):
    """Configure external networking for networking charms.

    :param networking_data: Data on networking charm topology.
    :type networking_data: CharmedOpenStackNetworkingData
    :param macs: MAC addresses of ports for use with external networking.
    :type macs: Iterator[str]
    :param use_juju_wait: Whether to use juju wait to wait for the model to
        settle once the gateway has been configured. Default is True
    :type use_juju_wait: Optional[bool]
    """
    br_mac_fmt = 'br-ex:{}' if not deprecated_external_networking() else '{}'
    br_mac = [
        br_mac_fmt.format(mac)
        for mac in macs
    ]

    config = copy.deepcopy(networking_data.other_config)
    config.update({networking_data.port_config_key: ' '.join(sorted(br_mac))})

    for application_name in networking_data.application_names:
        logging.info('Setting {} on {}'.format(
            config, application_name))
        current_data_port = get_application_config_option(
            application_name,
            networking_data.port_config_key)

        # NOTE(lourot): in
        # https://github.com/openstack-charmers/openstack-bundles we have made
        # the conscious choice to use 'to-be-set' instead of 'null' for the
        # following reasons:
        # * With 'to-be-set' (rather than 'null') it is clearer for the reader
        #   that some action is required and the value can't just be left as
        #   is.
        # * Some of our tooling doesn't work with 'null', see
        #   https://github.com/openstack-charmers/openstack-bundles/pull/228
        # This nonetheless supports both by exiting early if the value is
        # neither 'null' nor 'to-be-set':
        if current_data_port and current_data_port != 'to-be-set':
            logging.info("Skip update of external network data port config."
                         "Config '{}' already set to value: {}".format(
                             networking_data.port_config_key,
                             current_data_port))
            return

        model.set_application_config(
            application_name,
            configuration=config)
    # NOTE(fnordahl): We are stuck with juju_wait until we figure out how
    # to deal with all the non ['active', 'idle', 'Unit is ready.']
    # workload/agent states and msgs that our mojo specs are exposed to.
    if use_juju_wait:
        juju_wait.wait(wait_for_workload=True, max_wait=2700)
    else:
        zaza.model.wait_for_agent_status()
        # TODO: shouldn't access get_charm_config() here as it relies on
        # ./tests/tests.yaml existing by default (regardless of the
        # fatal=False) ... it's not great design.
        test_config = zaza.charm_lifecycle.utils.get_charm_config(
            fatal=False)
        zaza.model.wait_for_application_states(
            states=test_config.get('target_deploy_status', {}))


def configure_gateway_ext_port(novaclient, neutronclient, net_id=None,
                               add_dataport_to_netplan=False,
                               limit_gws=None,
                               use_juju_wait=True):
    """Configure the neturong-gateway external port.

    :param novaclient: Authenticated novaclient
    :type novaclient: novaclient.Client object
    :param neutronclient: Authenticated neutronclient
    :type neutronclient: neutronclient.Client object
    :param net_id: Network ID
    :type net_id: string
    :param limit_gws: Limit the number of gateways that get a port attached
    :type limit_gws: Optional[int]
    :param use_juju_wait: Whether to use juju wait to wait for the model to
        settle once the gateway has been configured. Default is True
    :type use_juju_wait: boolean
    """
    networking_data = get_charm_networking_data(limit_gws=limit_gws)
    if networking_data.topology in (
            OpenStackNetworkingTopology.ML2_OVS_DVR,
            OpenStackNetworkingTopology.ML2_OVS_DVR_SNAT):
        # If dvr, do not attempt to persist nic in netplan
        # https://github.com/openstack-charmers/zaza-openstack-tests/issues/78
        add_dataport_to_netplan = False

    if not net_id:
        net_id = get_admin_net(neutronclient)['id']

    macs = create_additional_port_for_machines(
        novaclient, neutronclient, net_id, networking_data.unit_machine_ids,
        add_dataport_to_netplan)

    if macs:
        configure_networking_charms(
            networking_data, macs, use_juju_wait=use_juju_wait)


def configure_charmed_openstack_on_maas(network_config, limit_gws=None):
    """Configure networking charms for charm-based OVS config on MAAS provider.

    :param network_config: Network configuration as provided in environment.
    :type network_config: Dict[str]
    :param limit_gws: Limit the number of gateways that get a port attached
    :type limit_gws: Optional[int]
    """
    networking_data = get_charm_networking_data(limit_gws=limit_gws)
    macs = []
    machines = set()
    for mim in zaza.utilities.maas.get_macs_from_cidr(
            zaza.utilities.maas.get_maas_client_from_juju_cloud_data(
                zaza.model.get_cloud_data()),
            network_config['external_net_cidr'],
            link_mode=zaza.utilities.maas.LinkMode.LINK_UP):
        if mim.machine_id in machines:
            logging.warning("Machine {} has multiple unconfigured interfaces, "
                            "ignoring interface {} ({})."
                            .format(mim.machine_id, mim.ifname, mim.mac))
            continue
        logging.info("Machine {} selected {} ({}) for external networking."
                     .format(mim.machine_id, mim.ifname, mim.mac))
        machines.add(mim.machine_id)
        macs.append(mim.mac)

    if macs:
        configure_networking_charms(
            networking_data, macs, use_juju_wait=False)


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                reraise=True, retry=tenacity.retry_if_exception_type(KeyError))
def get_mac_from_port(port, neutronclient):
    """Get mac address from port, with tenacity due to openstack async.

    :param port: neutron port
    :type port: neutron port
    :param neutronclient: Authenticated neutronclient
    :type neutronclient: neutronclient.Client object
    :returns: mac address
    :rtype: string
    """
    logging.info("Trying to get mac address from port:"
                 "{}".format(port['port']['id']))
    refresh_port = neutronclient.show_port(port['port']['id'])
    return refresh_port['port']['mac_address']


def create_project_network(neutron_client, project_id, net_name=PRIVATE_NET,
                           shared=False, network_type='gre', domain=None):
    """Create the project network.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param project_id: Project ID
    :type project_id: string
    :param net_name: Network name
    :type net_name: string
    :param shared: The network should be shared between projects
    :type shared: boolean
    :param net_type: Network type: GRE, VXLAN, local, VLAN
    :type net_type: string
    :param domain_name: Name of the domain
    :type domain_name: string or None
    :returns: Network object
    :rtype: dict
    """
    networks = neutron_client.list_networks(name=net_name)
    if len(networks['networks']) == 0:
        logging.info('Creating network: %s',
                     net_name)
        network_msg = {
            'network': {
                'name': net_name,
                'shared': shared,
                'tenant_id': project_id,
            }
        }
        if network_type == 'vxlan':
            network_msg['network']['provider:segmentation_id'] = 1233
            network_msg['network']['provider:network_type'] = network_type
        network = neutron_client.create_network(network_msg)['network']
    else:
        logging.warning('Network %s already exists.', net_name)
        network = networks['networks'][0]
    return network


def create_provider_network(neutron_client, project_id, net_name=EXT_NET,
                            external=True, shared=False, network_type='flat',
                            vlan_id=None):
    """Create a provider network.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param project_id: Project ID
    :type project_id: string
    :param net_name: Network name
    :type net_name: string
    :param shared: The network should be external
    :type shared: boolean
    :param shared: The network should be shared between projects
    :type shared: boolean
    :param net_type: Network type: GRE, VXLAN, local, VLAN
    :type net_type: string
    :param net_name: VLAN ID
    :type net_name: string
    :returns: Network object
    :rtype: dict
    """
    networks = neutron_client.list_networks(name=net_name)
    if len(networks['networks']) == 0:
        logging.info('Creating %s %s network: %s', network_type,
                     'external' if external else 'provider', net_name)
        network_msg = {
            'name': net_name,
            'router:external': external,
            'shared': shared,
            'tenant_id': project_id,
            'provider:physical_network': 'physnet1',
            'provider:network_type': network_type,
        }

        if network_type == 'vlan':
            network_msg['provider:segmentation_id'] = int(vlan_id)
        network = neutron_client.create_network(
            {'network': network_msg})['network']
        logging.info('Network %s created: %s', net_name, network['id'])
    else:
        logging.warning('Network %s already exists.', net_name)
        network = networks['networks'][0]
    return network


def create_project_subnet(neutron_client, project_id, network, cidr, dhcp=True,
                          subnet_name=PRIVATE_NET_SUBNET, domain=None,
                          subnetpool=None, ip_version=4, prefix_len=24):
    """Create the project subnet.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param project_id: Project ID
    :type project_id: string
    :param network: Network object
    :type network: dict
    :param cidr: Network CIDR
    :type cidr: string
    :param dhcp: Run DHCP on this subnet
    :type dhcp: boolean
    :param subnet_name: Subnet name
    :type subnet_name: string
    :param domain_name: Name of the domain
    :type domain_name: string or None
    :param subnet_pool: Subnetpool object
    :type subnet_pool: dict or None
    :param ip_version: IP version: 4 or 6
    :type ip_version: int
    :param prefix_len: Prefix lenghths of subnets derived from subnet pools
    :type prefix_len: int
    :returns: Subnet object
    :rtype: dict
    """
    # Create subnet
    subnets = neutron_client.list_subnets(name=subnet_name)
    if len(subnets['subnets']) == 0:
        logging.info('Creating subnet')
        subnet_msg = {
            'subnet': {
                'name': subnet_name,
                'network_id': network['id'],
                'enable_dhcp': dhcp,
                'ip_version': ip_version,
                'tenant_id': project_id
            }
        }
        if subnetpool:
            subnet_msg['subnet']['subnetpool_id'] = subnetpool['id']
            subnet_msg['subnet']['prefixlen'] = prefix_len
        else:
            subnet_msg['subnet']['cidr'] = cidr
        subnet = neutron_client.create_subnet(subnet_msg)['subnet']
    else:
        logging.warning('Subnet %s already exists.', subnet_name)
        subnet = subnets['subnets'][0]
    return subnet


def create_provider_subnet(neutron_client, project_id, network,
                           subnet_name=EXT_NET_SUBNET,
                           default_gateway=None, cidr=None,
                           start_floating_ip=None, end_floating_ip=None,
                           dhcp=False):
    """Create the provider subnet.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param project_id: Project ID
    :type project_id: string
    :param network: Network object
    :type network: dict
    :param default_gateway: Deafault gateway IP address
    :type default_gateway: string
    :param subnet_name: Subnet name
    :type subnet_name: string
    :param cidr: Network CIDR
    :type cidr: string
    :param start_floating_ip: Start of floating IP range: IP address
    :type start_floating_ip: string or None
    :param end_floating_ip: End of floating IP range: IP address
    :type end_floating_ip: string or None
    :param dhcp: Run DHCP on this subnet
    :type dhcp: boolean
    :returns: Subnet object
    :rtype: dict
    """
    subnets = neutron_client.list_subnets(name=subnet_name)
    if len(subnets['subnets']) == 0:
        subnet_msg = {
            'name': subnet_name,
            'network_id': network['id'],
            'enable_dhcp': dhcp,
            'ip_version': 4,
            'tenant_id': project_id
        }

        if default_gateway:
            subnet_msg['gateway_ip'] = default_gateway
        if cidr:
            subnet_msg['cidr'] = cidr
        if (start_floating_ip and end_floating_ip):
            allocation_pool = {
                'start': start_floating_ip,
                'end': end_floating_ip,
            }
            subnet_msg['allocation_pools'] = [allocation_pool]

        logging.info('Creating new subnet')
        subnet = neutron_client.create_subnet({'subnet': subnet_msg})['subnet']
        logging.info('New subnet created: %s', subnet['id'])
    else:
        logging.warning('Subnet %s already exists.', subnet_name)
        subnet = subnets['subnets'][0]
    return subnet


def update_subnet_dns(neutron_client, subnet, dns_servers):
    """Update subnet DNS servers.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param subnet: Subnet object
    :type subnet: dict
    :param dns_servers: Comma separted list of IP addresses
    :type project_id: string
    """
    msg = {
        'subnet': {
            'dns_nameservers': dns_servers.split(',')
        }
    }
    logging.info('Updating dns_nameservers (%s) for subnet',
                 dns_servers)
    neutron_client.update_subnet(subnet['id'], msg)


def update_subnet_dhcp(neutron_client, subnet, enable_dhcp):
    """Update subnet DHCP status.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param subnet: Subnet object
    :type subnet: dict
    :param enable_dhcp: Whether DHCP should be enabled or not
    :type enable_dhcp: bool
    """
    msg = {
        'subnet': {
            'enable_dhcp': enable_dhcp,
        }
    }
    neutron_client.update_subnet(subnet['id'], msg)


def create_provider_router(neutron_client, project_id):
    """Create the provider router.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param project_id: Project ID
    :type project_id: string
    :returns: Router object
    :rtype: dict
    """
    routers = neutron_client.list_routers(name=PROVIDER_ROUTER)
    if len(routers['routers']) == 0:
        logging.info('Creating provider router for external network access')
        router_info = {
            'router': {
                'name': PROVIDER_ROUTER,
                'tenant_id': project_id
            }
        }
        router = neutron_client.create_router(router_info)['router']
        logging.info('New router created: %s', (router['id']))
    else:
        logging.warning('Router %s already exists.', (PROVIDER_ROUTER))
        router = routers['routers'][0]
    return router


def plug_extnet_into_router(neutron_client, router, network):
    """Add external interface to virtual router.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param router: Router object
    :type router: dict
    :param network: Network object
    :type network: dict
    """
    ports = neutron_client.list_ports(device_owner='network:router_gateway',
                                      network_id=network['id'])
    if len(ports['ports']) == 0:
        logging.info('Plugging router into ext_net')
        router = neutron_client.add_gateway_router(
            router=router['id'],
            body={'network_id': network['id']})
        logging.info('Router connected')
    else:
        logging.warning('Router already connected')


def plug_subnet_into_router(neutron_client, router, network, subnet):
    """Add subnet interface to virtual router.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param router: Router object
    :type router: dict
    :param network: Network object
    :type network: dict
    :param subnet: Subnet object
    :type subnet: dict
    """
    routers = neutron_client.list_routers(name=router)
    if len(routers['routers']) == 0:
        logging.error('Unable to locate provider router %s', router)
        sys.exit(1)
    else:
        # Check to see if subnet already plugged into router
        ports = neutron_client.list_ports(
            device_owner='network:router_interface',
            network_id=network['id'])
        if len(ports['ports']) == 0:
            logging.info('Adding interface from subnet to %s' % (router))
            router = routers['routers'][0]
            neutron_client.add_interface_router(router['id'],
                                                {'subnet_id': subnet['id']})
        else:
            logging.warning('Router already connected to subnet')


def create_address_scope(neutron_client, project_id, name, ip_version=4):
    """Create address scope.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param project_id: Project ID
    :type project_id: string
    :param name: Address scope name
    :type name: string
    :param ip_version: IP version: 4 or 6
    :type ip_version: int
    :returns: Address scope object
    :rtype: dict
    """
    address_scopes = neutron_client.list_address_scopes(name=name)
    if len(address_scopes['address_scopes']) == 0:
        logging.info('Creating {} address scope'.format(name))
        address_scope_info = {
            'address_scope': {
                'name': name,
                'shared': True,
                'ip_version': ip_version,
                'tenant_id': project_id,
            }
        }
        address_scope = neutron_client.create_address_scope(
            address_scope_info)['address_scope']
        logging.info('New address scope created: %s', (address_scope['id']))
    else:
        logging.warning('Address scope {} already exists.'.format(name))
        address_scope = address_scopes['address_scopes'][0]
    return address_scope


def create_subnetpool(neutron_client, project_id, name, subnetpool_prefix,
                      address_scope, shared=True):
    """Create subnet pool.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param project_id: Project ID
    :type project_id: string
    :param name: Subnet pool name
    :type name: string
    :param subnetpool_prefix: CIDR network
    :type subnetpool_prefix: string
    :param address_scope: Address scope object
    :type address_scope: dict
    :param shared: The subnet pool should be shared between projects
    :type shared: boolean
    :returns: Subnetpool object
    :rtype: dict
    """
    subnetpools = neutron_client.list_subnetpools(name=name)
    if len(subnetpools['subnetpools']) == 0:
        logging.info('Creating subnetpool: %s',
                     name)
        subnetpool_msg = {
            'subnetpool': {
                'name': name,
                'shared': shared,
                'tenant_id': project_id,
                'prefixes': [subnetpool_prefix],
                'address_scope_id': address_scope['id'],
            }
        }
        subnetpool = neutron_client.create_subnetpool(
            subnetpool_msg)['subnetpool']
    else:
        logging.warning('Network %s already exists.', name)
        subnetpool = subnetpools['subnetpools'][0]
    return subnetpool


def create_bgp_speaker(neutron_client, local_as=12345, ip_version=4,
                       name='bgp-speaker'):
    """Create BGP speaker.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param local_as: Autonomous system number of the OpenStack cloud
    :type local_as: int
    :param remote_as: Autonomous system number of the BGP peer
    :type local_as: int
    :param name: BGP speaker name
    :type name: string
    :returns: BGP speaker object
    :rtype: dict
    """
    bgp_speakers = neutron_client.list_bgp_speakers(name=name)
    if len(bgp_speakers['bgp_speakers']) == 0:
        logging.info('Creating BGP Speaker')
        bgp_speaker_msg = {
            'bgp_speaker': {
                'name': name,
                'local_as': local_as,
                'ip_version': ip_version,
            }
        }
        bgp_speaker = neutron_client.create_bgp_speaker(
            bgp_speaker_msg)['bgp_speaker']
    else:
        logging.warning('BGP Speaker %s already exists.', name)
        bgp_speaker = bgp_speakers['bgp_speakers'][0]
    return bgp_speaker


def add_network_to_bgp_speaker(neutron_client, bgp_speaker, network_name):
    """Advertise network on BGP Speaker.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param bpg_speaker: BGP speaker object
    :type bgp_speaker: dict
    :param network_name: Name of network to advertise
    :type network_name: string
    """
    network_id = get_net_uuid(neutron_client, network_name)
    # There is no direct way to determine which networks have already
    # been advertised. For example list_route_advertised_from_bgp_speaker shows
    # ext_net as FIP /32s.
    # Handle the expected exception if the route is already advertised
    try:
        logging.info('Advertising {} network on BGP Speaker {}'
                     .format(network_name, bgp_speaker['name']))
        neutron_client.add_network_to_bgp_speaker(bgp_speaker['id'],
                                                  {'network_id': network_id})
    except neutronexceptions.InternalServerError:
        logging.warning('{} network already advertised.'.format(network_name))


def create_bgp_peer(neutron_client, peer_application_name='quagga',
                    remote_as=10000, auth_type='none'):
    """Create BGP peer.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param peer_application_name: Application name of the BGP peer
    :type peer_application_name: string
    :param remote_as: Autonomous system number of the BGP peer
    :type local_as: int
    :param auth_type: BGP authentication type
    :type auth_type: string or None
    :returns: BGP peer object
    :rtype: dict
    """
    peer_unit = model.get_units(peer_application_name)[0]
    peer_ip = model.get_unit_public_address(peer_unit)
    bgp_peers = neutron_client.list_bgp_peers(name=peer_application_name)
    if len(bgp_peers['bgp_peers']) == 0:
        logging.info('Creating BGP Peer')
        bgp_peer_msg = {
            'bgp_peer': {
                'name': peer_application_name,
                'peer_ip': peer_ip,
                'remote_as': remote_as,
                'auth_type': auth_type,
            }
        }
        bgp_peer = neutron_client.create_bgp_peer(bgp_peer_msg)['bgp_peer']
    else:
        logging.warning('BGP Peer %s already exists.', peer_ip)
        bgp_peer = bgp_peers['bgp_peers'][0]
    return bgp_peer


def add_peer_to_bgp_speaker(neutron_client, bgp_speaker, bgp_peer):
    """Add BGP peer relationship to BGP speaker.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param bpg_speaker: BGP speaker object
    :type bgp_speaker: dict
    :param bpg_peer: BGP peer object
    :type bgp_peer: dict
    """
    # Handle the expected exception if the peer is already on the
    # speaker
    try:
        logging.info('Adding peer {} on BGP Speaker {}'
                     .format(bgp_peer['name'], bgp_speaker['name']))
        neutron_client.add_peer_to_bgp_speaker(bgp_speaker['id'],
                                               {'bgp_peer_id': bgp_peer['id']})
    except neutronexceptions.Conflict:
        logging.warning('{} peer already on BGP speaker.'
                        .format(bgp_peer['name']))


def add_neutron_secgroup_rules(neutron_client, project_id, custom_rules=[]):
    """Add neutron security group rules.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param project_id: Project ID
    :type project_id: string
    :param custom_rules: List of ``security_group_rule`` dicts to create
    :type custom_rules: list
    """
    secgroup = None
    for group in neutron_client.list_security_groups().get('security_groups'):
        if (group.get('name') == 'default' and
            (group.get('project_id') == project_id or
                (group.get('tenant_id') == project_id))):
            secgroup = group
    if not secgroup:
        raise Exception("Failed to find default security group")
    # Using presence of a 22 rule to indicate whether secgroup rules
    # have been added
    port_rules = [rule['port_range_min'] for rule in
                  secgroup.get('security_group_rules')]
    protocol_rules = [rule['protocol'] for rule in
                      secgroup.get('security_group_rules')]
    if 22 in port_rules:
        logging.warn('Security group rules for ssh already added')
    else:
        logging.info('Adding ssh security group rule')
        neutron_client.create_security_group_rule(
            {'security_group_rule':
                {'security_group_id': secgroup.get('id'),
                 'protocol': 'tcp',
                 'port_range_min': 22,
                 'port_range_max': 22,
                 'direction': 'ingress',
                 }
             })

    if 'icmp' in protocol_rules:
        logging.warn('Security group rules for ping already added')
    else:
        logging.info('Adding ping security group rule')
        neutron_client.create_security_group_rule(
            {'security_group_rule':
                {'security_group_id': secgroup.get('id'),
                 'protocol': 'icmp',
                 'direction': 'ingress',
                 }
             })

    for rule in custom_rules:
        rule_port = rule.get('port_range_min')
        if rule_port and int(rule_port) in port_rules:
            logging.warn('Custom security group for port {} appears to '
                         'already exist, skipping.'.format(rule_port))
        else:
            logging.info('Adding custom port {} security group rule'
                         .format(rule_port))
            rule.update({'security_group_id': secgroup.get('id')})
            neutron_client.create_security_group_rule(
                {'security_group_rule': rule})


def create_port(neutron_client, name, network_name):
    """Create port on network.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param name: Port name
    :type name: string
    :param network_name: Network name the port is on
    :type network_name: string
    :returns: Port object
    :rtype: dict
    """
    ports = neutron_client.list_ports(name=name)
    if len(ports['ports']) == 0:
        logging.info('Creating port: {}'.format(name))
        network_id = get_net_uuid(neutron_client, network_name)
        port_msg = {
            'port': {
                'name': name,
                'network_id': network_id,
            }
        }
        port = neutron_client.create_port(port_msg)['port']
    else:
        logging.debug('Port {} already exists.'.format(name))
        port = ports['ports'][0]

    return port


def create_floating_ip(neutron_client, network_name, port=None):
    """Create floating IP on network and optionally associate to a port.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param network_name: Name of external netowrk for FIPs
    :type network_name: string
    :param port: Port object
    :type port: dict
    :returns: Floating IP object
    :rtype: dict
    """
    floatingips = neutron_client.list_floatingips()
    if len(floatingips['floatingips']) > 0:
        if port:
            for floatingip in floatingips['floatingips']:
                if floatingip.get('port_id') == port['id']:
                    logging.debug('Floating IP with port, {}, already'
                                  'exists.'.format(port['name']))
                    return floatingip
        logging.warning('A floating IP already exists but ports do not match '
                        'Potentially creating more than one.')

    logging.info('Creating floatingip')
    network_id = get_net_uuid(neutron_client, network_name)
    floatingip_msg = {
        'floatingip': {
            'floating_network_id': network_id,
        }
    }
    if port:
        floatingip_msg['floatingip']['port_id'] = port['id']
    floatingip = neutron_client.create_floatingip(
        floatingip_msg)['floatingip']
    return floatingip


# Codename and package versions
def get_swift_codename(version):
    """Determine OpenStack codename that corresponds to swift version.

    :param version: Version of Swift
    :type version: string
    :returns: Codename for swift
    :rtype: string
    """
    return _get_special_codename(version, SWIFT_CODENAMES)


def get_ovn_codename(version):
    """Determine OpenStack codename that corresponds to OVN version.

    :param version: Version of OVN
    :type version: string
    :returns: Codename for OVN
    :rtype: string
    """
    return _get_special_codename(version, OVN_CODENAMES)


def _get_special_codename(version, codenames):
    found = [k for k, v in six.iteritems(codenames) if version in v]
    return found[0]


def get_os_code_info(package, pkg_version):
    """Determine OpenStack codename that corresponds to package version.

    :param package: Package name
    :type package: string
    :param pkg_version: Package version
    :type pkg_version: string
    :returns: Codename for package
    :rtype: string
    """
    # Remove epoch if it exists
    if ':' in pkg_version:
        pkg_version = pkg_version.split(':')[1:][0]
    if 'swift' in package:
        # Fully x.y.z match for swift versions
        match = re.match(r'^(\d+)\.(\d+)\.(\d+)', pkg_version)
    else:
        # x.y match only for 20XX.X
        # and ignore patch level for other packages
        match = re.match(r'^(\d+)\.(\d+)', pkg_version)

    if match:
        vers = match.group(0)
    # Generate a major version number for newer semantic
    # versions of openstack projects
    major_vers = vers.split('.')[0]
    if (package in PACKAGE_CODENAMES and
            major_vers in PACKAGE_CODENAMES[package]):
        return PACKAGE_CODENAMES[package][major_vers]
    else:
        # < Liberty co-ordinated project versions
        if 'swift' in package:
            return get_swift_codename(vers)
        elif 'ovn' in package:
            return get_ovn_codename(vers)
        else:
            return OPENSTACK_CODENAMES[vers]


def get_openstack_release(application, model_name=None):
    """Return the openstack release codename based on /etc/openstack-release.

    This will only return a codename if the openstack-release package is
    installed on the unit.

    :param application: Application name
    :type application: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: OpenStack release codename for application
    :rtype: string
    """
    versions = []
    units = model.get_units(application, model_name=model_name)
    for unit in units:
        cmd = 'cat /etc/openstack-release | grep OPENSTACK_CODENAME'
        try:
            out = juju_utils.remote_run(unit.entity_id, cmd,
                                        model_name=model_name)
        except model.CommandRunFailed:
            logging.debug('Fall back to version check for OpenStack codename')
        else:
            codename = out.split('=')[1].strip()
            versions.append(codename)
    if len(set(versions)) == 0:
        return None
    elif len(set(versions)) > 1:
        raise Exception('Unexpected mix of OpenStack releases for {}: {}',
                        application, versions)
    return versions[0]


def get_current_os_versions(deployed_applications, model_name=None):
    """Determine OpenStack codename of deployed applications.

    Initially, see if the openstack-release pkg is available and use it
    instead.

    If it isn't then it falls back to the existing method of checking the
    version of the package passed and then resolving the version from that
    using lookup tables.

    :param deployed_applications: List of deployed applications
    :type deployed_applications: list
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: List of aplication to codenames dictionaries
    :rtype: list
    """
    versions = {}
    for application in UPGRADE_SERVICES:
        if application['name'] not in deployed_applications:
            continue
        logging.info("looking at application: {}".format(application))

        codename = get_openstack_release(application['name'],
                                         model_name=model_name)
        if codename:
            versions[application['name']] = codename
        else:
            version = generic_utils.get_pkg_version(application['name'],
                                                    application['type']['pkg'],
                                                    model_name=model_name)
            versions[application['name']] = (
                get_os_code_info(application['type']['pkg'], version))
    return versions


def get_application_config_keys(application):
    """Return application configuration keys.

    :param application: Name of application
    :type application: string
    :returns: List of aplication configuration keys
    :rtype: list
    """
    application_config = model.get_application_config(application)
    return list(application_config.keys())


def get_current_os_release_pair(application='keystone'):
    """Return OpenStack Release pair name.

    :param application: Name of application
    :type application: string
    :returns: Name of the OpenStack release pair
    :rtype: str
    :raises: exceptions.ApplicationNotFound
    :raises: exceptions.SeriesNotFound
    :raises: exceptions.OSVersionNotFound
    """
    try:
        machine = list(juju_utils.get_machines_for_application(application))[0]
    except IndexError:
        raise exceptions.ApplicationNotFound(application)

    series = juju_utils.get_machine_series(machine)
    if not series:
        raise exceptions.SeriesNotFound()

    os_version = get_current_os_versions([application]).get(application)
    if not os_version:
        raise exceptions.OSVersionNotFound()

    return '{}_{}'.format(series, os_version)


def get_os_release(release_pair=None, application='keystone'):
    """Return index of release in OPENSTACK_RELEASES_PAIRS.

    :param release_pair: OpenStack release pair eg 'focal_ussuri'
    :type release_pair: string
    :param application: Name of application to derive release pair from.
    :type application: string
    :returns: Index of the release
    :rtype: int
    :raises: exceptions.ReleasePairNotFound
    """
    if release_pair is None:
        release_pair = get_current_os_release_pair(application=application)
    try:
        index = OPENSTACK_RELEASES_PAIRS.index(release_pair)
    except ValueError:
        msg = 'Release pair: {} not found in {}'.format(
            release_pair,
            OPENSTACK_RELEASES_PAIRS
        )
        raise exceptions.ReleasePairNotFound(msg)
    return index


def get_application_config_option(application, option, model_name=None):
    """Return application configuration.

    :param application: Name of application
    :type application: string
    :param option: Specific configuration option
    :type option: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Value of configuration option
    :rtype: Configuration option value type
    """
    application_config = model.get_application_config(
        application,
        model_name=model_name)
    try:
        return application_config.get(option).get('value')
    except AttributeError:
        return None


def get_undercloud_auth():
    """Get undercloud OpenStack authentication settings from environment.

    :returns: Dictionary of authentication settings
    :rtype: dict
    """
    os_auth_url = os.environ.get('OS_AUTH_URL')
    if os_auth_url:
        api_version = os_auth_url.split('/')[-1].replace('v', '')
    else:
        logging.error('Missing OS authentication setting: OS_AUTH_URL')
        raise exceptions.MissingOSAthenticationException(
            'One or more OpenStack authentication variables could '
            'be found in the environment. Please export the OS_* '
            'settings into the environment.')

    logging.info('AUTH_URL: {}, api_ver: {}'.format(os_auth_url, api_version))

    if api_version == '2.0':
        # V2
        logging.info('Using keystone API V2 for undercloud auth')
        auth_settings = {
            'OS_AUTH_URL': os.environ.get('OS_AUTH_URL'),
            'OS_TENANT_NAME': os.environ.get('OS_TENANT_NAME'),
            'OS_USERNAME': os.environ.get('OS_USERNAME'),
            'OS_PASSWORD': os.environ.get('OS_PASSWORD'),
            'OS_REGION_NAME': os.environ.get('OS_REGION_NAME'),
            'API_VERSION': 2,
        }
    elif api_version >= '3':
        # V3 or later
        logging.info('Using keystone API V3 (or later) for undercloud auth')
        domain = os.environ.get('OS_DOMAIN_NAME')
        auth_settings = {
            'OS_AUTH_URL': os.environ.get('OS_AUTH_URL'),
            'OS_USERNAME': os.environ.get('OS_USERNAME'),
            'OS_PASSWORD': os.environ.get('OS_PASSWORD'),
            'OS_REGION_NAME': os.environ.get('OS_REGION_NAME'),
            'API_VERSION': 3,
        }
        if domain:
            auth_settings['OS_DOMAIN_NAME'] = domain
        else:
            auth_settings['OS_USER_DOMAIN_NAME'] = (
                os.environ.get('OS_USER_DOMAIN_NAME'))
            auth_settings['OS_PROJECT_NAME'] = (
                os.environ.get('OS_PROJECT_NAME'))
            auth_settings['OS_PROJECT_DOMAIN_NAME'] = (
                os.environ.get('OS_PROJECT_DOMAIN_NAME'))
            os_project_id = os.environ.get('OS_PROJECT_ID')
            if os_project_id is not None:
                auth_settings['OS_PROJECT_ID'] = os_project_id

    _os_cacert = os.environ.get('OS_CACERT')
    if _os_cacert:
        auth_settings.update({'OS_CACERT': _os_cacert})

    # Validate settings
    for key, settings in list(auth_settings.items()):
        if settings is None:
            logging.error('Missing OS authentication setting: {}'
                          ''.format(key))
            raise exceptions.MissingOSAthenticationException(
                'One or more OpenStack authentication variables could '
                'be found in the environment. Please export the OS_* '
                'settings into the environment.')

    return auth_settings


# OpenStack Client helpers
def get_keystone_ip(model_name=None):
    """Return the IP address to use when communicating with keystone api.

    If there are multiple VIP addresses specified in the 'vip' option for the
    keystone unit, then ONLY the first one is returned.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: IP address
    :rtype: str
    """
    vip_option = get_application_config_option(
        'keystone',
        'vip',
        model_name=model_name)
    if vip_option:
        # strip the option, splits on whitespace and return the first one.
        return vip_option.strip().split()[0]
    unit = model.get_units('keystone', model_name=model_name)[0]
    return model.get_unit_public_address(unit)


def get_keystone_api_version(model_name=None):
    """Return the keystone api version.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Keystone's api version
    :rtype: int
    """
    os_version = get_current_os_versions(
        'keystone',
        model_name=model_name)['keystone']
    api_version = get_application_config_option(
        'keystone',
        'preferred-api-version',
        model_name=model_name)
    if CompareOpenStack(os_version) >= 'queens':
        api_version = 3
    elif api_version is None:
        api_version = 2

    return int(api_version)


def get_overcloud_auth(address=None, model_name=None):
    """Get overcloud OpenStack authentication from the environment.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Dictionary of authentication settings
    :rtype: dict
    """
    if juju_utils.is_k8s_deployment():
        return _get_overcloud_auth_k8s(address=address, model_name=None)
    else:
        return _get_overcloud_auth(address=address, model_name=None)


def _get_overcloud_auth_k8s(address=None, model_name=None):
    """Get overcloud OpenStack authentication from the k8s environment.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Dictionary of authentication settings
    :rtype: dict
    """
    logging.warning('Assuming http keystone endpoint')
    transport = 'http'
    port = 5000
    if not address:
        address = zaza.model.get_status()[
            'applications']['keystone'].public_address
    address = network_utils.format_addr(address)

    logging.info('Retrieving admin password from keystone')
    action = zaza.model.run_action_on_leader(
        'keystone',
        'get-admin-password',
        action_params={}
    )
    password = action.data['results']['password']

    # V3 or later
    logging.info('Using keystone API V3 (or later) for overcloud auth')
    auth_settings = {
        'OS_AUTH_URL': '%s://%s:%i/v3' % (transport, address, port),
        'OS_USERNAME': 'admin',
        'OS_PASSWORD': password,
        'OS_REGION_NAME': 'RegionOne',
        'OS_DOMAIN_NAME': 'admin_domain',
        'OS_USER_DOMAIN_NAME': 'admin_domain',
        'OS_PROJECT_NAME': 'admin',
        'OS_PROJECT_DOMAIN_NAME': 'admin_domain',
        'API_VERSION': 3,
    }
    return auth_settings


def _get_overcloud_auth(address=None, model_name=None):
    """Get overcloud OpenStack authentication from the environment.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Dictionary of authentication settings
    :rtype: dict
    """
    tls_rid = model.get_relation_id('keystone', 'vault',
                                    model_name=model_name,
                                    remote_interface_name='certificates')
    ssl_config = get_application_config_option(
        'keystone',
        'ssl_cert',
        model_name=model_name)
    if tls_rid or ssl_config:
        transport = 'https'
        port = 35357
    else:
        transport = 'http'
        port = 5000

    if not address:
        address = get_keystone_ip(model_name=model_name)
    address = network_utils.format_addr(address)

    password = juju_utils.leader_get(
        'keystone',
        'admin_passwd',
        model_name=model_name)

    if get_keystone_api_version(model_name=model_name) == 2:
        # V2 Explicitly, or None when charm does not possess the config key
        logging.info('Using keystone API V2 for overcloud auth')
        auth_settings = {
            'OS_AUTH_URL': '%s://%s:%i/v2.0' % (transport, address, port),
            'OS_TENANT_NAME': 'admin',
            'OS_USERNAME': 'admin',
            'OS_PASSWORD': password,
            'OS_REGION_NAME': 'RegionOne',
            'API_VERSION': 2,
        }
    else:
        # V3 or later
        logging.info('Using keystone API V3 (or later) for overcloud auth')
        auth_settings = {
            'OS_AUTH_URL': '%s://%s:%i/v3' % (transport, address, port),
            'OS_USERNAME': 'admin',
            'OS_PASSWORD': password,
            'OS_REGION_NAME': 'RegionOne',
            'OS_DOMAIN_NAME': 'admin_domain',
            'OS_USER_DOMAIN_NAME': 'admin_domain',
            'OS_PROJECT_NAME': 'admin',
            'OS_PROJECT_DOMAIN_NAME': 'admin_domain',
            'API_VERSION': 3,
        }
    local_ca_cert = get_remote_ca_cert_file('keystone', model_name=model_name)
    if local_ca_cert:
        auth_settings['OS_CACERT'] = local_ca_cert

    return auth_settings


async def _async_get_remote_ca_cert_file_candidates(application,
                                                    model_name=None):
    """Return a list of possible remote CA file names.

    :param application: Name of application to examine.
    :type application: str
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: List of paths to possible ca files.
    :rtype: List[str]
    """
    cert_files = []
    for _provider in CERT_PROVIDERS:
        tls_rid = await model.async_get_relation_id(
            application,
            _provider,
            model_name=model_name,
            remote_interface_name='certificates')
        if tls_rid:
            cert_files.append(
                REMOTE_CERT_DIR + '/' + CACERT_FILENAME_FORMAT.format(
                    _provider))
    cert_files.append(KEYSTONE_REMOTE_CACERT)
    return cert_files

_get_remote_ca_cert_file_candidates = zaza.model.sync_wrapper(
    _async_get_remote_ca_cert_file_candidates)


def get_remote_ca_cert_file(application, model_name=None):
    """Collect CA certificate from application.

    :param application: Name of application to collect file from.
    :type application: str
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Path to cafile
    :rtype: str
    """
    unit = model.get_first_unit_name(application, model_name=model_name)
    local_cert_file = None
    cert_files = _get_remote_ca_cert_file_candidates(
        application,
        model_name=model_name)
    for cert_file in cert_files:
        _local_cert_file = get_cacert_absolute_path(
            os.path.basename(cert_file))
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as _tmp_ca:
            try:
                model.scp_from_unit(
                    unit,
                    cert_file,
                    _tmp_ca.name)
            except JujuError:
                continue
            # ensure that the path to put the local cacert in actually exists.
            # The assumption that 'tests/' exists for, say, mojo is false.
            # Needed due to:
            # commit: 537473ad3addeaa3d1e4e2d0fd556aeaa4018eb2
            _dir = os.path.dirname(_local_cert_file)
            if not os.path.exists(_dir):
                os.makedirs(_dir)
            shutil.move(_tmp_ca.name, _local_cert_file)
            os.chmod(_local_cert_file, 0o644)
            local_cert_file = _local_cert_file
            break
    return local_cert_file


def get_urllib_opener():
    """Create a urllib opener taking into account proxy settings.

    Using urllib.request.urlopen will automatically handle proxies so none
    of this function is needed except we are currently specifying proxies
    via TEST_HTTP_PROXY rather than http_proxy so a ProxyHandler is needed
    explicitly stating the proxies.

    :returns: An opener which opens URLs via BaseHandlers chained together
    :rtype: urllib.request.OpenerDirector
    """
    deploy_env = deployment_env.get_deployment_context()
    http_proxy = deploy_env.get('TEST_HTTP_PROXY')
    logging.debug('TEST_HTTP_PROXY: {}'.format(http_proxy))

    if http_proxy:
        handler = urllib.request.ProxyHandler({'http': http_proxy})
    else:
        handler = urllib.request.HTTPHandler()
    return urllib.request.build_opener(handler)


def get_images_by_name(glance, image_name):
    """Get all glance image objects with the given name.

    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :param image_name: Name of image
    :type image_name: str

    :returns: List of glance images
    :rtype: [glanceclient.v2.image, ...]
    """
    return [i for i in glance.images.list() if image_name == i.name]


def get_volumes_by_name(cinder, volume_name):
    """Get all cinder volume objects with the given name.

    :param cinder: Authenticated cinderclient
    :type cinder: cinderclient.Client
    :param image_name: Name of volume
    :type image_name: str
    :returns: List of cinder volumes
    :rtype: List[cinderclient.v3.volume, ...]
    """
    return [i for i in cinder.volumes.list() if volume_name == i.name]


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                reraise=True,
                retry=tenacity.retry_if_exception_type(urllib.error.URLError))
def find_cirros_image(arch):
    """Return the url for the latest cirros image for the given architecture.

    :param arch: aarch64, arm, i386, amd64, x86_64 etc
    :type arch: str
    :returns: URL for latest cirros image
    :rtype: str
    """
    http_connection_timeout = 10  # seconds
    opener = get_urllib_opener()
    f = opener.open(CIRROS_RELEASE_URL, timeout=http_connection_timeout)
    version = f.read().strip().decode()
    cirros_img = 'cirros-{}-{}-disk.img'.format(version, arch)
    return '{}/{}/{}'.format(CIRROS_IMAGE_URL, version, cirros_img)


def find_ubuntu_image(release, arch):
    """Return url for image."""
    loc_str = UBUNTU_IMAGE_URLS.get(release) or UBUNTU_IMAGE_URLS['default']
    return loc_str.format(release=release, arch=arch)


def download_image(image_url, target_file):
    """Download the image from the given url to the specified file.

    :param image_url: URL to download image from
    :type image_url: str
    :param target_file: Local file to save image to
    :type target_file: str
    """
    opener = get_urllib_opener()
    urllib.request.install_opener(opener)
    urllib.request.urlretrieve(image_url, target_file)


def _resource_reaches_status(resource, resource_id,
                             expected_status='available',
                             msg='resource',
                             resource_attribute='status'):
    """Wait for an openstack resources status to reach an expected status.

       Wait for an openstack resources status to reach an expected status
       within a specified time. Useful to confirm that nova instances, cinder
       vols, snapshots, glance images, heat stacks and other resources
       eventually reach the expected status.

    :param resource: pointer to os resource type, ex: heat_client.stacks
    :type resource: str
    :param resource_id: unique id for the openstack resource
    :type resource_id: str
    :param expected_status: status to expect resource to reach
    :type expected_status: str
    :param msg: text to identify purpose in logging
    :type msg: str
    :param resource_attribute: Resource attribute to check against
    :type resource_attribute: str
    :raises: AssertionError
    """
    resource_status = getattr(resource.get(resource_id), resource_attribute)
    logging.info("{}: resource {} in {} state, waiting for {}".format(
        msg, resource_id, resource_status, expected_status))
    assert resource_status == expected_status


def resource_reaches_status(resource,
                            resource_id,
                            expected_status='available',
                            msg='resource',
                            resource_attribute='status',
                            wait_exponential_multiplier=1,
                            wait_iteration_max_time=60,
                            stop_after_attempt=8,
                            ):
    """Wait for an openstack resources status to reach an expected status.

       Wait for an openstack resources status to reach an expected status
       within a specified time. Useful to confirm that nova instances, cinder
       vols, snapshots, glance images, heat stacks and other resources
       eventually reach the expected status.

    :param resource: pointer to os resource type, ex: heat_client.stacks
    :type resource: str
    :param resource_id: unique id for the openstack resource
    :type resource_id: str
    :param expected_status: status to expect resource to reach
    :type expected_status: str
    :param msg: text to identify purpose in logging
    :type msg: str
    :param resource_attribute: Resource attribute to check against
    :type resource_attribute: str
    :param wait_exponential_multiplier: Wait 2^x * wait_exponential_multiplier
                                        seconds between each retry
    :type wait_exponential_multiplier: int
    :param wait_iteration_max_time: Wait a max of wait_iteration_max_time
                                    between retries.
    :type wait_iteration_max_time: int
    :param stop_after_attempt: Stop after stop_after_attempt retires.
    :type stop_after_attempt: int
    :raises: AssertionError
    """
    retryer = tenacity.Retrying(
        wait=tenacity.wait_exponential(
            multiplier=wait_exponential_multiplier,
            max=wait_iteration_max_time),
        reraise=True,
        stop=tenacity.stop_after_attempt(stop_after_attempt))
    retryer(
        _resource_reaches_status,
        resource,
        resource_id,
        expected_status,
        msg,
        resource_attribute)


def _resource_removed(resource, resource_id, msg="resource"):
    """Wait for an openstack resource to no longer be present.

    :param resource: pointer to os resource type, ex: heat_client.stacks
    :type resource: str
    :param resource_id: unique id for the openstack resource
    :type resource_id: str
    :param msg: text to identify purpose in logging
    :type msg: str
    :raises: AssertionError
    """
    matching = [r for r in resource.list() if r.id == resource_id]
    logging.debug("{}: resource {} still present".format(msg, resource_id))
    assert len(matching) == 0


def resource_removed(resource,
                     resource_id,
                     msg='resource',
                     wait_exponential_multiplier=1,
                     wait_iteration_max_time=60,
                     stop_after_attempt=8):
    """Wait for an openstack resource to no longer be present.

    :param resource: pointer to os resource type, ex: heat_client.stacks
    :type resource: str
    :param resource_id: unique id for the openstack resource
    :type resource_id: str
    :param msg: text to identify purpose in logging
    :type msg: str
    :param wait_exponential_multiplier: Wait 2^x * wait_exponential_multiplier
                                        seconds between each retry
    :type wait_exponential_multiplier: int
    :param wait_iteration_max_time: Wait a max of wait_iteration_max_time
                                    between retries.
    :type wait_iteration_max_time: int
    :param stop_after_attempt: Stop after stop_after_attempt retires.
    :type stop_after_attempt: int
    :raises: AssertionError
    """
    retryer = tenacity.Retrying(
        wait=tenacity.wait_exponential(
            multiplier=wait_exponential_multiplier,
            max=wait_iteration_max_time),
        reraise=True,
        stop=tenacity.stop_after_attempt(stop_after_attempt))
    retryer(
        _resource_removed,
        resource,
        resource_id,
        msg)


def delete_resource(resource, resource_id, msg="resource"):
    """Delete an openstack resource.

    Delete an openstack resource, such as one instance, keypair,
    image, volume, stack, etc., and confirm deletion within max wait time.

    :param resource: pointer to os resource type, ex:glance_client.images
    :type resource: str
    :param resource_id: unique name or id for the openstack resource
    :type resource_id: str
    :param msg: text to identify purpose in logging
    :type msg: str
    """
    logging.debug('Deleting OpenStack resource '
                  '{} ({})'.format(resource_id, msg))
    resource.delete(resource_id)
    resource_removed(resource, resource_id, msg)


def delete_image(glance, img_id):
    """Delete the given image from glance.

    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :param img_id: unique name or id for the openstack resource
    :type img_id: str
    """
    delete_resource(glance.images, img_id, msg="glance image")


def delete_volume(cinder, vol_id):
    """Delete the given volume from cinder.

    :param cinder: Authenticated cinderclient
    :type cinder: cinderclient.Client
    :param vol_id: unique name or id for the openstack resource
    :type vol_id: str
    """
    delete_resource(cinder.volumes, vol_id, msg="deleting cinder volume")


def delete_volume_backup(cinder, vol_backup_id):
    """Delete the given volume from cinder.

    :param cinder: Authenticated cinderclient
    :type cinder: cinderclient.Client
    :param vol_backup_id: unique name or id for the openstack resource
    :type vol_backup_id: str
    """
    delete_resource(cinder.backups, vol_backup_id,
                    msg="deleting cinder volume backup")


def upload_image_to_glance(glance, local_path, image_name, disk_format='qcow2',
                           visibility='public', container_format='bare',
                           backend=None, force_import=False):
    """Upload the given image to glance and apply the given label.

    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :param local_path: Path to local image
    :type local_path: str
    :param image_name: The label to give the image in glance
    :type image_name: str
    :param disk_format: The of the underlying disk image.
    :type disk_format: str
    :param visibility: Who can access image
    :type visibility: str (public, private, shared or community)
    :param container_format: Whether the virtual machine image is in a file
                             format that also contains metadata about the
                             actual virtual machine.
    :type container_format: str
    :param force_import: Force the use of glance image import
        instead of direct upload
    :type force_import: boolean
    :returns: glance image pointer
    :rtype: glanceclient.common.utils.RequestIdProxy
    """
    # Create glance image
    image = glance.images.create(
        name=image_name,
        disk_format=disk_format,
        visibility=visibility,
        container_format=container_format)

    if force_import:
        logging.info('Forcing image import')
        glance.images.stage(image.id, open(local_path, 'rb'))
        glance.images.image_import(
            image.id, method='glance-direct', backend=backend)
    else:
        glance.images.upload(
            image.id, open(local_path, 'rb'), backend=backend)

    resource_reaches_status(
        glance.images,
        image.id,
        expected_status='active',
        msg='Image status wait')

    return image


def create_image(glance, image_url, image_name, image_cache_dir=None, tags=[],
                 properties=None, backend=None, disk_format='qcow2',
                 visibility='public', container_format='bare',
                 force_import=False):
    """Download the image and upload it to glance.

    Download an image from image_url and upload it to glance labelling
    the image with image_url, validate and return a resource pointer.

    :param glance: Authenticated glanceclient
    :type glance: glanceclient.Client
    :param image_url: URL to download image from
    :type image_url: str
    :param image_name: display name for new image
    :type image_name: str
    :param image_cache_dir: Directory to store image in before uploading. If it
        is not passed, or is None, then a tmp directory is used.
    :type image_cache_dir: Option[str, None]
    :param tags: Tags to add to image
    :type tags: list of str
    :param properties: Properties and values to add to image
    :type properties: dict
    :param force_import: Force the use of glance image import
        instead of direct upload
    :type force_import: boolean
    :returns: glance image pointer
    :rtype: glanceclient.common.utils.RequestIdProxy
    """
    if image_cache_dir is None:
        image_cache_dir = tempfile.gettempdir()

    logging.debug('Creating glance cirros image '
                  '({})...'.format(image_name))

    img_name = os.path.basename(urllib.parse.urlparse(image_url).path)
    local_path = os.path.join(image_cache_dir, img_name)

    if not os.path.exists(local_path):
        logging.info('Downloading {} ...'.format(image_url))
        download_image(image_url, local_path)
    else:
        logging.info('Cached image found at {} - Skipping download'.format(
            local_path))

    image = upload_image_to_glance(
        glance, local_path, image_name, backend=backend,
        disk_format=disk_format, visibility=visibility,
        container_format=container_format, force_import=force_import)
    for tag in tags:
        result = glance.image_tags.update(image.id, tag)
        logging.debug(
            'applying tag to image: glance.image_tags.update({}, {}) = {}'
            .format(image.id, tags, result))

    logging.info("Setting image properties: {}".format(properties))
    if properties:
        result = glance.images.update(image.id, **properties)

    return image


def create_volume(cinder, size, name=None, image=None):
    """Create cinder volume.

    :param cinder: Authenticated cinderclient
    :type cinder: cinder.Client
    :param size: Size of the volume
    :type size: int
    :param name: display name for new volume
    :type name: Option[str, None]
    :param image: Image to download to volume.
    :type image: Option[str, None]
    :returns: cinder volume pointer
    :rtype: cinderclient.common.utils.RequestIdProxy
    """
    logging.debug('Creating volume')
    # Create volume
    volume = cinder.volumes.create(
        size=size,
        name=name,
        imageRef=image)

    resource_reaches_status(
        cinder.volumes,
        volume.id,
        expected_status='available',
        msg='Volume status wait')
    return volume


def attach_volume(nova, volume_id, instance_id):
    """Attach a cinder volume to a nova instance.

    :param nova: Authenticated nova client
    :type nova: novaclient.v2.client.Client
    :param volume_id: the id of the volume to attach
    :type volume_id: str
    :param instance_id: the id of the instance to attach the volume to
    :type instance_id: str
    :returns: nova volume pointer
    :rtype: novaclient.v2.volumes.Volume
    """
    logging.info(
        'Attaching volume {} to instance {}'.format(
            volume_id, instance_id
        )
    )
    return nova.volumes.create_server_volume(server_id=instance_id,
                                             volume_id=volume_id,
                                             device='/dev/vdx')


def detach_volume(nova, volume_id, instance_id):
    """Detach a cinder volume to a nova instance.

    :param nova: Authenticated nova client
    :type nova: novaclient.v2.client.Client
    :param volume_id: the id of the volume to attach
    :type volume_id: str
    :param instance_id: the id of the instance to attach the volume to
    :type instance_id: str
    :returns: nova volume pointer
    :rtype: novaclient.v2.volumes.Volume
    """
    logging.info(
        'Detaching volume {} from instance {}'.format(
            volume_id, instance_id
        )
    )
    return nova.volumes.delete_server_volume(server_id=instance_id,
                                             volume_id=volume_id)


def failover_cinder_volume_host(cinder, backend_name='cinder-ceph',
                                target_backend_id='ceph',
                                target_status='disabled',
                                target_replication_status='failed-over'):
    """Failover Cinder volume host with replication enabled.

    :param cinder: Authenticated cinderclient
    :type cinder: cinder.Client
    :param backend_name: Cinder volume backend name with
                         replication enabled.
    :type backend_name: str
    :param target_backend_id: Failover target Cinder backend id.
    :type target_backend_id: str
    :param target_status: Target Cinder volume status after failover.
    :type target_status: str
    :param target_replication_status: Target Cinder volume replication
                                      status after failover.
    :type target_replication_status: str
    :raises: AssertionError
    """
    host = 'cinder@{}'.format(backend_name)
    logging.info('Failover Cinder volume host %s to backend_id %s',
                 host, target_backend_id)
    cinder.services.failover_host(host=host, backend_id=target_backend_id)
    for attempt in tenacity.Retrying(
            retry=tenacity.retry_if_exception_type(AssertionError),
            stop=tenacity.stop_after_attempt(10),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=10)):
        with attempt:
            svc = cinder.services.list(host=host, binary='cinder-volume')[0]
            assert svc.status == target_status
            assert svc.replication_status == target_replication_status


def create_volume_backup(cinder, volume_id, name=None):
    """Create cinder volume backup.

    :param cinder: Authenticated cinderclient
    :type cinder: cinder.Client
    :param volume_id: the source volume's id for backup
    :type volume_id: str
    :param name: display name for new volume backup
    :type name: Option[str, None]
    :returns: cinder volume backup pointer
    :rtype: cinderclient.common.utils.RequestIdProxy
    """
    logging.debug('Creating volume backup')
    # Create volume backup
    volume_backup = cinder.backups.create(
        volume_id,
        name=name)

    resource_reaches_status(
        cinder.backups,
        volume_backup.id,
        expected_status='available',
        msg='Volume status wait')
    return volume_backup


def get_volume_backup_metadata(cinder, backup_id):
    """Get cinder volume backup record.

    :param cinder: Authenticated cinderclient
    :type cinder: cinder.Client
    :param backup_id: the source backup id
    """
    logging.debug('Request volume backup record')
    # Request volume backup record
    volume_backup_record = cinder.backups.export_record(
        backup_id)

    return volume_backup_record


def create_ssh_key(nova_client, keypair_name, replace=False):
    """Create ssh key.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    :param keypair_name: Label to apply to keypair in OpenStack.
    :type keypair_name: str
    :param replace: Whether to replace the existing keypair if it already
                    exists.
    :type replace: str
    :returns: The keypair
    :rtype: nova.objects.keypair
    """
    existing_keys = nova_client.keypairs.findall(name=keypair_name)
    if existing_keys:
        if replace:
            logging.info('Deleting key(s) {}'.format(keypair_name))
            for key in existing_keys:
                nova_client.keypairs.delete(key)
        else:
            return existing_keys[0]
    logging.info('Creating key %s' % (keypair_name))
    return nova_client.keypairs.create(name=keypair_name)


def get_private_key_file(keypair_name):
    """Location of the file containing the private key with the given label.

    :param keypair_name: Label of keypair in OpenStack.
    :type keypair_name: str
    :returns: Path to file containing key
    :rtype: str
    """
    key = os.environ.get("TEST_PRIVKEY")
    if key:
        return key

    tmp_dir = deployment_env.get_tmpdir()
    return '{}/id_rsa_{}'.format(tmp_dir, keypair_name)


def write_private_key(keypair_name, key):
    """Store supplied private key in file.

    :param keypair_name: Label of keypair in OpenStack.
    :type keypair_name: str
    :param key: PEM Encoded Private Key
    :type key: str
    """
    # Create the key file with mode 0o600 to allow the developer to pass it to
    # the `ssh` command without getting a "bad permissions" error.
    stored_umask = os.umask(0o177)
    try:
        with open(get_private_key_file(keypair_name), 'w') as key_file:
            key_file.write(key)
    finally:
        os.umask(stored_umask)


def get_private_key(keypair_name):
    """Return private key.

    :param keypair_name: Label of keypair in OpenStack.
    :type keypair_name: str
    :returns: PEM Encoded Private Key
    :rtype: str
    """
    key_file = get_private_key_file(keypair_name)
    if not os.path.isfile(key_file):
        return None
    with open(key_file, 'r') as key_file:
        key = key_file.read()
    return key


def get_public_key(nova_client, keypair_name):
    """Return public key from OpenStack.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    :param keypair_name: Label of keypair in OpenStack.
    :type keypair_name: str
    :returns: OpenSSH Encoded Public Key
    :rtype: str or None
    """
    keys = nova_client.keypairs.findall(name=keypair_name)
    if keys:
        return keys[0].public_key
    else:
        return None


def valid_key_exists(nova_client, keypair_name):
    """Check if a valid public/private keypair exists for keypair_name.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    :param keypair_name: Label of keypair in OpenStack.
    :type keypair_name: str
    """
    pub_key = get_public_key(nova_client, keypair_name)
    priv_key = get_private_key(keypair_name)
    if not all([pub_key, priv_key]):
        return False
    return cert.is_keys_valid(pub_key, priv_key)


def get_ports_from_device_id(neutron_client, device_id):
    """Return the ports associated with a given device.

    :param neutron_client: Authenticated neutronclient
    :type neutron_client: neutronclient.Client object
    :param device_id: The id of the device to look for
    :type device_id: str
    :returns: List of port objects
    :rtype: []
    """
    ports = []
    for _port in neutron_client.list_ports().get('ports'):
        if device_id in _port.get('device_id'):
            ports.append(_port)
    return ports


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=120),
                reraise=True, stop=tenacity.stop_after_delay(1800))
def cloud_init_complete(nova_client, vm_id, bootstring):
    """Wait for cloud init to complete on the given vm.

    If cloud init does not complete in the alloted time then
    exceptions.CloudInitIncomplete is raised.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    :param vm_id,: The id of the server to monitor.
    :type vm_id: str (uuid)
    :param bootstring: The string to look for in the console output that will
                       indicate cloud init is complete.
    :type bootstring: str
    :raises: exceptions.CloudInitIncomplete
    """
    instance = nova_client.servers.find(id=vm_id)
    console_log = instance.get_console_output()
    if bootstring not in console_log:
        raise exceptions.CloudInitIncomplete(
            "'{}' not found in console log: {}"
            .format(bootstring, console_log))


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                reraise=True, stop=tenacity.stop_after_attempt(16))
def ping_response(ip):
    """Wait for ping to respond on the given IP.

    :param ip: IP address to ping
    :type ip: str
    :raises: subprocess.CalledProcessError
    """
    cmd = ['ping', '-c', '1', '-W', '1', ip]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   check=True)


def ssh_test(username, ip, vm_name, password=None, privkey=None, retry=True):
    """SSH to given ip using supplied credentials.

    :param username: Username to connect with
    :type username: str
    :param ip: IP address to ssh to.
    :type ip: str
    :param vm_name: Name of VM.
    :type vm_name: str
    :param password: Password to authenticate with. If supplied it is used
                     rather than privkey.
    :type password: str
    :param privkey: Private key to authenticate with. If a password is
                    supplied it is used rather than the private key.
    :type privkey: str
    :param retry: If True, retry a few times if an exception is raised in the
                  process, e.g. on connection failure.
    :type retry: boolean
    :raises: exceptions.SSHFailed
    """
    def verify(stdin, stdout, stderr):
        return_string = stdout.readlines()[0].strip()

        if return_string == vm_name:
            logging.info('SSH to %s(%s) successful' % (vm_name, ip))
        else:
            logging.info('SSH to %s(%s) failed (%s != %s)' % (vm_name, ip,
                                                              return_string,
                                                              vm_name))
            raise exceptions.SSHFailed()

    # NOTE(lourot): paramiko.SSHClient().connect() calls read_all() which can
    # raise an EOFError, see
    # * https://docs.paramiko.org/en/stable/api/packet.html
    # * https://github.com/paramiko/paramiko/issues/925
    # So retrying a few times makes sense.
    for attempt in tenacity.Retrying(
            stop=tenacity.stop_after_attempt(3 if retry else 1),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
            reraise=True):
        with attempt:
            ssh_command(username, ip, vm_name, 'uname -n',
                        password=password, privkey=privkey, verify=verify)


def ssh_command(username,
                ip,
                vm_name,
                command,
                password=None,
                privkey=None,
                verify=None):
    """SSH to given ip using supplied credentials.

    :param username: Username to connect with
    :type username: str
    :param ip: IP address to ssh to.
    :type ip: str
    :param vm_name: Name of VM.
    :type vm_name: str
    :param command: What command to run on the remote host
    :type command: str
    :param password: Password to authenticate with. If supplied it is used
                     rather than privkey.
    :type password: str
    :param privkey: Private key to authenticate with. If a password is
                    supplied it is used rather than the private key.
    :type privkey: str
    :param verify: A callable to verify the command output with
    :type verify: callable
    :raises: exceptions.SSHFailed
    """
    logging.info('Attempting to ssh to %s(%s)' % (vm_name, ip))
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if password:
        ssh.connect(ip, username=username, password=password)
    else:
        key = paramiko.RSAKey.from_private_key(io.StringIO(privkey))
        ssh.connect(ip, username=username, password=None, pkey=key)
    logging.info("Running {} on {}".format(command, vm_name))
    stdin, stdout, stderr = ssh.exec_command(command)
    if verify and callable(verify):
        try:
            verify(stdin, stdout, stderr)
        except Exception as e:
            raise e
        finally:
            ssh.close()


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=0.01),
                reraise=True, stop=tenacity.stop_after_delay(60) |
                tenacity.stop_after_attempt(100))
def neutron_agent_appears(neutron_client, binary):
    """Wait for Neutron agent to appear and return agent_id.

    :param neutron_client: Neutron client
    :type neutron_client: Pointer to Neutron client object
    :param binary: Name of agent we want to appear
    :type binary: str
    :returns: result set from Neutron list_agents call
    :rtype: dict
    :raises: exceptions.NeutronAgentMissing
    """
    result = neutron_client.list_agents(binary=binary)
    for agent in result.get('agents', []):
        agent_id = agent.get('id', None)
        if agent_id:
            break
    else:
        raise exceptions.NeutronAgentMissing(
            'no agents for binary "{}"'.format(binary))
    return result


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=0.01),
                reraise=True,
                stop=tenacity.stop_after_delay(60) |
                tenacity.stop_after_attempt(100))
def neutron_bgp_speaker_appears_on_agent(neutron_client, agent_id):
    """Wait for Neutron BGP speaker to appear on agent.

    :param neutron_client: Neutron client
    :type neutron_client: Pointer to Neutron client object
    :param agent_id: Neutron agent UUID
    :type agent_id: str
    :param speaker_id: Neutron BGP speaker UUID
    :type speaker_id: str
    :returns: result set from Neutron list_bgp_speaker_on_dragent call
    :rtype: dict
    :raises: exceptions.NeutronBGPSpeakerMissing
    """
    result = neutron_client.list_bgp_speaker_on_dragent(agent_id)
    for bgp_speaker in result.get('bgp_speakers', []):
        bgp_speaker_id = bgp_speaker.get('id', None)
        if bgp_speaker_id:
            break
    else:
        raise exceptions.NeutronBGPSpeakerMissing(
            'No BGP Speaker appeared on agent "{}"'
            ''.format(agent_id))
    return result


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                reraise=True, stop=tenacity.stop_after_attempt(80))
def wait_for_server_migration(nova_client, vm_name, original_hypervisor):
    """Wait for guest to migrate to a different hypervisor.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    :param vm_name: Name of guest to monitor
    :type vm_name: str
    :param original_hypervisor: Name of hypervisor that was hosting guest
                                prior to migration.
    :type original_hypervisor: str
    :raises: exceptions.NovaGuestMigrationFailed
    """
    server = nova_client.servers.find(name=vm_name)
    current_hypervisor = getattr(server, 'OS-EXT-SRV-ATTR:host')
    logging.info('{} is on {} in state {}'.format(
        vm_name,
        current_hypervisor,
        server.status))
    if original_hypervisor == current_hypervisor or server.status != 'ACTIVE':
        raise exceptions.NovaGuestMigrationFailed(
            'Migration of {} away from {} timed out or failed'.format(
                vm_name,
                original_hypervisor))
    else:
        logging.info('SUCCESS {} has migrated to {}'.format(
            vm_name,
            current_hypervisor))


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                reraise=True, stop=tenacity.stop_after_attempt(80),
                retry=tenacity.retry_if_exception_type(
                    exceptions.NovaGuestRestartFailed))
def wait_for_server_update_and_active(nova_client, vm_name,
                                      original_updatetime):
    """Wait for guests metadata to be updated and for status to become active.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    :param vm_name: Name of guest to monitor
    :type vm_name: str
    :param original_updatetime: The time the metadata was previously updated.
    :type original_updatetime: datetime
    :raises: exceptions.NovaGuestMigrationFailed
    """
    server = nova_client.servers.find(name=vm_name)
    current_updatetime = datetime.datetime.strptime(
        server.updated,
        "%Y-%m-%dT%H:%M:%SZ")
    if current_updatetime <= original_updatetime or server.status != 'ACTIVE':
        logging.info('{} Updated: {} Satus: {})'.format(
            vm_name,
            current_updatetime,
            server.status))
        raise exceptions.NovaGuestRestartFailed(
            'Restart of {} after crash failed'.format(vm_name))
    else:
        logging.info('SUCCESS {} has restarted'.format(vm_name))


def enable_all_nova_services(nova_client):
    """Enable all nova services.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    """
    for svc in nova_client.services.list():
        if svc.status == 'disabled':
            logging.info("Enabling {} on {}".format(svc.binary, svc.host))
            nova_client.services.enable(svc.host, svc.binary)


def get_hypervisor_for_guest(nova_client, guest_name):
    """Return the name of the hypervisor hosting a guest.

    :param nova_client: Authenticated nova client
    :type nova_client: novaclient.v2.client.Client
    :param vm_name: Name of guest to loohup
    :type vm_name: str
    """
    logging.info('Finding hosting hypervisor')
    server = nova_client.servers.find(name=guest_name)
    return getattr(server, 'OS-EXT-SRV-ATTR:host')


def get_keystone_session_from_relation(client_app,
                                       identity_app='keystone',
                                       relation_name='identity-service',
                                       scope='PROJECT',
                                       verify=None,
                                       model_name=None):
    """Extract credentials information from a relation & return a session.

    :param client_app: Name of application receiving credentials.
    :type client_app: string
    :param identity_app: Name of application providing credentials.
    :type identity_app: string
    :param relation_name: Name of relation between applications.
    :type relation_name: string
    :param scope: Authentication scope: PROJECT or DOMAIN
    :type scope: string
    :param verify: Control TLS certificate verification behaviour
    :type verify: any (True  - use system certs,
                       False - do not verify,
                       None  - defer to requests library to find certs,
                       str   - path to a CA cert bundle)
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Keystone session object
    :rtype: keystoneauth1.session.Session object
    """
    relation = juju_utils.get_relation_from_unit(
        client_app,
        identity_app,
        relation_name,
        model_name=model_name)

    api_version = int(relation.get('api_version', 2))
    creds = get_overcloud_auth(model_name=model_name)
    creds['OS_USERNAME'] = relation['service_username']
    creds['OS_PASSWORD'] = relation['service_password']
    creds['OS_PROJECT_NAME'] = relation['service_tenant']
    creds['OS_TENANT_NAME'] = relation['service_tenant']
    if api_version == 3:
        creds['OS_DOMAIN_NAME'] = relation['service_domain']
        creds['OS_USER_DOMAIN_NAME'] = relation['service_domain']
        creds['OS_PROJECT_DOMAIN_NAME'] = relation['service_domain']

    return get_keystone_session(creds, scope=scope, verify=verify)


def get_cli_auth_args(keystone_client):
    """Generate openstack CLI arguments for cloud authentication.

    :returns: string of required cli arguments for authentication
    :rtype: str
    """
    overcloud_auth = get_overcloud_auth()
    overcloud_auth.update(
        {
            "OS_DOMAIN_ID": get_domain_id(
                keystone_client, domain_name="admin_domain"
            ),
            "OS_TENANT_ID": get_project_id(
                keystone_client,
                project_name="admin",
                domain_name="admin_domain",
            ),
            "OS_TENANT_NAME": "admin",
        }
    )

    _required_keys = [
        "OS_AUTH_URL",
        "OS_USERNAME",
        "OS_PASSWORD",
        "OS_REGION_NAME",
        "OS_DOMAIN_ID",
        "OS_TENANT_ID",
        "OS_TENANT_NAME",
    ]

    params = []
    for os_key in _required_keys:
        params.append(
            "--{}={}".format(
                os_key.lower().replace("_", "-"),
                overcloud_auth[os_key],
            )
        )
    return " ".join(params)
