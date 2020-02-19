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

"""Collection of functions that did not fit anywhere else."""

import logging
import os
import socket
import subprocess
import telnetlib
import yaml

from zaza import model
from zaza.openstack.utilities import juju as juju_utils
from zaza.openstack.utilities import exceptions as zaza_exceptions
from zaza.openstack.utilities.os_versions import UBUNTU_OPENSTACK_RELEASE
from zaza.charm_lifecycle import utils as cl_utils

SUBORDINATE_PAUSE_RESUME_BLACKLIST = [
    "cinder-ceph",
]


def dict_to_yaml(dict_data):
    """Return YAML from dictionary.

    :param dict_data: Dictionary data
    :type dict_data: dict
    :returns: YAML dump
    :rtype: string
    """
    return yaml.dump(dict_data, default_flow_style=False)


def get_network_config(net_topology, ignore_env_vars=False,
                       net_topology_file="network.yaml"):
    """Get network info from environment.

    Get network info from network.yaml, override the values if specific
    environment variables are set for the undercloud.

    This function may be used when running network configuration from CLI to
    pass in network configuration settings from a YAML file.

    :param net_topology: Network topology name from network.yaml
    :type net_topology: string
    :param ignore_env_vars: Ignore enviroment variables or not
    :type ignore_env_vars: boolean
    :returns: Dictionary of network configuration
    :rtype: dict
    """
    if os.path.exists(net_topology_file):
        net_info = get_yaml_config(net_topology_file)[net_topology]
    else:
        raise Exception("Network topology file: {} not found."
                        .format(net_topology_file))

    if not ignore_env_vars:
        logging.info("Consuming network environment variables as overrides "
                     "for the undercloud.")
        net_info.update(get_undercloud_env_vars())

    logging.info("Network info: {}".format(dict_to_yaml(net_info)))
    return net_info


def get_unit_hostnames(units):
    """Return a dict of juju unit names to hostnames."""
    host_names = {}
    for unit in units:
        output = model.run_on_unit(unit.entity_id, 'hostname')
        hostname = output['Stdout'].strip()
        host_names[unit.entity_id] = hostname
    return host_names


def get_pkg_version(application, pkg, model_name=None):
    """Return package version.

    :param application: Application name
    :type application: string
    :param pkg: Package name
    :type pkg: string
    :param model_name: Name of model to query.
    :type model_name: str
    :returns: List of package version
    :rtype: list
    """
    versions = []
    units = model.get_units(application, model_name=model_name)
    for unit in units:
        cmd = 'dpkg -l | grep {}'.format(pkg)
        out = juju_utils.remote_run(unit.entity_id, cmd, model_name=model_name)
        versions.append(out.split('\n')[0].split()[2])
    if len(set(versions)) != 1:
        raise Exception('Unexpected output from pkg version check')
    return versions[0]


def get_undercloud_env_vars():
    """Get environment specific undercloud network configuration settings.

    Get environment specific undercloud network configuration settings from
    environment variables.

    For each testing substrate, specific undercloud network configuration
    settings should be exported into the environment to enable testing on that
    substrate.

    Note: *Overcloud* settings should be declared by the test caller and should
    not be overridden here.

    Return a dictionary compatible with zaza.openstack.configure.network
    functions' expected key structure.

    Example exported environment variables:
    export default_gateway="172.17.107.1"
    export external_net_cidr="172.17.107.0/24"
    export external_dns="10.5.0.2"
    export start_floating_ip="172.17.107.200"
    export end_floating_ip="172.17.107.249"

    Example o-c-t & uosci non-standard environment variables:
    export NET_ID="a705dd0f-5571-4818-8c30-4132cc494668"
    export GATEWAY="172.17.107.1"
    export CIDR_EXT="172.17.107.0/24"
    export NAME_SERVER="10.5.0.2"
    export FIP_RANGE="172.17.107.200:172.17.107.249"

    :returns: Network environment variables
    :rtype: dict
    """
    # Handle OSCI environment variables
    # Note: TEST_* is the only prefix honored
    _vars = {}
    _vars['net_id'] = os.environ.get('TEST_NET_ID')
    _vars['external_dns'] = os.environ.get('TEST_NAME_SERVER')
    _vars['default_gateway'] = os.environ.get('TEST_GATEWAY')
    _vars['external_net_cidr'] = os.environ.get('TEST_CIDR_EXT')

    # Take FIP_RANGE and create start and end floating ips
    _fip_range = os.environ.get('TEST_FIP_RANGE')
    if _fip_range is not None and ':' in _fip_range:
        _vars['start_floating_ip'] = os.environ.get(
            'TEST_FIP_RANGE').split(':')[0]
        _vars['end_floating_ip'] = os.environ.get(
            'TEST_FIP_RANGE').split(':')[1]

    # zaza.openstack.configure.network functions variables still take priority
    # for local testing. Override OSCI settings.
    _keys = ['default_gateway',
             'start_floating_ip',
             'end_floating_ip',
             'external_dns',
             'external_net_cidr']
    for _key in _keys:
        _val = os.environ.get(_key)
        if _val:
            _vars[_key] = _val

    # Remove keys and items with a None value
    for k, v in list(_vars.items()):
        if not v:
            del _vars[k]

    return _vars


def get_yaml_config(config_file):
    """Return configuration from YAML file.

    :param config_file: Configuration file name
    :type config_file: string
    :returns: Dictionary of configuration
    :rtype: dict
    """
    # Note in its original form get_mojo_config it would do a search pattern
    # through mojo stage directories. This version assumes the yaml file is in
    # the pwd.
    logging.info('Using config %s' % (config_file))
    return yaml.safe_load(open(config_file, 'r').read())


def run_post_upgrade_functions(post_upgrade_functions):
    """Execute list supplied functions.

    :param post_upgrade_functions: List of functions
    :type post_upgrade_functions: [function, function, ...]
    """
    if post_upgrade_functions:
        for func in post_upgrade_functions:
            logging.info("Running {}".format(func))
            cl_utils.get_class(func)()


def series_upgrade_non_leaders_first(application, from_series="trusty",
                                     to_series="xenial",
                                     completed_machines=[],
                                     post_upgrade_functions=None):
    """Series upgrade non leaders first.

    Wrap all the functionality to handle series upgrade for charms
    which must have non leaders upgraded first.

    :param application: Name of application to upgrade series
    :type application: str
    :param from_series: The series from which to upgrade
    :type from_series: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param completed_machines: List of completed machines which do no longer
                               require series upgrade.
    :type completed_machines: list
    :returns: None
    :rtype: None
    """
    status = model.get_status().applications[application]
    leader = None
    non_leaders = []
    for unit in status["units"]:
        if status["units"][unit].get("leader"):
            leader = unit
        else:
            non_leaders.append(unit)

    # Series upgrade the non-leaders first
    for unit in non_leaders:
        machine = status["units"][unit]["machine"]
        if machine not in completed_machines:
            logging.info("Series upgrade non-leader unit: {}"
                         .format(unit))
            series_upgrade(unit, machine,
                           from_series=from_series, to_series=to_series,
                           origin=None,
                           post_upgrade_functions=post_upgrade_functions)
            run_post_upgrade_functions(post_upgrade_functions)
            completed_machines.append(machine)
        else:
            logging.info("Skipping unit: {}. Machine: {} already upgraded. "
                         .format(unit, machine, application))
            model.block_until_all_units_idle()

    # Series upgrade the leader
    machine = status["units"][leader]["machine"]
    logging.info("Series upgrade leader: {}".format(leader))
    if machine not in completed_machines:
        series_upgrade(leader, machine,
                       from_series=from_series, to_series=to_series,
                       origin=None,
                       post_upgrade_functions=post_upgrade_functions)
        completed_machines.append(machine)
    else:
        logging.info("Skipping unit: {}. Machine: {} already upgraded."
                     .format(unit, machine, application))
        model.block_until_all_units_idle()


def series_upgrade_application(application, pause_non_leader_primary=True,
                               pause_non_leader_subordinate=True,
                               from_series="trusty", to_series="xenial",
                               origin='openstack-origin',
                               completed_machines=[],
                               files=None, workaround_script=None,
                               post_upgrade_functions=None):
    """Series upgrade application.

    Wrap all the functionality to handle series upgrade for a given
    application. Including pausing non-leader units.

    :param application: Name of application to upgrade series
    :type application: str
    :param pause_non_leader_primary: Whether the non-leader applications should
                                     be paused
    :type pause_non_leader_primary: bool
    :param pause_non_leader_subordinate: Whether the non-leader subordinate
                                         hacluster applications should be
                                         paused
    :type pause_non_leader_subordinate: bool
    :param from_series: The series from which to upgrade
    :type from_series: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param origin: The configuration setting variable name for changing origin
                   source. (openstack-origin or source)
    :type origin: str
    :param completed_machines: List of completed machines which do no longer
                               require series upgrade.
    :type completed_machines: list
    :param files: Workaround files to scp to unit under upgrade
    :type files: list
    :param workaround_script: Workaround script to run during series upgrade
    :type workaround_script: str
    :returns: None
    :rtype: None
    """
    status = model.get_status().applications[application]

    # For some applications (percona-cluster) the leader unit must upgrade
    # first. For API applications the non-leader haclusters must be paused
    # before upgrade. Finally, for some applications this is arbitrary but
    # generalized.
    leader = None
    non_leaders = []
    for unit in status["units"]:
        if status["units"][unit].get("leader"):
            leader = unit
        else:
            non_leaders.append(unit)

    # Pause the non-leaders
    for unit in non_leaders:
        if pause_non_leader_subordinate:
            if status["units"][unit].get("subordinates"):
                for subordinate in status["units"][unit]["subordinates"]:
                    _app = subordinate.split('/')[0]
                    if _app in SUBORDINATE_PAUSE_RESUME_BLACKLIST:
                        logging.info("Skipping pausing {} - blacklisted"
                                     .format(subordinate))
                    else:
                        logging.info("Pausing {}".format(subordinate))
                        model.run_action(
                            subordinate, "pause", action_params={})
        if pause_non_leader_primary:
            logging.info("Pausing {}".format(unit))
            model.run_action(unit, "pause", action_params={})

    machine = status["units"][leader]["machine"]
    # Series upgrade the leader
    logging.info("Series upgrade leader: {}".format(leader))
    if machine not in completed_machines:
        series_upgrade(leader, machine,
                       from_series=from_series, to_series=to_series,
                       origin=origin, workaround_script=workaround_script,
                       files=files,
                       post_upgrade_functions=post_upgrade_functions)
        completed_machines.append(machine)
    else:
        logging.info("Skipping unit: {}. Machine: {} already upgraded."
                     "But setting origin on the application {}"
                     .format(unit, machine, application))
        logging.info("Set origin on {}".format(application))
        set_origin(application, origin)
        model.block_until_all_units_idle()

    # Series upgrade the non-leaders
    for unit in non_leaders:
        machine = status["units"][unit]["machine"]
        if machine not in completed_machines:
            logging.info("Series upgrade non-leader unit: {}"
                         .format(unit))
            series_upgrade(unit, machine,
                           from_series=from_series, to_series=to_series,
                           origin=origin, workaround_script=workaround_script,
                           files=files,
                           post_upgrade_functions=post_upgrade_functions)
            completed_machines.append(machine)
        else:
            logging.info("Skipping unit: {}. Machine: {} already upgraded. "
                         "But setting origin on the application {}"
                         .format(unit, machine, application))
            logging.info("Set origin on {}".format(application))
            set_origin(application, origin)
            model.block_until_all_units_idle()


def series_upgrade(unit_name, machine_num,
                   from_series="trusty", to_series="xenial",
                   origin='openstack-origin',
                   files=None, workaround_script=None,
                   post_upgrade_functions=None):
    """Perform series upgrade on a unit.

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
    :param files: Workaround files to scp to unit under upgrade
    :type files: list
    :param workaround_script: Workaround script to run during series upgrade
    :type workaround_script: str
    :returns: None
    :rtype: None
    """
    logging.info("Series upgrade {}".format(unit_name))
    application = unit_name.split('/')[0]
    set_dpkg_non_interactive_on_unit(unit_name)
    dist_upgrade(unit_name)
    model.block_until_all_units_idle()
    logging.info("Prepare series upgrade on {}".format(machine_num))
    model.prepare_series_upgrade(machine_num, to_series=to_series)
    logging.info("Waiting for workload status 'blocked' on {}"
                 .format(unit_name))
    model.block_until_unit_wl_status(unit_name, "blocked")
    logging.info("Waiting for model idleness")
    model.block_until_all_units_idle()
    wrap_do_release_upgrade(unit_name, from_series=from_series,
                            to_series=to_series, files=files,
                            workaround_script=workaround_script)
    logging.info("Reboot {}".format(unit_name))
    reboot(unit_name)
    logging.info("Waiting for workload status 'blocked' on {}"
                 .format(unit_name))
    model.block_until_unit_wl_status(unit_name, "blocked")
    logging.info("Waiting for model idleness")
    model.block_until_all_units_idle()
    logging.info("Set origin on {}".format(application))
    # Allow for charms which have neither source nor openstack-origin
    if origin:
        set_origin(application, origin)
    model.block_until_all_units_idle()
    logging.info("Complete series upgrade on {}".format(machine_num))
    model.complete_series_upgrade(machine_num)
    model.block_until_all_units_idle()
    logging.info("Running run_post_upgrade_functions {}".format(
        post_upgrade_functions))
    run_post_upgrade_functions(post_upgrade_functions)
    logging.info("Waiting for workload status 'active' on {}"
                 .format(unit_name))
    model.block_until_unit_wl_status(unit_name, "active")
    model.block_until_all_units_idle()
    # This step may be performed by juju in the future
    logging.info("Set series on {} to {}".format(application, to_series))
    model.set_series(application, to_series)


def set_origin(application, origin='openstack-origin', pocket='distro'):
    """Set the configuration option for origin source.

    :param application: Name of application to upgrade series
    :type application: str
    :param origin: The configuration setting variable name for changing origin
                   source. (openstack-origin or source)
    :type origin: str
    :param pocket: Origin source cloud pocket.
                   i.e. 'distro' or 'cloud:xenial-newton'
    :type pocket: str
    :returns: None
    :rtype: None
    """
    logging.info("Set origin on {} to {}".format(application, origin))
    model.set_application_config(application, {origin: pocket})


def wrap_do_release_upgrade(unit_name, from_series="trusty",
                            to_series="xenial",
                            files=None, workaround_script=None):
    """Wrap do release upgrade.

    In a production environment this step would be run administratively.
    For testing purposes we need this automated.

    :param unit_name: Unit Name
    :type unit_name: str
    :param from_series: The series from which to upgrade
    :type from_series: str
    :param to_series: The series to which to upgrade
    :type to_series: str
    :param files: Workaround files to scp to unit under upgrade
    :type files: list
    :param workaround_script: Workaround script to run during series upgrade
    :type workaround_script: str
    :returns: None
    :rtype: None
    """
    # Pre upgrade hacks
    # There are a few necessary hacks to accomplish an automated upgrade
    # to overcome some packaging bugs.
    # Copy scripts
    if files:
        logging.info("SCP files")
        for _file in files:
            logging.info("SCP {}".format(_file))
            model.scp_to_unit(unit_name, _file, os.path.basename(_file))

    # Run Script
    if workaround_script:
        logging.info("Running workaround script")
        run_via_ssh(unit_name, workaround_script)

    # Actually do the do_release_upgrade
    do_release_upgrade(unit_name)


def run_via_ssh(unit_name, cmd):
    """Run command on unit via ssh.

    For executing commands on units when the juju agent is down.

    :param unit_name: Unit Name
    :param cmd: Command to execute on remote unit
    :type cmd: str
    :returns: None
    :rtype: None
    """
    if "sudo" not in cmd:
        cmd = "sudo {}".format(cmd)
    cmd = ['juju', 'ssh', unit_name, cmd]
    logging.info("Running {} on {}".format(cmd, unit_name))
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        logging.warn("Failed command {} on {}".format(cmd, unit_name))
        logging.warn(e)


def dist_upgrade(unit_name):
    """Run dist-upgrade on unit after update package db.

    :param unit_name: Unit Name
    :type unit_name: str
    :returns: None
    :rtype: None
    """
    logging.info('Updating package db ' + unit_name)
    update_cmd = 'sudo apt update'
    model.run_on_unit(unit_name, update_cmd)

    logging.info('Updating existing packages ' + unit_name)
    dist_upgrade_cmd = (
        """sudo DEBIAN_FRONTEND=noninteractive apt --assume-yes """
        """-o "Dpkg::Options::=--force-confdef" """
        """-o "Dpkg::Options::=--force-confold" dist-upgrade""")
    model.run_on_unit(unit_name, dist_upgrade_cmd)


def check_commands_on_units(commands, units):
    """Check that all commands in a list exit zero on all units in a list.

    :param commands:  list of bash commands
    :param units:  list of unit pointers
    :returns: None if successful; Failure message otherwise
    """
    logging.debug('Checking exit codes for {} commands on {} '
                  'units...'.format(len(commands),
                                    len(units)))

    for u in units:
        for cmd in commands:
            output = model.run_on_unit(u.entity_id, cmd)
            if int(output['Code']) == 0:
                logging.debug('{} `{}` returned {} '
                              '(OK)'.format(u.entity_id,
                                            cmd, output['Code']))
            else:
                return ('{} `{}` returned {} '
                        '{}'.format(u.entity_id,
                                    cmd, output['Code'], output))
    return None


def do_release_upgrade(unit_name):
    """Run do-release-upgrade noninteractive.

    :param unit_name: Unit Name
    :type unit_name: str
    :returns: None
    :rtype: None
    """
    logging.info('Upgrading ' + unit_name)
    # NOTE: It is necessary to run this via juju ssh rather than juju run due
    # to timeout restrictions and error handling.
    cmd = ['juju', 'ssh', unit_name, 'sudo', 'DEBIAN_FRONTEND=noninteractive',
           'do-release-upgrade', '-f', 'DistUpgradeViewNonInteractive']
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        logging.warn("Failed do-release-upgrade for {}".format(unit_name))
        logging.warn(e)


def reboot(unit_name):
    """Reboot unit.

    :param unit_name: Unit Name
    :type unit_name: str
    :returns: None
    :rtype: None
    """
    # NOTE: When used with series upgrade the agent will be down.
    # Even juju run will not work
    cmd = ['juju', 'ssh', unit_name, 'sudo', 'reboot', '&&', 'exit']
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        logging.info(e)
        pass


def set_dpkg_non_interactive_on_unit(
        unit_name, apt_conf_d="/etc/apt/apt.conf.d/50unattended-upgrades"):
    """Set dpkg options on unit.

    :param unit_name: Unit Name
    :type unit_name: str
    :param apt_conf_d: Apt.conf file to update
    :type apt_conf_d: str
    """
    DPKG_NON_INTERACTIVE = 'DPkg::options { "--force-confdef"; };'
    # Check if the option exists. If not, add it to the apt.conf.d file
    cmd = ("grep '{option}' {file_name} || echo '{option}' >> {file_name}"
           .format(option=DPKG_NON_INTERACTIVE, file_name=apt_conf_d))
    model.run_on_unit(unit_name, cmd)


def get_process_id_list(unit_name, process_name,
                        expect_success=True):
    """Get a list of process ID(s).

    Get a list of process ID(s) from a single sentry juju unit
    for a single process name.

    :param unit_name: Amulet sentry instance (juju unit)
    :param process_name: Process name
    :param expect_success: If False, expect the PID to be missing,
        raise if it is present.
    :returns: List of process IDs
    :raises: zaza_exceptions.ProcessIdsFailed
    """
    cmd = 'pidof -x "{}"'.format(process_name)
    if not expect_success:
        cmd += " || exit 0 && exit 1"
    results = model.run_on_unit(unit_name=unit_name, command=cmd)
    code = results.get("Code", 1)
    try:
        code = int(code)
    except ValueError:
        code = 1
    error = results.get("Stderr")
    output = results.get("Stdout")
    if code != 0:
        msg = ('{} `{}` returned {} '
               '{} with error {}'.format(unit_name, cmd, code, output, error))
        raise zaza_exceptions.ProcessIdsFailed(msg)
    return str(output).split()


def get_unit_process_ids(unit_processes, expect_success=True):
    """Get unit process ID(s).

    Construct a dict containing unit sentries, process names, and
    process IDs.

    :param unit_processes: A dictionary of unit names
        to list of process names.
    :param expect_success: if False expect the processes to not be
        running, raise if they are.
    :returns: Dictionary of unit names to dictionary
        of process names to PIDs.
    :raises: zaza_exceptions.ProcessIdsFailed
    """
    pid_dict = {}
    for unit_name, process_list in unit_processes.items():
        pid_dict[unit_name] = {}
        for process in process_list:
            pids = get_process_id_list(
                unit_name, process, expect_success=expect_success)
            pid_dict[unit_name].update({process: pids})
    return pid_dict


def validate_unit_process_ids(expected, actual):
    """Validate process id quantities for services on units.

    :returns: True if the PIDs are validated, raises an exception
        if it is not the case.
    :raises: zaza_exceptions.UnitCountMismatch
    :raises: zaza_exceptions.UnitNotFound
    :raises: zaza_exceptions.ProcessNameCountMismatch
    :raises: zaza_exceptions.ProcessNameMismatch
    :raises: zaza_exceptions.PIDCountMismatch
    """
    logging.debug('Checking units for running processes...')
    logging.debug('Expected PIDs: {}'.format(expected))
    logging.debug('Actual PIDs: {}'.format(actual))

    if len(actual) != len(expected):
        msg = ('Unit count mismatch.  expected, actual: {}, '
               '{} '.format(len(expected), len(actual)))
        raise zaza_exceptions.UnitCountMismatch(msg)

    for (e_unit_name, e_proc_names) in expected.items():
        if e_unit_name in actual.keys():
            a_proc_names = actual[e_unit_name]
        else:
            msg = ('Expected unit ({}) not found in actual dict data.'.
                   format(e_unit_name))
            raise zaza_exceptions.UnitNotFound(msg)

        if len(e_proc_names.keys()) != len(a_proc_names.keys()):
            msg = ('Process name count mismatch.  expected, actual: {}, '
                   '{}'.format(len(expected), len(actual)))
            raise zaza_exceptions.ProcessNameCountMismatch(msg)

        for (e_proc_name, e_pids), (a_proc_name, a_pids) in \
                zip(e_proc_names.items(), a_proc_names.items()):
            if e_proc_name != a_proc_name:
                msg = ('Process name mismatch.  expected, actual: {}, '
                       '{}'.format(e_proc_name, a_proc_name))
                raise zaza_exceptions.ProcessNameMismatch(msg)

            a_pids_length = len(a_pids)
            fail_msg = ('PID count mismatch. {} ({}) expected, actual: '
                        '{}, {} ({})'.format(e_unit_name, e_proc_name,
                                             e_pids, a_pids_length,
                                             a_pids))

            # If expected is a list, ensure at least one PID quantity match
            if isinstance(e_pids, list) and \
                    a_pids_length not in e_pids:
                raise zaza_exceptions.PIDCountMismatch(fail_msg)
            # If expected is not bool and not list,
            # ensure PID quantities match
            elif not isinstance(e_pids, bool) and \
                    not isinstance(e_pids, list) and \
                    a_pids_length != e_pids:
                raise zaza_exceptions.PIDCountMismatch(fail_msg)
            # If expected is bool True, ensure 1 or more PIDs exist
            elif isinstance(e_pids, bool) and \
                    e_pids is True and a_pids_length < 1:
                raise zaza_exceptions.PIDCountMismatch(fail_msg)
            # If expected is bool False, ensure 0 PIDs exist
            elif isinstance(e_pids, bool) and \
                    e_pids is False and a_pids_length != 0:
                raise zaza_exceptions.PIDCountMismatch(fail_msg)
            else:
                logging.debug('PID check OK: {} {} {}: '
                              '{}'.format(e_unit_name, e_proc_name,
                                          e_pids, a_pids))
    return True


def get_ubuntu_release(ubuntu_name):
    """Get index of Ubuntu release.

    Returns the index of the name of the Ubuntu release in
        UBUNTU_OPENSTACK_RELEASE.

    :param ubuntu_name: Name of the Ubuntu release.
    :type ubuntu_name: string
    :returns: Index of the Ubuntu release
    :rtype: integer
    :raises: zaza_exceptions.UbuntuReleaseNotFound
    """
    ubuntu_releases = list(UBUNTU_OPENSTACK_RELEASE.keys())
    try:
        index = ubuntu_releases.index(ubuntu_name)
    except ValueError:
        msg = ('Could not find Ubuntu release {} in {}'.
               format(ubuntu_name, UBUNTU_OPENSTACK_RELEASE))
        raise zaza_exceptions.UbuntuReleaseNotFound(msg)
    return index


def get_file_contents(unit, f):
    """Get contents of a file on a remote unit."""
    return model.run_on_unit(unit.entity_id,
                             "cat {}".format(f))['Stdout']


def is_port_open(port, address):
        """Determine if TCP port is accessible.

        Connect to the MySQL port on the VIP.

        :param port: Port number
        :type port: str
        :param address: IP address
        :type port: str
        :returns: True if port is reachable
        :rtype: boolean
        """
        try:
            telnetlib.Telnet(address, port)
            return True
        except socket.error as e:
            if e.errno == 113:
                logging.error("could not connect to {}:{}"
                              .format(address, port))
            if e.errno == 111:
                logging.error("connection refused connecting"
                              " to {}:{}".format(address, port))
            return False


def port_knock_units(units, port=22, expect_success=True):
    """Check if specific port is open on units.

    Open a TCP socket to check for a listening sevice on each listed juju unit.
    :param units: list of unit pointers
    :param port: TCP port number, default to 22
    :param timeout: Connect timeout, default to 15 seconds
    :expect_success: True by default, set False to invert logic
    :returns: None if successful, Failure message otherwise
    """
    for u in units:
        host = u.public_address
        connected = is_port_open(port, host)
        if not connected and expect_success:
            return 'Socket connect failed.'
        elif connected and not expect_success:
            return 'Socket connected unexpectedly.'


def get_series(unit):
    """Ubuntu release name running on unit."""
    result = model.run_on_unit(unit.entity_id,
                               "lsb_release -cs")
    return result['Stdout'].strip()


def systemctl(unit, service, command="restart"):
    """Run systemctl command on a unit.

    :param unit: Unit object or unit name
    :type unit: Union[Unit,string]
    :param service: Name of service to act on
    :type service: string
    :param command: Name of command. i.e. start, stop, restart
    :type command: string
    :raises: AssertionError if the command is unsuccessful
    :returns: None if successful
    """
    cmd = "/bin/systemctl {} {}".format(command, service)

    # Check if this is a unit object or string name of a unit
    try:
        unit.entity_id
    except AttributeError:
        unit = model.get_unit_from_name(unit)

    result = model.run_on_unit(
        unit.entity_id, cmd)
    assert int(result['Code']) == 0, (
        "{} of {} on {} failed".format(command, service, unit.entity_id))


def get_mojo_cacert_path():
    """Retrieve cacert from Mojo storage location.

    :returns: Path to cacert
    :rtype: str
    :raises: zaza_exceptions.CACERTNotFound
    :raises: :class:`zaza_exceptions.CACERTNotfound`
    """
    try:
        cert_dir = os.environ['MOJO_LOCAL_DIR']
    except KeyError:
        raise zaza_exceptions.CACERTNotFound(
            "Could not find cacert.pem, MOJO_LOCAL_DIR unset")
    cacert = os.path.join(cert_dir, 'cacert.pem')
    if os.path.exists(cacert):
        return cacert
    else:
        raise zaza_exceptions.CACERTNotFound("Could not find cacert.pem")
