#!/usr/bin/env python3

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
"""Module for interacting with juju."""
import os
from pathlib import Path
import yaml

from zaza import (
    model,
    controller,
)
from zaza.openstack.utilities import generic as generic_utils


def get_application_status(application=None, unit=None, model_name=None):
    """Return the juju status for an application.

    :param application: Application name
    :type application: string
    :param unit: Specific unit
    :type unit: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Juju status output for an application
    :rtype: dict
    """
    status = get_full_juju_status()

    if unit and not application:
        application = unit.split("/")[0]

    if application:
        status = status.applications.get(application)
    if unit:
        status = status.get("units").get(unit)
    return status


def get_cloud_configs(cloud=None):
    """Get cloud configuration from local clouds.yaml.

    libjuju does not yet have cloud information implemented.
    Use libjuju as soon as possible.

    :param cloud: Name of specific cloud
    :type remote_cmd: string
    :returns: Dictionary of cloud configuration
    :rtype: dict
    """
    home = str(Path.home())
    cloud_config = os.path.join(home, ".local", "share", "juju", "clouds.yaml")
    if cloud:
        return generic_utils.get_yaml_config(cloud_config)["clouds"].get(cloud)
    else:
        return generic_utils.get_yaml_config(cloud_config)


def get_full_juju_status(model_name=None):
    """Return the full juju status output.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Full juju status output
    :rtype: dict
    """
    status = model.get_status(model_name=model_name)
    return status


def get_machines_for_application(application, model_name=None):
    """Return machines for a given application.

    :param application: Application name
    :type application: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: machines for an application
    :rtype: Iterator[str]
    """
    status = get_application_status(application, model_name=model_name)
    if not status:
        return

    # libjuju juju status no longer has units for subordinate charms
    # Use the application it is subordinate-to to find machines
    if status.get("units") is None and status.get("subordinate-to"):
        status = get_application_status(status.get("subordinate-to")[0],
                                        model_name=model_name)

    for unit in status.get("units").keys():
        yield status.get("units").get(unit).get("machine")


def get_unit_name_from_host_name(host_name, application, model_name=None):
    """Return the juju unit name corresponding to a hostname.

    :param host_name: Host name to map to unit name.
    :type host_name: string
    :param application: Application name
    :type application: string
    :param model_name: Name of model to query.
    :type model_name: str
    """
    # Assume that a juju managed hostname always ends in the machine number.
    machine_number = host_name.split('-')[-1]
    unit_names = [
        u.entity_id
        for u in model.get_units(application_name=application,
                                 model_name=model_name)
        if int(u.data['machine-id']) == int(machine_number)]
    return unit_names[0]


def get_machine_status(machine, key=None, model_name=None):
    """Return the juju status for a machine.

    :param machine: Machine number
    :type machine: string
    :param key: Key option requested
    :type key: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Juju status output for a machine
    :rtype: dict
    """
    status = get_full_juju_status(model_name=model_name)
    status = status.machines.get(machine)
    if key:
        status = status.get(key)
    return status


def get_machine_series(machine, model_name=None):
    """Return the juju series for a machine.

    :param machine: Machine number
    :type machine: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Juju series
    :rtype: string
    """
    return get_machine_status(
        machine=machine,
        key='series',
        model_name=model_name
    )


def get_machine_uuids_for_application(application, model_name=None):
    """Return machine uuids for a given application.

    :param application: Application name
    :type application: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: machine uuuids for an application
    :rtype: Iterator[str]
    """
    for machine in get_machines_for_application(application,
                                                model_name=model_name):
        yield get_machine_status(machine, key="instance-id",
                                 model_name=model_name)


def get_provider_type():
    """Get the type of the undercloud.

    :returns: Name of the undercloud type
    :rtype: string
    """
    cloud = controller.get_cloud()
    if cloud:
        # If the controller was deployed from this system with
        # the cloud configured in ~/.local/share/juju/clouds.yaml
        # Determine the cloud type directly
        return get_cloud_configs(cloud)["type"]
    else:
        # If the controller was deployed elsewhere
        # For now assume openstack
        return "openstack"


def remote_run(unit, remote_cmd, timeout=None, fatal=None, model_name=None):
    """Run command on unit and return the output.

    NOTE: This function is pre-deprecated. As soon as libjuju unit.run is able
    to return output this functionality should move to model.run_on_unit.

    :param remote_cmd: Command to execute on unit
    :type remote_cmd: string
    :param timeout: Timeout value for the command
    :type arg: int
    :param fatal: Command failure condidered fatal or not
    :type fatal: boolean
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Juju run output
    :rtype: string
    :raises: model.CommandRunFailed
    """
    if fatal is None:
        fatal = True
    result = model.run_on_unit(
        unit,
        remote_cmd,
        timeout=timeout,
        model_name=model_name)
    if result:
        if int(result.get("Code")) == 0:
            return result.get("Stdout")
        else:
            if fatal:
                raise model.CommandRunFailed(remote_cmd, result)
            return result.get("Stderr")


def _get_unit_names(names, model_name=None):
    """Resolve given application names to first unit name of said application.

    Helper function that resolves application names to first unit name of
    said application.  Any already resolved unit names are returned as-is.

    :param names: List of units/applications to translate
    :type names: list(str)
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: List of units
    :rtype: list(str)
    """
    result = []
    for name in names:
        if '/' in name:
            result.append(name)
        else:
            result.append(model.get_first_unit_name(
                name,
                model_name=model_name))
    return result


def get_relation_from_unit(entity, remote_entity, remote_interface_name,
                           model_name=None):
    """Get relation data passed between two units.

    Get relation data for relation with `remote_interface_name` between
    `entity` and `remote_entity` from the perspective of `entity`.

    `entity` and `remote_entity` may refer to either a application or a
    specific unit. If application name is given first unit is found in model.

    :param entity: Application or unit to get relation data from
    :type entity: str
    :param remote_entity: Application or Unit in the other end of the relation
                          we want to query
    :type remote_entity: str
    :param remote_interface_name: Name of interface to query on remote end of
                                  relation
    :type remote_interface_name: str
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: dict with relation data
    :rtype: dict
    :raises: model.CommandRunFailed
    """
    application = entity.split('/')[0]
    remote_application = remote_entity.split('/')[0]
    rid = model.get_relation_id(application, remote_application,
                                remote_interface_name=remote_interface_name,
                                model_name=model_name)
    (unit, remote_unit) = _get_unit_names(
        [entity, remote_entity],
        model_name=model_name)
    cmd = 'relation-get --format=yaml -r "{}" - "{}"' .format(rid, remote_unit)
    result = model.run_on_unit(unit, cmd, model_name=model_name)
    if result and int(result.get('Code')) == 0:
        return yaml.safe_load(result.get('Stdout'))
    else:
        raise model.CommandRunFailed(cmd, result)


def leader_get(application, key='', model_name=None):
    """Get leader settings from leader unit of named application.

    :param application: Application to get leader settings from.
    :type application: str
    :param key: Key option requested
    :type key: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: dict with leader settings
    :rtype: dict
    :raises: model.CommandRunFailed
    """
    cmd = 'leader-get --format=yaml {}'.format(key)
    result = model.run_on_leader(application, cmd, model_name=model_name)
    if result and int(result.get('Code')) == 0:
        return yaml.safe_load(result.get('Stdout'))
    else:
        raise model.CommandRunFailed(cmd, result)


def get_subordinate_units(unit_list, charm_name=None, status=None,
                          model_name=None):
    """Get a list of all subordinate units associated with units in unit_list.

    Get a list of all subordinate units associated with units in unit_list.
    Subordinate can be filtered by using 'charm_name' which will only return
    subordinate units which have 'charm_name' in the name of the charm e.g.

        get_subordinate_units(
            ['cinder/1']) would return ['cinder-hacluster/1',
                                        'cinder-ceph/2'])
    where as

        get_subordinate_units(
            ['cinder/1'], charm_name='hac') would return ['cinder-hacluster/1']

    NOTE: The charm_name match is against the name of the charm not the
          application name.

    :param charm_name: List of unit names
    :type unit_list: []
    :param charm_name: charm_name to match against, can be a sub-string.
    :type charm_name: str
    :param status: Juju status to query against,
    :type status: juju.client._definitions.FullStatus
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: List of matching unit names.
    :rtype: []
    """
    if not status:
        status = model.get_status(model_name=model_name)
    sub_units = []
    for unit_name in unit_list:
        app_name = unit_name.split('/')[0]
        subs = status.applications[app_name]['units'][unit_name].get(
            'subordinates') or {}
        if charm_name:
            for unit_name, unit_data in subs.items():
                if charm_name in unit_data['charm']:
                    sub_units.append(unit_name)
        else:
            sub_units.extend([n for n in subs.keys()])
    return sub_units
