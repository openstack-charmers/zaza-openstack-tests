#!/usr/bin/env python3
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

"""Collection of functions for testing series upgrade in parallel."""


import asyncio

import collections
import copy
import logging
import subprocess

from zaza import model, sync_wrapper
from zaza.charm_lifecycle import utils as cl_utils
import zaza.openstack.utilities.generic as os_utils
import zaza.openstack.utilities.series_upgrade as series_upgrade_utils
from zaza.openstack.utilities.series_upgrade import async_pause_helper


def app_config(charm_name, vault_unsealer=None):
    """Return a dict with the upgrade config for an application.

    :param charm_name: Name of the charm about to upgrade
    :type charm_name: str
    :param async: Whether the upgreade functions should be async
    :type async: bool
    :returns: A dicitonary of the upgrade config for the application
    :rtype: Dict
    """
    default = {
        'origin': 'auto',
        'pause_non_leader_subordinate': True,
        'pause_non_leader_primary': True,
        'post_upgrade_functions': [],
        'pre_upgrade_functions': [],
        'post_application_upgrade_functions': [],
        'follower_first': False, }
    _app_settings = collections.defaultdict(lambda: default)
    ceph = {
        'origin': "source",
        'pause_non_leader_primary': False,
        'pause_non_leader_subordinate': False,
    }
    exceptions = {
        'rabbitmq-server': {
            # NOTE: AJK disable config-changed on rabbitmq-server due to bug:
            # #1896520
            'origin': None,
            'pause_non_leader_subordinate': False,
            'post_application_upgrade_functions': [
                ('zaza.openstack.charm_tests.rabbitmq_server.utils.'
                 'complete_cluster_series_upgrade')]
        },
        'percona-cluster': {
            'origin': 'source',
            'post_application_upgrade_functions': [
                ('zaza.openstack.charm_tests.mysql.utils.'
                 'complete_cluster_series_upgrade')]
        },
        'nova-compute': {
            'pause_non_leader_primary': False,
            'pause_non_leader_subordinate': False,
            # TODO
            # 'pre_upgrade_functions': [
            #     'zaza.openstack.charm_tests.nova_compute.setup.evacuate'
            # ]
        },
        'ceph': ceph,
        'ceph-mon': ceph,
        'ceph-osd': ceph,
        'designate-bind': {'origin': None, },
        'tempest': {'origin': None, },
        'memcached': {
            'origin': None,
            'pause_non_leader_primary': False,
            'pause_non_leader_subordinate': False,
        },
        'vault': {
            'origin': None,
            'pause_non_leader_primary': False,
            'pause_non_leader_subordinate': True,
            'post_upgrade_functions': [
                vault_unsealer or
                ('zaza.openstack.charm_tests.vault.setup.'
                 'async_mojo_or_default_unseal_by_unit')]
        },
        'mongodb': {
            'origin': None,
            'follower_first': True,
        }
    }
    for key, value in exceptions.items():
        _app_settings[key] = copy.deepcopy(default)
        _app_settings[key].update(value)
    return _app_settings[charm_name]


def upgrade_ubuntu_lite(from_series='xenial', to_series='bionic'):
    """Validate that we can upgrade the ubuntu-lite charm.

    :param from_series: What series are we upgrading from
    :type from_series: str
    :param to_series: What series are we upgrading to
    :type to_series: str
    """
    completed_machines = []
    asyncio.get_event_loop().run_until_complete(
        async_parallel_series_upgrade(
            'ubuntu-lite', pause_non_leader_primary=False,
            pause_non_leader_subordinate=False,
            from_series=from_series, to_series=to_series,
            completed_machines=completed_machines, origin=None)
    )


async def async_parallel_series_upgrade(
    application,
    from_series='xenial',
    to_series='bionic',
    origin='openstack-origin',
    pause_non_leader_primary=True,
    pause_non_leader_subordinate=True,
    pre_upgrade_functions=None,
    post_upgrade_functions=None,
    post_application_upgrade_functions=None,
    completed_machines=None,
    follower_first=False,
    files=None,
    workaround_script=None
):
    """Perform series upgrade on an application in parallel.

    :param unit_name: Unit Name
    :type unit_name: str
    :param machine_num: Machine number
    :type machine_num: str
    :param from_series: The series from which to upgrade
    :type from_series: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param origin: The configuration setting variable name for changing origin
                   source. (openstack-origin or source)
    :type origin: str
    :param pause_non_leader_primary: Whether the non-leader applications should
                                     be paused
    :type pause_non_leader_primary: bool
    :param pause_non_leader_subordinate: Whether the non-leader subordinate
                                         hacluster applications should be
                                         paused
    :type pause_non_leader_subordinate: bool

    :param pre_upgrade_functions: A list of Zaza functions to call before
                                  the upgrade is started on each machine
    :type pre_upgrade_functions: List[str]
    :param post_upgrade_functions: A list of Zaza functions to call when
                                   the upgrade is complete on each machine
    :type post_upgrade_functions: List[str]
    :param post_application_upgrade_functions: A list of Zaza functions
                                   to call when the upgrade is complete
                                   on all machine in the application
    :param follower_first: Should the follower(s) be upgraded first
    :type follower_first: bool
    :type post_application_upgrade_functions: List[str]
    :param files: Workaround files to scp to unit under upgrade
    :type files: list
    :param workaround_script: Workaround script to run during series upgrade
    :type workaround_script: str
    :returns: None
    :rtype: None
    """
    if completed_machines is None:
        completed_machines = []
    if follower_first:
        logging.error("leader_first is ignored for parallel upgrade")
    logging.info(
        "About to upgrade the units of {} in parallel (follower first: {})"
        .format(application, follower_first))

    status = (await model.async_get_status()).applications[application]
    logging.info(
        "Configuring leader / non leaders for {}".format(application))
    leaders, non_leaders = get_leader_and_non_leaders(status)
    for leader_unit in leaders.values():
        leader_machine = leader_unit["machine"]
    machines = [unit["machine"] for name, unit in non_leaders.items()
                if unit['machine'] not in completed_machines]

    await maybe_pause_things(
        status,
        non_leaders,
        pause_non_leader_subordinate,
        pause_non_leader_primary)
    # wait for the entire application set to be idle before starting upgrades
    await asyncio.gather(*[
        model.async_wait_for_unit_idle(unit, include_subordinates=True)
        for unit in status["units"]])
    await prepare_series_upgrade(leader_machine, to_series=to_series)
    await asyncio.gather(*[
        wait_for_idle_then_prepare_series_upgrade(
            machine, to_series=to_series)
        for machine in machines])
    if leader_machine not in completed_machines:
        machines.append(leader_machine)
    await asyncio.gather(*[
        series_upgrade_machine(
            machine,
            origin=origin,
            application=application,
            files=files, workaround_script=workaround_script,
            post_upgrade_functions=post_upgrade_functions)
        for machine in machines])
    completed_machines.extend(machines)
    await series_upgrade_utils.async_set_series(
        application, to_series=to_series)
    await run_post_application_upgrade_functions(
        post_application_upgrade_functions)

parallel_series_upgrade = sync_wrapper(async_parallel_series_upgrade)


async def wait_for_idle_then_prepare_series_upgrade(
        machine, to_series, model_name=None):
    """Wait for the units to idle the do prepare_series_upgrade.

    We need to be sure that all the units are idle prior to actually calling
    prepare_series_upgrade() as otherwise the call will fail.  It has to be
    checked because when the leader is paused it may kick off relation hooks in
    the other units in an HA group.

    :param machine: the machine that is going to be prepared
    :type machine: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param model_name: Name of model to query.
    :type model_name: str
    """
    await model.async_block_until_units_on_machine_are_idle(
        machine, model_name=model_name)
    await prepare_series_upgrade(machine, to_series=to_series)


async def async_serial_series_upgrade(
    application,
    from_series='xenial',
    to_series='bionic',
    origin='openstack-origin',
    pause_non_leader_primary=True,
    pause_non_leader_subordinate=True,
    pre_upgrade_functions=None,
    post_upgrade_functions=None,
    post_application_upgrade_functions=None,
    completed_machines=None,
    follower_first=False,
    files=None,
    workaround_script=None
):
    """Perform series upgrade on an application in serial.

    :param unit_name: Unit Name
    :type unit_name: str
    :param machine_num: Machine number
    :type machine_num: str
    :param from_series: The series from which to upgrade
    :type from_series: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param origin: The configuration setting variable name for changing origin
                   source. (openstack-origin or source)
    :type origin: str
    :param pause_non_leader_primary: Whether the non-leader applications should
                                     be paused
    :type pause_non_leader_primary: bool
    :param pause_non_leader_subordinate: Whether the non-leader subordinate
                                         hacluster applications should be
                                         paused
    :type pause_non_leader_subordinate: bool

    :param pre_upgrade_functions: A list of Zaza functions to call before
                                  the upgrade is started on each machine
    :type pre_upgrade_functions: List[str]
    :param post_upgrade_functions: A list of Zaza functions to call when
                                   the upgrade is complete on each machine
    :type post_upgrade_functions: List[str]
    :param post_application_upgrade_functions: A list of Zaza functions
                                   to call when the upgrade is complete
                                   on all machine in the application
    :param follower_first: Should the follower(s) be upgraded first
    :type follower_first: bool
    :type post_application_upgrade_functions: List[str]
    :param files: Workaround files to scp to unit under upgrade
    :type files: list
    :param workaround_script: Workaround script to run during series upgrade
    :type workaround_script: str
    :returns: None
    :rtype: None
    """
    if completed_machines is None:
        completed_machines = []
    logging.info(
        "About to upgrade the units of {} in serial (follower first: {})"
        .format(application, follower_first))
    status = (await model.async_get_status()).applications[application]
    logging.info(
        "Configuring leader / non leaders for {}".format(application))
    leader, non_leaders = get_leader_and_non_leaders(status)
    for leader_name, leader_unit in leader.items():
        leader_machine = leader_unit["machine"]
        leader = leader_name

    await maybe_pause_things(
        status,
        non_leaders,
        pause_non_leader_subordinate,
        pause_non_leader_primary)
    logging.info("Finishing pausing application: {}".format(application))
    await series_upgrade_utils.async_set_series(
        application, to_series=to_series)
    logging.info("Finished set series for application: {}".format(application))
    if not follower_first and leader_machine not in completed_machines:
        await model.async_wait_for_unit_idle(leader, include_subordinates=True)
        await prepare_series_upgrade(leader_machine, to_series=to_series)
        logging.info("About to upgrade leader of {}: {}"
                     .format(application, leader_machine))
        await series_upgrade_machine(
            leader_machine,
            origin=origin,
            application=application,
            files=files, workaround_script=workaround_script,
            post_upgrade_functions=post_upgrade_functions)
        completed_machines.append(leader_machine)
        logging.info("Finished upgrading of leader for application: {}"
                     .format(application))

    # for machine in machines:
    for unit_name, unit in non_leaders.items():
        machine = unit['machine']
        if machine in completed_machines:
            continue
        await model.async_wait_for_unit_idle(
            unit_name, include_subordinates=True)
        await prepare_series_upgrade(machine, to_series=to_series)
        logging.info("About to upgrade follower of {}: {}"
                     .format(application, machine))
        await series_upgrade_machine(
            machine,
            origin=origin,
            application=application,
            files=files, workaround_script=workaround_script,
            post_upgrade_functions=post_upgrade_functions)
        completed_machines.append(machine)
    logging.info("Finished upgrading non leaders for application: {}"
                 .format(application))

    if follower_first and leader_machine not in completed_machines:
        await model.async_wait_for_unit_idle(leader, include_subordinates=True)
        await prepare_series_upgrade(leader_machine, to_series=to_series)
        logging.info("About to upgrade leader of {}: {}"
                     .format(application, leader_machine))
        await series_upgrade_machine(
            leader_machine,
            origin=origin,
            application=application,
            files=files, workaround_script=workaround_script,
            post_upgrade_functions=post_upgrade_functions)
        completed_machines.append(leader_machine)
    await run_post_application_upgrade_functions(
        post_application_upgrade_functions)
    logging.info("Done series upgrade for: {}".format(application))

serial_series_upgrade = sync_wrapper(async_serial_series_upgrade)


async def series_upgrade_machine(
        machine,
        origin=None,
        application=None,
        post_upgrade_functions=None,
        pre_upgrade_functions=None,
        files=None,
        workaround_script=None):
    """Perform series upgrade on an machine.

    :param machine_num: Machine number
    :type machine_num: str
    :param files: Workaround files to scp to unit under upgrade
    :type files: list
    :param workaround_script: Workaround script to run during series upgrade
    :type workaround_script: str
    :param pre_upgrade_functions: A list of Zaza functions to call before
                                  the upgrade is started on each machine
    :type pre_upgrade_functions: List[str]
    :param post_upgrade_functions: A list of Zaza functions to call when
                                   the upgrade is complete on each machine
    :type post_upgrade_functions: List[str]
    :returns: None
    :rtype: None
    """
    logging.info("About to series-upgrade ({})".format(machine))
    await run_pre_upgrade_functions(machine, pre_upgrade_functions)
    await add_confdef_file(machine)
    await async_dist_upgrade(machine)
    await async_do_release_upgrade(machine)
    await remove_confdef_file(machine)
    await reboot(machine)
    await series_upgrade_utils.async_complete_series_upgrade(machine)
    if origin:
        await os_utils.async_set_origin(application, origin)
    await run_post_upgrade_functions(post_upgrade_functions)


async def add_confdef_file(machine):
    """Add the file  /etc/apt/apt-conf.d/local setup to accept defaults.

    :param machine: The machine to manage
    :type machine: str
    :returns: None
    :rtype: None
    """
    create_file = (
        """echo 'DPkg::options { "--force-confdef"; "--force-confnew"; }' | """
        """sudo tee /etc/apt/apt.conf.d/local"""
    )
    await model.async_run_on_machine(machine, create_file)


async def remove_confdef_file(machine):
    """Remove the file  /etc/apt/apt-conf.d/local setup to accept defaults.

    :param machine: The machine to manage
    :type machine: str
    :returns: None
    :rtype: None
    """
    await model.async_run_on_machine(
        machine,
        "sudo rm /etc/apt/apt.conf.d/local")


async def run_pre_upgrade_functions(machine, pre_upgrade_functions):
    """Execute list supplied functions.

    Each of the supplied functions will be called with a single
    argument of the machine that is about to be upgraded.

    :param machine: Machine that is about to be upgraded
    :type machine: str
    :param pre_upgrade_functions: List of awaitable functions
    :type pre_upgrade_functions: [function, function, ...]
    """
    if pre_upgrade_functions:
        for func in pre_upgrade_functions:
            logging.info("Running {}".format(func))
            m = cl_utils.get_class(func)
            await m(machine)


async def run_post_upgrade_functions(post_upgrade_functions):
    """Execute list supplied functions.

    :param post_upgrade_functions: List of awaitable functions
    :type post_upgrade_functions: [function, function, ...]
    """
    if post_upgrade_functions:
        for func in post_upgrade_functions:
            if callable(func):
                func()
                return
            logging.info("Running {}".format(func))
            m = cl_utils.get_class(func)
            await m()


async def run_post_application_upgrade_functions(post_upgrade_functions):
    """Execute list supplied functions.

    :param post_upgrade_functions: List of awaitable functions
    :type post_upgrade_functions: [function, function, ...]
    """
    if post_upgrade_functions:
        for func in post_upgrade_functions:
            logging.info("Running {}".format(func))
            m = cl_utils.get_class(func)
            await m()


async def maybe_pause_things(
        status, units, pause_non_leader_subordinate=True,
        pause_non_leader_primary=True):
    """Pause the non-leaders, based on the run configuration.

    :param status: Juju status for an application
    :type status: juju.applications
    :param units: List of units to paybe pause
    :type units: LIst[str]
    :param pause_non_leader_subordinate: Should the non leader
                                         subordinate be paused
    :type pause_non_leader_subordinate: bool
    :param pause_non_leader_primary: Should the non leaders be paused
    :type pause_non_leader_primary: bool
    :returns: Nothing
    :trype: None
    """
    unit_pauses = []
    for unit in units:
        if pause_non_leader_subordinate:
            if status["units"][unit].get("subordinates"):
                for subordinate in status["units"][unit]["subordinates"]:
                    unit_pauses.append(async_pause_helper(
                        "subordinate", subordinate))
        if pause_non_leader_primary:
            unit_pauses.append(async_pause_helper("leader", unit))
    if unit_pauses:
        await asyncio.gather(*unit_pauses)


def get_leader_and_non_leaders(status):
    """Get the leader and non-leader Juju units.

    This function returns a tuple that looks like:

    ({
        'unit/1': juju.Unit,
    },
    {
        'unit/0': juju.Unit,
        'unit/2': juju.unit,
    })

    The first entry of this tuple is the leader, and the second is
    all non-leader units.

    :returns: A tuple of dicts identifying leader and non-leaders
    :rtype: Dict[str, List[juju.Unit]]
    """
    leader = None
    non_leaders = {}
    for name, unit in status["units"].items():
        if unit.get("leader"):
            leader = {name: unit}
        else:
            non_leaders[name] = unit
    return (leader, non_leaders)


async def prepare_series_upgrade(machine, to_series):
    """Execute juju series-upgrade prepare on machine.

    NOTE: This is a new feature in juju behind a feature flag and not yet in
    libjuju.
    export JUJU_DEV_FEATURE_FLAGS=upgrade-series
    :param machine: Machine number
    :type machine: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :returns: None
    :rtype: None
    """
    logging.info("Preparing series upgrade for: %s", machine)
    await series_upgrade_utils.async_prepare_series_upgrade(
        machine, to_series=to_series)


async def reboot(machine):
    """Reboot the named machine.

    :param machine: Machine to reboot
    :type machine: str
    :returns: Nothing
    :rtype: None
    """
    try:
        await model.async_run_on_machine(machine, 'sudo init 6 & exit')
        # await run_on_machine(unit, "sudo reboot && exit")
    except subprocess.CalledProcessError as error:
        logging.warning("Error doing reboot: %s", error)


async def async_dist_upgrade(machine):
    """Run dist-upgrade on unit after update package db.

    :param machine: Machine Number
    :type machine: str
    :returns: None
    :rtype: None
    """
    logging.info('Updating package db %s', machine)
    update_cmd = 'sudo apt-get update'
    await model.async_run_on_machine(machine, update_cmd)

    logging.info('Updating existing packages %s', machine)
    dist_upgrade_cmd = (
        """yes | sudo DEBIAN_FRONTEND=noninteractive apt-get --assume-yes """
        """-o "Dpkg::Options::=--force-confdef" """
        """-o "Dpkg::Options::=--force-confold" dist-upgrade""")
    await model.async_run_on_machine(machine, dist_upgrade_cmd)
    rdict = await model.async_run_on_machine(
        machine,
        "cat /var/run/reboot-required || true")
    if "Stdout" in rdict and "restart" in rdict["Stdout"].lower():
        logging.info("dist-upgrade required reboot machine: %s", machine)
        await reboot(machine)
        logging.info("Waiting for machine to come back afer reboot: %s",
                     machine)
        await model.async_block_until_file_missing_on_machine(
            machine, "/var/run/reboot-required")
        logging.info("Waiting for machine idleness on %s", machine)
        await asyncio.sleep(5.0)
        await model.async_block_until_units_on_machine_are_idle(machine)
        # TODO: change this to wait on units on the machine
        # await model.async_block_until_all_units_idle()


async def async_do_release_upgrade(machine):
    """Run do-release-upgrade noninteractive.

    :param machine: Machine Name
    :type machine: str
    :returns: None
    :rtype: None
    """
    logging.info('Upgrading %s', machine)
    do_release_upgrade_cmd = (
        'yes | sudo DEBIAN_FRONTEND=noninteractive '
        'do-release-upgrade -f DistUpgradeViewNonInteractive')

    await model.async_run_on_machine(
        machine, do_release_upgrade_cmd, timeout="120m")
