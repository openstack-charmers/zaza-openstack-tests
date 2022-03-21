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
"""Deprecated, please use zaza.utilities.juju."""

import logging
import functools

import zaza.utilities.juju


def deprecate():
    """Add a deprecation warning to wrapped function."""
    def wrap(f):

        @functools.wraps(f)
        def wrapped_f(*args, **kwargs):
            msg = (
                "{} from zaza.openstack.utilities.juju is deprecated. "
                "Please use the equivalent from zaza.utilities.juju".format(
                    f.__name__))
            logging.warning(msg)
            return f(*args, **kwargs)
        return wrapped_f
    return wrap


@deprecate()
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
    return zaza.utilities.juju.get_application_status(
        application=application,
        unit=unit,
        model_name=model_name)


@deprecate()
def get_application_ip(application, model_name=None):
    """Get the application's IP address.

    :param application: Application name
    :type application: str
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Application's IP address
    :rtype: str
    """
    return zaza.utilities.juju.get_application_ip(
        application,
        model_name=model_name)


@deprecate()
def get_cloud_configs(cloud=None):
    """Get cloud configuration from local clouds.yaml.

    libjuju does not yet have cloud information implemented.
    Use libjuju as soon as possible.

    :param cloud: Name of specific cloud
    :type remote_cmd: string
    :returns: Dictionary of cloud configuration
    :rtype: dict
    """
    return zaza.utilities.juju.get_cloud_configs(
        cloud=cloud)


@deprecate()
def get_full_juju_status(model_name=None):
    """Return the full juju status output.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Full juju status output
    :rtype: dict
    """
    return zaza.utilities.juju.get_full_juju_status(
        model_name=model_name)


@deprecate()
def get_machines_for_application(application, model_name=None):
    """Return machines for a given application.

    :param application: Application name
    :type application: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: machines for an application
    :rtype: Iterator[str]
    """
    return zaza.utilities.juju.get_machines_for_application(
        application,
        model_name=model_name)


@deprecate()
def get_unit_name_from_host_name(host_name, application, model_name=None):
    """Return the juju unit name corresponding to a hostname.

    :param host_name: Host name to map to unit name.
    :type host_name: string
    :param application: Application name
    :type application: string
    :param model_name: Name of model to query.
    :type model_name: str
    """
    return zaza.utilities.juju.get_unit_name_from_host_name(
        host_name,
        application,
        model_name=model_name)


@deprecate()
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
    return zaza.utilities.juju.get_machine_status(
        machine,
        key=key,
        model_name=model_name)


@deprecate()
def get_machine_series(machine, model_name=None):
    """Return the juju series for a machine.

    :param machine: Machine number
    :type machine: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Juju series
    :rtype: string
    """
    return zaza.utilities.juju.get_machine_series(
        machine,
        model_name=model_name)


@deprecate()
def get_machine_uuids_for_application(application, model_name=None):
    """Return machine uuids for a given application.

    :param application: Application name
    :type application: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: machine uuuids for an application
    :rtype: Iterator[str]
    """
    return zaza.utilities.juju.get_machine_uuids_for_application(
        application,
        model_name=model_name)


@deprecate()
def get_provider_type():
    """Get the type of the undercloud.

    :returns: Name of the undercloud type
    :rtype: string
    """
    return zaza.utilities.juju.get_provider_type()


@deprecate()
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
    return zaza.utilities.juju.remote_run(
        unit,
        remote_cmd,
        timeout=timeout,
        fatal=fatal,
        model_name=model_name)


@deprecate()
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
    return zaza.utilities.juju.get_relation_from_unit(
        entity,
        remote_entity,
        remote_interface_name,
        model_name=model_name)


@deprecate()
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
    return zaza.utilities.juju.leader_get(
        application,
        key=key,
        model_name=model_name)


@deprecate()
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
    return zaza.utilities.juju.get_subordinate_units(
        unit_list,
        charm_name=charm_name,
        status=status,
        model_name=model_name)
