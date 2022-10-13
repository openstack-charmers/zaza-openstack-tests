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

import asyncio
import logging
import os
import socket
import subprocess
import telnetlib
import tempfile
import yaml

from zaza import model, sync_wrapper
from zaza.openstack.utilities import exceptions as zaza_exceptions
from zaza.openstack.utilities.os_versions import UBUNTU_OPENSTACK_RELEASE
from zaza.utilities import juju as juju_utils


def assertActionRanOK(action):
    """Assert that the remote action ran successfully.

    Example usage::

        self.assertActionRanOK(model.run_action(
            unit,
            'pause',
            model_name=self.model_name))

        self.assertActionRanOK(model.run_action_on_leader(
            unit,
            'pause',
            model_name=self.model_name))

    :param action: Action object to check.
    :type action: juju.action.Action
    :raises: AssertionError if the assertion fails.
    """
    if action.status != 'completed':
        msg = ("Action '{name}' exited with status '{status}': "
               "'{message}'").format(**action.data)
        raise AssertionError(msg)


def assertRemoteRunOK(run_output):
    """Use with zaza.model.run_on_unit.

    Example usage::

        self.assertRemoteRunOK(zaza.model.run_on_unit(
            unit,
            'ls /tmp/'))

    :param action: Dict returned from remote run.
    :type action: dict
    :raises: AssertionError if the assertion fails.
    """
    if int(run_output['Code']) != 0:
        raise AssertionError("Command failed: {}".format(run_output))


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


def get_unit_hostnames(units, fqdn=False):
    """Return a dict of juju unit names to hostnames."""
    host_names = {}
    for unit in units:
        cmd = 'hostname'
        if fqdn:
            cmd = cmd + ' -f'
        output = model.run_on_unit(unit.entity_id, cmd)
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


async def async_set_origin(application, origin='openstack-origin',
                           pocket='distro'):
    """Set the configuration option for origin source.

    :param application: Name of application to upgrade series
    :type application: str
    :param origin: The configuration setting variable name for changing origin
                   source. (openstack-origin or source). Use "auto" to
                   automatically detect origin variable name.
    :type origin: str
    :param pocket: Origin source cloud pocket.
                   i.e. 'distro' or 'cloud:xenial-newton'
    :type pocket: str
    :returns: None
    :rtype: None
    """
    if origin == "auto":
        config = await model.async_get_application_config(application)
        for origin in ("openstack-origin", "source"):
            if config.get(origin):
                break
        else:
            logging.warn("Failed to set origin for {} to {}, no origin config "
                         "found".format(application, origin))
            return

    logging.info("Set origin on {} to {}".format(application, pocket))
    await model.async_set_application_config(application, {origin: pocket})

set_origin = sync_wrapper(async_set_origin)


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


async def async_run_via_ssh(unit_name, cmd, raise_exceptions=False):
    """Run command on unit via ssh.

    For executing commands on units when the juju agent is down.

    :param unit_name: Unit Name
    :param cmd: Command to execute on remote unit
    :type cmd: str
    :returns: None
    :rtype: None
    """
    if "sudo" not in cmd:
        # cmd.insert(0, "sudo")
        cmd = "sudo {}".format(cmd)
    cmd = ['juju', 'ssh', unit_name, cmd]
    try:
        await check_call(cmd)
    except subprocess.CalledProcessError as e:
        logging.warn("Failed command {} on {}".format(cmd, unit_name))
        logging.warn(e)
        if raise_exceptions:
            raise e


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


async def async_reboot(unit_name):
    """Reboot unit.

    :param unit_name: Unit Name
    :type unit_name: str
    :returns: None
    :rtype: None
    """
    # NOTE: When used with series upgrade the agent will be down.
    # Even juju run will not work
    await async_run_via_ssh(unit_name, "sudo reboot && exit")


async def check_call(cmd):
    """Asynchronous function to check a subprocess call.

    :param cmd: Command to execute
    :type cmd: List[str]
    :returns: None
    :rtype: None
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    stdout = stdout.decode('utf-8')
    stderr = stderr.decode('utf-8')
    if proc.returncode != 0:
        logging.warn("STDOUT: {}".format(stdout))
        logging.warn("STDERR: {}".format(stderr))
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    else:
        if stderr:
            logging.info("STDERR: {} ({})".format(stderr, ' '.join(cmd)))
        if stdout:
            logging.info("STDOUT: {} ({})".format(stdout, ' '.join(cmd)))


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


async def async_set_dpkg_non_interactive_on_unit(
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
    await model.async_run_on_unit(unit_name, cmd)


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
        host = model.get_unit_public_address(u)
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


def attach_file_resource(application_name, resource_name,
                         file_content, file_suffix=".txt"):
    """Attaches a file as a Juju resource given the file content and suffix.

    The file content will be written into a temporary file with the given
    suffix, and it will be attached to the Juju application.

    :param application_name: Juju application name.
    :type application_name: string
    :param resource_name: Juju resource name.
    :type resource_name: string
    :param file_content: The content of the file that will be attached
    :type file_content: string
    :param file_suffix: File suffix. This should be used to set the file
        extension for applications that are sensitive to this.
    :type file_suffix: string
    :returns: None
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix=file_suffix) as fp:
        fp.write(file_content)
        fp.flush()
        model.attach_resource(
            application_name, resource_name, fp.name)


def get_leaders_and_non_leaders(application_name):
    """Get leader node and non-leader nodes.

    :returns: leader, list of non-leader
    :rtype: str, list of str
    """
    status = model.get_status().applications[application_name]
    leader = None
    non_leaders = []
    for unit in status["units"]:
        if status["units"][unit].get("leader"):
            leader = unit
        else:
            non_leaders.append(unit)
    return leader, non_leaders


def add_loop_device(unit, name='loop.img', size=10):
    """Add a loopback device to a Juju unit.

    :param unit: The unit name on which to create the device.
    :type unit: str

    :param name: The name of the file used for the loop device.
    :type unit: str

    :param size: The size in GB of the device.
    :type size: int

    :returns: The device name.
    """
    loop_name = '/home/ubuntu/{}'.format(name)
    truncate = 'truncate --size {}GB {}'.format(size, loop_name)
    losetup = 'losetup --find {}'.format(loop_name)
    lofind = 'losetup -a | grep {} | cut -f1 -d ":"'.format(loop_name)
    cmd = "sudo sh -c '{} && {} && {}'".format(truncate, losetup, lofind)
    return model.run_on_unit(unit, cmd)


def remove_loop_device(unit, device, name='loop.img'):
    """Remove a loopback device from a Juju unit.

    :param unit: The unit name from which to remove the device.
    :type unit: str

    :param device: The loop device path to be removed.
    :type unit: str

    :param name: The name of the file used for the loop device.
    :type name: str
    """
    cmd = "sudo sh -c 'losetup -d {} && rm {}'".format(device, name)
    return model.run_on_unit(unit, cmd)
