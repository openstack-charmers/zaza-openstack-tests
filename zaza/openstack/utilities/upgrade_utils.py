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
import re
import logging
import collections
import zaza.model


SERVICE_GROUPS = collections.OrderedDict([
    ('Core Identity', ['keystone']),
    ('Control Plane', [
        'aodh', 'barbican', 'ceilometer', 'ceph-mon', 'ceph-fs',
        'ceph-radosgw', 'cinder', 'designate',
        'designate-bind', 'glance', 'gnocchi', 'heat', 'manila',
        'manila-generic', 'neutron-api', 'neutron-gateway', 'placement',
        'nova-cloud-controller', 'openstack-dashboard']),
    ('Data Plane', [
        'nova-compute', 'ceph-osd', 'swift-proxy', 'swift-storage'])
])

UPGRADE_EXCLUDE_LIST = ['rabbitmq-server', 'percona-cluster']


def get_upgrade_candidates(model_name=None):
    """Extract list of apps from model that can be upgraded.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: List of application that can have their payload upgraded.
    :rtype: []
    """
    status = zaza.model.get_status(model_name=model_name)
    candidates = {}
    for app, app_config in status.applications.items():
        # Filter out subordinates
        if app_config.get("subordinate-to"):
            logging.warning(
                "Excluding {} from upgrade, it is a subordinate".format(app))
            continue

        # Filter out charms on the naughty list
        charm_name = extract_charm_name_from_url(app_config['charm'])
        if app in UPGRADE_EXCLUDE_LIST or charm_name in UPGRADE_EXCLUDE_LIST:
            logging.warning(
                "Excluding {} from upgrade, on the exclude list".format(app))
            continue

        # Filter out charms that have no source option
        charm_options = zaza.model.get_application_config(
            app, model_name=model_name).keys()
        src_options = ['openstack-origin', 'source']
        if not [x for x in src_options if x in charm_options]:
            logging.warning(
                "Excluding {} from upgrade, no src option".format(app))
            continue

        candidates[app] = app_config
    return candidates


def get_upgrade_groups(model_name=None):
    """Place apps in the model into their upgrade groups.

    Place apps in the model into their upgrade groups. If an app is deployed
    but is not in SERVICE_GROUPS then it is placed in a sweep_up group.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Dict of group lists keyed on group name.
    :rtype: collections.OrderedDict
    """
    apps_in_model = get_upgrade_candidates(model_name=model_name)

    groups = collections.OrderedDict()
    for phase_name, charms in SERVICE_GROUPS.items():
        group = []
        for app, app_config in apps_in_model.items():
            charm_name = extract_charm_name_from_url(app_config['charm'])
            if charm_name in charms:
                group.append(app)
        groups[phase_name] = group

    sweep_up = []
    for app in apps_in_model:
        if not (app in [a for group in groups.values() for a in group]):
            sweep_up.append(app)

    groups['sweep_up'] = sweep_up
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
