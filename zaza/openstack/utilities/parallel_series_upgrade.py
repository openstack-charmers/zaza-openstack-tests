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

from zaza import model
from zaza.charm_lifecycle import utils as cl_utils
import zaza.openstack.utilities.generic as os_utils
import zaza.openstack.utilities.series_upgrade as series_upgrade_utils
from zaza.openstack.utilities.series_upgrade import (
    SUBORDINATE_PAUSE_RESUME_BLACKLIST,
)


def app_config(charm_name):
    """Return a dict with the upgrade config for an application.

    :param charm_name: Name of the charm about to upgrade
    :type charm_name: str
    :param async: Whether the upgreade functions should be async
    :type async: bool
    :returns: A dicitonary of the upgrade config for the application
    :rtype: Dict
    """
    default = {
        'origin': 'openstack-origin',
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
            'origin': 'source',
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
                ('zaza.openstack.charm_tests.vault.setup.'
                 'mojo_unseal_by_unit')]
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
        parallel_series_upgrade(
            'ubuntu-lite', pause_non_leader_primary=False,
            pause_non_leader_subordinate=False,
            completed_machines=completed_machines, origin=None)
    )


async def parallel_series_upgrade(
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
    leader, non_leaders = get_leader_and_non_leaders(status)
    for leader_name, leader_unit in leader.items():
        leader_machine = leader_unit["machine"]
        leader = leader_name
    machines = [
        unit["machine"] for name, unit
        in non_leaders.items()
        if unit['machine'] not in completed_machines]

    await maybe_pause_things(
        status,
        non_leaders,
        pause_non_leader_subordinate,
        pause_non_leader_primary)
    await series_upgrade_utils.async_set_series(
        application, to_series=to_series)

    prepare_group = [
        series_upgrade_utils.async_prepare_series_upgrade(
            machine, to_series=to_series)
        for machine in machines]
    asyncio.gather(*prepare_group)
    await series_upgrade_utils.async_prepare_series_upgrade(
        leader_machine, to_series=to_series)
    if leader_machine not in completed_machines:
        machines.append(leader_machine)
    upgrade_group = [
        series_upgrade_machine(
            machine,
            files=files, workaround_script=workaround_script,
            post_upgrade_functions=post_upgrade_functions)
        for machine in machines
    ]
    await asyncio.gather(*upgrade_group)
    if origin:
        await os_utils.async_set_origin(application, origin)
    run_post_application_upgrade_functions(post_application_upgrade_functions)


async def serial_series_upgrade(
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

    machines = [
        unit["machine"] for name, unit
        in non_leaders.items()
        if unit['machine'] not in completed_machines]

    await maybe_pause_things(
        status,
        non_leaders,
        pause_non_leader_subordinate,
        pause_non_leader_primary)
    await series_upgrade_utils.async_set_series(
        application, to_series=to_series)

    if not follower_first and leader_machine not in completed_machines:
        await series_upgrade_utils.async_prepare_series_upgrade(
            leader_machine, to_series=to_series)
        logging.info("About to upgrade leader of {}: {}"
                     .format(application, leader_machine))
        await series_upgrade_machine(
            leader_machine,
            files=files, workaround_script=workaround_script,
            post_upgrade_functions=post_upgrade_functions)

    for machine in machines:
        await series_upgrade_utils.async_prepare_series_upgrade(
            machine, to_series=to_series)
        logging.info("About to upgrade follower of {}: {}"
                     .format(application, machine))
        await series_upgrade_machine(
            machine,
            files=files, workaround_script=workaround_script,
            post_upgrade_functions=post_upgrade_functions)

    if follower_first and leader_machine not in completed_machines:
        await series_upgrade_utils.async_prepare_series_upgrade(
            leader_machine, to_series=to_series)
        logging.info("About to upgrade leader of {}: {}"
                     .format(application, leader_machine))
        await series_upgrade_machine(
            leader_machine,
            files=files, workaround_script=workaround_script,
            post_upgrade_functions=post_upgrade_functions)
    if origin:
        await os_utils.async_set_origin(application, origin)
    run_post_application_upgrade_functions(post_application_upgrade_functions)


async def series_upgrade_machine(
        machine,
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
    logging.info(
        "About to dist-upgrade ({})".format(machine))

    run_pre_upgrade_functions(machine, pre_upgrade_functions)
    await async_dist_upgrade(machine)
    await async_do_release_upgrade(machine)
    await reboot(machine)
    await series_upgrade_utils.async_complete_series_upgrade(machine)
    series_upgrade_utils.run_post_upgrade_functions(post_upgrade_functions)


def run_pre_upgrade_functions(machine, pre_upgrade_functions):
    """Execute list supplied functions.

    Each of the supplied functions will be called with a single
    argument of the machine that is about to be upgraded.

    :param machine: Machine that is about to be upgraded
    :type machine: str
    :param pre_upgrade_functions: List of functions
    :type pre_upgrade_functions: [function, function, ...]
    """
    if pre_upgrade_functions:
        for func in pre_upgrade_functions:
            logging.info("Running {}".format(func))
            cl_utils.get_class(func)(machine)


def run_post_application_upgrade_functions(post_upgrade_functions):
    """Execute list supplied functions.

    :param post_upgrade_functions: List of functions
    :type post_upgrade_functions: [function, function, ...]
    """
    if post_upgrade_functions:
        for func in post_upgrade_functions:
            logging.info("Running {}".format(func))
            cl_utils.get_class(func)()


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
    subordinate_pauses = []
    leader_pauses = []
    for unit in units:
        if pause_non_leader_subordinate:
            if status["units"][unit].get("subordinates"):
                for subordinate in status["units"][unit]["subordinates"]:
                    _app = subordinate.split('/')[0]
                    if _app in SUBORDINATE_PAUSE_RESUME_BLACKLIST:
                        logging.info("Skipping pausing {} - blacklisted"
                                     .format(subordinate))
                    else:
                        logging.info("Pausing {}".format(subordinate))
                        subordinate_pauses.append(model.async_run_action(
                            subordinate, "pause", action_params={}))
        if pause_non_leader_primary:
            logging.info("Pausing {}".format(unit))
            leader_pauses.append(
                model.async_run_action(unit, "pause", action_params={}))
    await asyncio.gather(*subordinate_pauses)
    await asyncio.gather(*leader_pauses)


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
    :param machine_num: Machine number
    :type machine_num: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :returns: None
    :rtype: None
    """
    logging.debug("Preparing series upgrade for: {}".format(machine))
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
        await run_on_machine(machine, 'shutdown --reboot now & exit')
        # await run_on_machine(unit, "sudo reboot && exit")
    except subprocess.CalledProcessError as e:
        logging.warn("Error doing reboot: {}".format(e))
        pass


async def run_on_machine(machine, command, model_name=None, timeout=None):
    """Juju run on unit.

    :param model_name: Name of model unit is in
    :type model_name: str
    :param unit_name: Name of unit to match
    :type unit: str
    :param command: Command to execute
    :type command: str
    :param timeout: How long in seconds to wait for command to complete
    :type timeout: int
    :returns: action.data['results'] {'Code': '', 'Stderr': '', 'Stdout': ''}
    :rtype: dict
    """
    cmd = ['juju', 'run', '--machine={}'.format(machine)]
    if model_name:
        cmd.append('--model={}'.format(model_name))
    if timeout:
        cmd.append('--timeout={}'.format(timeout))
    cmd.append(command)
    logging.debug("About to call '{}'".format(cmd))
    await os_utils.check_call(cmd)


async def async_dist_upgrade(machine):
    """Run dist-upgrade on unit after update package db.

    :param machine: Machine Number
    :type machine: str
    :returns: None
    :rtype: None
    """
    logging.info('Updating package db ' + machine)
    update_cmd = 'sudo apt update'
    await run_on_machine(machine, update_cmd)

    logging.info('Updating existing packages ' + machine)
    dist_upgrade_cmd = (
        """yes | sudo DEBIAN_FRONTEND=noninteractive apt --assume-yes """
        """-o "Dpkg::Options::=--force-confdef" """
        """-o "Dpkg::Options::=--force-confold" dist-upgrade""")
    await run_on_machine(machine, dist_upgrade_cmd)


async def async_do_release_upgrade(machine):
    """Run do-release-upgrade noninteractive.

    :param machine: Machine Name
    :type machine: str
    :returns: None
    :rtype: None
    """
    logging.info('Upgrading ' + machine)
    do_release_upgrade_cmd = (
        'yes | sudo DEBIAN_FRONTEND=noninteractive '
        'do-release-upgrade -f DistUpgradeViewNonInteractive')

    await run_on_machine(machine, do_release_upgrade_cmd, timeout="120m")
