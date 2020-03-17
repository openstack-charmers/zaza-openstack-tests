# Copyright 2019 Canonical Ltd.
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

"""Module for performing OpenStack upgrades.

This module contains a number of functions for upgrading OpenStack.
"""
import logging
import zaza.openstack.utilities.juju as juju_utils

import zaza.model
from zaza import sync_wrapper
from zaza.openstack.utilities.upgrade_utils import (
    SERVICE_GROUPS,
    UPGRADE_EXCLUDE_LIST,
    get_upgrade_candidates,
    get_upgrade_groups,
)


async def async_pause_units(units, model_name=None):
    """Pause all units in unit list.

    Pause all units in unit list. Wait for pause action
    to complete.

    :param units: List of unit names.
    :type units: []
    :param model_name: Name of model to query.
    :type model_name: str
    :rtype: juju.action.Action
    :raises: zaza.model.ActionFailed
    """
    logging.info("Pausing {}".format(', '.join(units)))
    await zaza.model.async_run_action_on_units(
        units,
        'pause',
        model_name=model_name,
        raise_on_failure=True)

pause_units = sync_wrapper(async_pause_units)


async def async_resume_units(units, model_name=None):
    """Resume all units in unit list.

    Resume all units in unit list. Wait for resume action
    to complete.

    :param units: List of unit names.
    :type units: []
    :param model_name: Name of model to query.
    :type model_name: str
    :rtype: juju.action.Action
    :raises: zaza.model.ActionFailed
    """
    logging.info("Resuming {}".format(', '.join(units)))
    await zaza.model.async_run_action_on_units(
        units,
        'resume',
        model_name=model_name,
        raise_on_failure=True)

resume_units = sync_wrapper(async_resume_units)


async def async_action_unit_upgrade(units, model_name=None):
    """Run openstack-upgrade on all units in unit list.

    Upgrade payload on all units in unit list. Wait for action
    to complete.

    :param units: List of unit names.
    :type units: []
    :param model_name: Name of model to query.
    :type model_name: str
    :rtype: juju.action.Action
    :raises: zaza.model.ActionFailed
    """
    logging.info("Upgrading {}".format(', '.join(units)))
    await zaza.model.async_run_action_on_units(
        units,
        'openstack-upgrade',
        model_name=model_name,
        raise_on_failure=True)

action_unit_upgrade = sync_wrapper(async_action_unit_upgrade)


def action_upgrade_group(applications, model_name=None):
    """Upgrade units using action managed upgrades.

    Upgrade all units of the given applications using action managed upgrades.
    This involves the following process:
        1) Take a unit from each application which has not been upgraded yet.
        2) Pause all hacluster units assocaiated with units to be upgraded.
        3) Pause target units.
        4) Upgrade target units.
        5) Resume target units.
        6) Resume hacluster units paused in step 2.
        7) Repeat until all units are upgraded.

    :param applications: List of application names.
    :type applications: []
    :param model_name: Name of model to query.
    :type model_name: str
    """
    status = zaza.model.get_status(model_name=model_name)
    done = []
    while True:
        target = []
        for app in applications:
            for unit in zaza.model.get_units(app, model_name=model_name):
                if unit.entity_id not in done:
                    target.append(unit.entity_id)
                    break
            else:
                logging.info("All units of {} upgraded".format(app))
        if not target:
            break
        hacluster_units = juju_utils.get_subordinate_units(
            target,
            'hacluster',
            status=status,
            model_name=model_name)

        pause_units(hacluster_units, model_name=model_name)
        pause_units(target, model_name=model_name)

        action_unit_upgrade(target, model_name=model_name)

        resume_units(target, model_name=model_name)
        resume_units(hacluster_units, model_name=model_name)

        done.extend(target)


def set_upgrade_application_config(applications, new_source,
                                   action_managed=True, model_name=None):
    """Set the charm config for upgrade.

    Set the charm config for upgrade.

    :param applications: List of application names.
    :type applications: []
    :param new_source: New package origin.
    :type new_source: str
    :param action_managed: Whether to set action-managed-upgrade config option.
    :type action_managed: bool
    :param model_name: Name of model to query.
    :type model_name: str
    """
    for app in applications:
        src_option = 'openstack-origin'
        charm_options = zaza.model.get_application_config(
            app, model_name=model_name)
        try:
            charm_options[src_option]
        except KeyError:
            src_option = 'source'
        config = {
            src_option: new_source}
        if action_managed:
            config['action-managed-upgrade'] = 'True'
        logging.info("Setting config for {} to {}".format(app, config))
        zaza.model.set_application_config(
            app,
            config,
            model_name=model_name)


def is_action_upgradable(app, model_name=None):
    """Can application be upgraded using action managed upgrade method.

    :param new_source: New package origin.
    :type new_source: str
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Whether app be upgraded using action managed upgrade method.
    :rtype: bool
    """
    config = zaza.model.get_application_config(app, model_name=model_name)
    try:
        config['action-managed-upgrade']
        supported = True
    except KeyError:
        supported = False
    return supported


def run_action_upgrade(group, new_source, model_name=None):
    """Upgrade payload of all applications in group using action upgrades.

    :param group: List of applications to upgrade.
    :type group
    :param new_source: New package origin.
    :type new_source: str
    :param model_name: Name of model to query.
    :type model_name: str
    """
    set_upgrade_application_config(group, new_source, model_name=model_name)
    action_upgrade_group(group, model_name=model_name)


def run_all_in_one_upgrade(group, new_source, model_name=None):
    """Upgrade payload of all applications in group using all-in-one method.

    :param group: List of applications to upgrade.
    :type group: []
    :source: New package origin.
    :type new_source: str
    :param model_name: Name of model to query.
    :type model_name: str
    """
    set_upgrade_application_config(
        group,
        new_source,
        model_name=model_name,
        action_managed=False)
    zaza.model.block_until_all_units_idle()


def run_upgrade(group, new_source, model_name=None):
    """Upgrade payload of all applications in group.

    Upgrade apps using action managed upgrades where possible and fallback to
    all_in_one method.

    :param group: List of applications to upgrade.
    :type group: []
    :param new_source: New package origin.
    :type new_source: str
    :param model_name: Name of model to query.
    :type model_name: str
    """
    action_upgrade = []
    all_in_one_upgrade = []
    for app in group:
        if is_action_upgradable(app, model_name=model_name):
            action_upgrade.append(app)
        else:
            all_in_one_upgrade.append(app)
    run_all_in_one_upgrade(
        all_in_one_upgrade,
        new_source,
        model_name=model_name)
    run_action_upgrade(
        action_upgrade,
        new_source,
        model_name=model_name)


def run_upgrade_tests(new_source, model_name=None):
    """Upgrade payload of all applications in model.

    This the most basic upgrade test. It should be adapted to add/remove
    elements from the environment and add tests at intermediate stages.

    :param new_source: New package origin.
    :type new_source: str
    :param model_name: Name of model to query.
    :type model_name: str
    """
    groups = get_upgrade_groups(model_name=model_name)
    run_upgrade(groups['Core Identity'], new_source, model_name=model_name)
    run_upgrade(groups['Storage'], new_source, model_name=model_name)
    run_upgrade(groups['Control Plane'], new_source, model_name=model_name)
    run_upgrade(groups['Compute'], new_source, model_name=model_name)
    run_upgrade(groups['sweep_up'], new_source, model_name=model_name)
