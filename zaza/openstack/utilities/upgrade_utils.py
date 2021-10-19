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

"""Collection of functions to support upgrade testing."""

import itertools
import logging
import re

import zaza.model
import zaza.utilities.juju
from zaza.openstack.utilities.os_versions import (
    OPENSTACK_CODENAMES,
    UBUNTU_OPENSTACK_RELEASE,
    OPENSTACK_RELEASES_PAIRS,
)

"""
The below upgrade order is surfaced in end-user documentation. Any change to
it should be accompanied by an update to the OpenStack Charms Deployment Guide
for both charm upgrades and payload upgrades:
- source/upgrade-charms.rst#upgrade-order
- source/upgrade-openstack.rst#openstack_upgrade_order
"""
SERVICE_GROUPS = (
    ('Database Services', ['percona-cluster', 'mysql-innodb-cluster']),
    ('Stateful Services', ['rabbitmq-server', 'ceph-mon']),
    ('Core Identity', ['keystone']),
    ('Control Plane', [
        'aodh', 'barbican', 'ceilometer', 'ceph-fs',
        'ceph-radosgw', 'cinder', 'designate',
        'designate-bind', 'glance', 'gnocchi', 'heat', 'manila',
        'manila-generic', 'neutron-api', 'neutron-gateway', 'ovn-central',
        'placement', 'nova-cloud-controller', 'openstack-dashboard']),
    ('Data Plane', [
        'nova-compute', 'ceph-osd',
        'swift-proxy', 'swift-storage']))

UPGRADE_EXCLUDE_LIST = ['rabbitmq-server', 'percona-cluster']


def get_upgrade_candidates(model_name=None, filters=None):
    """Extract list of apps from model that can be upgraded.

    :param model_name: Name of model to query.
    :type model_name: str
    :param filters: List of filter functions to apply
    :type filters: List[fn]
    :returns: List of application that can have their payload upgraded.
    :rtype: Dict[str, Dict[str, ANY]]
    """
    if filters is None:
        filters = []
    status = zaza.model.get_status(model_name=model_name)
    candidates = {}
    for app, app_config in status.applications.items():
        if _include_app(app, app_config, filters, model_name=model_name):
            candidates[app] = app_config
    return candidates


def _include_app(app, app_config, filters, model_name=None):
    for filt in filters:
        if filt(app, app_config, model_name=model_name):
            return False
    return True


def _filter_subordinates(app, app_config, model_name=None):
    if app_config.get("subordinate-to"):
        logging.warning(
            "Excluding {} from upgrade, it is a subordinate".format(app))
        return True
    return False


def _filter_openstack_upgrade_list(app, app_config, model_name=None):
    charm_name = extract_charm_name_from_url(app_config['charm'])
    if app in UPGRADE_EXCLUDE_LIST or charm_name in UPGRADE_EXCLUDE_LIST:
        print("Excluding {} from upgrade, on the exclude list".format(app))
        logging.warning(
            "Excluding {} from upgrade, on the exclude list".format(app))
        return True
    return False


def _filter_non_openstack_services(app, app_config, model_name=None):
    charm_options = zaza.model.get_application_config(
        app, model_name=model_name).keys()
    src_options = ['openstack-origin', 'source']
    if not [x for x in src_options if x in charm_options]:
        logging.warning(
            "Excluding {} from upgrade, no src option".format(app))
        return True
    return False


def _apply_extra_filters(filters, extra_filters):
    if extra_filters:
        if isinstance(extra_filters, list):
            filters.extend(extra_filters)
        elif callable(extra_filters):
            filters.append(extra_filters)
        else:
            raise RuntimeError(
                "extra_filters should be a list of "
                "callables")
    return filters


def _filter_easyrsa(app, app_config, model_name=None):
    charm_name = extract_charm_name_from_url(app_config['charm'])
    if "easyrsa" in charm_name:
        logging.warn("Skipping upgrade of easyrsa Bug #1850121")
        return True
    return False


def _filter_etcd(app, app_config, model_name=None):
    charm_name = extract_charm_name_from_url(app_config['charm'])
    if "etcd" in charm_name:
        logging.warn("Skipping upgrade of easyrsa Bug #1850124")
        return True
    return False


def _filter_memcached(app, app_config, model_name=None):
    charm_name = extract_charm_name_from_url(app_config['charm'])
    if "memcached" in charm_name:
        logging.warn("Skipping upgrade of memcached charm")
        return True
    return False


def get_upgrade_groups(model_name=None, extra_filters=None):
    """Place apps in the model into their upgrade groups.

    Place apps in the model into their upgrade groups. If an app is deployed
    but is not in SERVICE_GROUPS then it is placed in a sweep_up group.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Dict of group lists keyed on group name.
    :rtype: collections.OrderedDict
    """
    filters = [
        _filter_subordinates,
        _filter_openstack_upgrade_list,
        _filter_non_openstack_services,
    ]
    filters = _apply_extra_filters(filters, extra_filters)
    apps_in_model = get_upgrade_candidates(
        model_name=model_name,
        filters=filters)

    return _build_service_groups(apps_in_model)


def get_series_upgrade_groups(model_name=None, extra_filters=None):
    """Place apps in the model into their upgrade groups.

    Place apps in the model into their upgrade groups. If an app is deployed
    but is not in SERVICE_GROUPS then it is placed in a sweep_up group.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: List of tuples(group name, applications)
    :rtype: List[Tuple[str, Dict[str, ANY]]]
    """
    filters = [_filter_subordinates]
    filters = _apply_extra_filters(filters, extra_filters)
    apps_in_model = get_upgrade_candidates(
        model_name=model_name,
        filters=filters)

    return _build_service_groups(apps_in_model)


def get_charm_upgrade_groups(model_name=None, extra_filters=None):
    """Place apps in the model into their upgrade groups for a charm upgrade.

    Place apps in the model into their upgrade groups. If an app is deployed
    but is not in SERVICE_GROUPS then it is placed in a sweep_up group.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Dict of group lists keyed on group name.
    :rtype: collections.OrderedDict
    """
    filters = _apply_extra_filters([], extra_filters)
    apps_in_model = get_upgrade_candidates(
        model_name=model_name,
        filters=filters)

    return _build_service_groups(apps_in_model)


def _build_service_groups(applications):
    groups = []
    for phase_name, charms in SERVICE_GROUPS:
        group = []
        for app, app_config in applications.items():
            charm_name = extract_charm_name_from_url(app_config['charm'])
            if charm_name in charms:
                group.append(app)
        groups.append((phase_name, group))

    # collect all the values into a list, and then a lookup hash
    values = list(itertools.chain(*(ls for _, ls in groups)))
    vhash = {v: 1 for v in values}
    sweep_up = [app for app in applications if app not in vhash]
    groups.append(('sweep_up', sweep_up))
    for name, group in groups:
        group.sort()
    return groups


def extract_charm_name_from_url(charm_url):
    """Extract the charm name from the charm url.

    E.g. Extract 'heat' from local:bionic/heat-12

    :param charm_url: Name of model to query.
    :type charm_url: str
    :returns: Charm name
    :rtype: str
    """
    charm_name = re.sub(r'-[0-9]+$', '', charm_url.split('/')[-1])
    return charm_name.split(':')[-1]


def get_all_principal_applications(model_name=None):
    """Return a list of all the prinical applications in the model.

    :param model_name: Optional model name
    :type model_name: Optional[str]
    :returns: List of principal application names
    :rtype: List[str]
    """
    status = zaza.utilities.juju.get_full_juju_status(model_name=model_name)
    return [application for application in status.applications.keys()
            if not status.applications.get(application)['subordinate-to']]


def get_lowest_openstack_version(current_versions):
    """Get the lowest OpenStack version from the list of current versions.

    :param current_versions: The list of versions
    :type current_versions: List[str]
    :returns: the lowest version currently installed.
    :rtype: str
    """
    lowest_version = 'zebra'
    for svc in current_versions.keys():
        if current_versions[svc] < lowest_version:
            lowest_version = current_versions[svc]
    return lowest_version


def determine_next_openstack_release(release):
    """Determine the next release after the one passed as a str.

    The returned value is a tuple of the form: ('2020.1', 'ussuri')

    :param release: the release to use as the base
    :type release: str
    :returns: the release tuple immediately after the current one.
    :rtype: Tuple[str, str]
    :raises: KeyError if the current release doesn't actually exist
    """
    old_index = list(OPENSTACK_CODENAMES.values()).index(release)
    new_index = old_index + 1
    return list(OPENSTACK_CODENAMES.items())[new_index]


def determine_new_source(ubuntu_version, current_source, new_release,
                         single_increment=True):
    """Determine the new source/openstack-origin value  based on new release.

    This takes the ubuntu_version and the current_source (in the form of
    'distro' or 'cloud:xenial-mitaka') and either converts it to a new source,
    or returns None if the new_release will match the current_source (i.e. it's
    already at the right release), or it's simply not possible.

    If single_increment is set, then the returned source will only be returned
    if the new_release is one more than the release in the current source.

    :param ubuntu_version: the ubuntu version that the app is installed on.
    :type ubuntu_version: str
    :param current_source: a source in the form of 'distro' or
        'cloud:xenial-mitaka'
    :type current_source: str
    :param new_release: a new OpenStack version codename. e.g. 'stein'
    :type new_release: str
    :param single_increment: If True, only allow single increment upgrade.
    :type single_increment: boolean
    :returns: The new source in the form of 'cloud:bionic-train' or None if not
        possible
    :rtype: Optional[str]
    :raises: KeyError if any of the strings don't correspond to known values.
    """
    logging.warn("determine_new_source: locals: %s", locals())
    if current_source == 'distro':
        # convert to a ubuntu-openstack pair
        current_source = "cloud:{}-{}".format(
            ubuntu_version, UBUNTU_OPENSTACK_RELEASE[ubuntu_version])
    # strip out the current openstack version
    if ':' not in current_source:
        current_source = "cloud:{}-{}".format(ubuntu_version, current_source)
    pair = current_source.split(':')[1]
    u_version, os_version = pair.split('-', 2)
    if u_version != ubuntu_version:
        logging.warn("determine_new_source: ubuntu_versions don't match: "
                     "%s != %s" % (ubuntu_version, u_version))
        return None
    # determine versions
    openstack_codenames = list(OPENSTACK_CODENAMES.values())
    old_index = openstack_codenames.index(os_version)
    try:
        new_os_version = openstack_codenames[old_index + 1]
    except IndexError:
        logging.warn("determine_new_source: no OpenStack version after "
                     "'%s'" % os_version)
        return None
    if single_increment and new_release != new_os_version:
        logging.warn("determine_new_source: requested version '%s' not a "
                     "single increment from '%s' which is '%s'" % (
                         new_release, os_version, new_os_version))
        return None
    # now check that there is a combination of u_version-new_os_version
    new_pair = "{}_{}".format(u_version, new_os_version)
    if new_pair not in OPENSTACK_RELEASES_PAIRS:
        logging.warn("determine_new_source: now release pair candidate for "
                     " combination cloud:%s-%s" % (u_version, new_os_version))
        return None
    return "cloud:{}-{}".format(u_version, new_os_version)
