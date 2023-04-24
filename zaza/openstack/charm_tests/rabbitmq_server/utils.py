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

"""RabbitMQ Testing utility functions."""

import json
import logging

import pika
import tenacity
import zaza.model

import ssl as libssl
import zaza.openstack.utilities.generic as generic_utils


class RmqNoMessageException(Exception):
    """Message retrieval from Rmq resulted in no message."""

    pass


def _log_tenacity_retry(retry_state):
    logging.info('Attempt {}: {}'.format(retry_state.attempt_number,
                                         retry_state.outcome.result()))


def wait_for_cluster(model_name=None, timeout=1200):
    """Wait for Rmq cluster status to show cluster readiness.

    Wait for rmq units extended status to show cluster readiness,
    after an optional initial sleep period.  Initial sleep is likely
    necessary to be effective following a config change, as status
    message may not instantly update to non-ready.
    """
    states = {
        'rabbitmq-server': {
            'workload-status-messages': 'Unit is ready and clustered'
        }
    }

    zaza.model.wait_for_application_states(model_name=model_name,
                                           states=states,
                                           timeout=timeout)


def add_user(units, username="testuser1", password="changeme"):
    """Add a user to a RabbitMQ cluster.

    Add a user via the first rmq juju unit, check connection as
    the new user against all units.
    :param units: list of unit pointers
    :param username: amqp user name, default to testuser1
    :param password: amqp user password
    :returns: None if successful.  Raise on error.
    """
    logging.debug('Adding rmq user ({})...'.format(username))

    # Check that user does not already exist
    cmd_user_list = 'rabbitmqctl list_users'
    cmd_result = zaza.model.run_on_unit(units[0].entity_id, cmd_user_list)
    output = cmd_result['Stdout'].strip()
    if username in output:
        logging.warning('User ({}) already exists, returning '
                        'gracefully.'.format(username))
        return

    perms = '".*" ".*" ".*"'
    cmds = ['rabbitmqctl add_user {} {}'.format(username, password),
            'rabbitmqctl set_permissions {} {}'.format(username, perms)]

    # Add user via first unit
    for cmd in cmds:
        cmd_result = zaza.model.run_on_unit(units[0].entity_id, cmd)
        output = cmd_result['Stdout'].strip()

    # Check connection against the other units
    logging.debug('Checking user connect against units...')
    for u in units:
        connection = connect_amqp_by_unit(u, ssl=False,
                                          username=username,
                                          password=password)
        connection.close()


def delete_user(units, username="testuser1"):
    """Delete a user from a RabbitMQ cluster.

    Delete a rabbitmq user via the first rmq juju unit.
    :param units: list of unit pointers
    :param username: amqp user name, default to testuser1
    :param password: amqp user password
    :returns: None if successful or no such user.
    """
    logging.debug('Deleting rmq user ({})...'.format(username))

    # Check that the user exists
    cmd_user_list = 'rabbitmqctl list_users'
    output = zaza.model.run_on_unit(units[0].entity_id,
                                    cmd_user_list)['Stdout'].strip()

    if username not in output:
        logging.warning('User ({}) does not exist, returning '
                        'gracefully.'.format(username))
        return

    # Delete the user
    cmd_user_del = 'rabbitmqctl delete_user {}'.format(username)
    output = zaza.model.run_on_unit(units[0].entity_id, cmd_user_del)


def is_rabbitmq_version_ge_382(unit):
    """Test is the rabbitmq version on the :param:`unit` is 3.8.2+.

    Returns True if the rabbitmq_server version installed on the :param:`unit`
    is >= 3.8.2

    :param unit: the unit to test
    :type unit: :class:`juju.model.ModelEntity`
    :returns: True if the server is 3.8.2 or later
    :rtype: Boolean
    """
    cmd = 'rabbitmqctl version'
    output = zaza.model.run_on_unit(unit.entity_id, cmd)['Stdout'].strip()
    logging.debug('{} rabbitmq version:{}'.format(unit.entity_id, output))
    try:
        return tuple(map(int, output.split('.')[:3])) >= (3, 8, 2)
    except Exception:
        return False


def get_cluster_status(unit):
    """Get RabbitMQ cluster status output.

    Execute rabbitmq cluster status command on a unit and return
    the full output.
    :param unit: unit
    :returns: String containing console output of cluster status command
    """
    cmd = 'rabbitmqctl cluster_status'
    output = zaza.model.run_on_unit(unit.entity_id, cmd)['Stdout'].strip()
    logging.debug('{} cluster_status:\n{}'.format(
        unit.entity_id, output))
    return str(output)


def get_cluster_running_nodes(unit):
    """Get a list of RabbitMQ cluster's running nodes.

    Return a list of the running rabbitmq cluster nodes from the specified
    unit.

    NOTE: this calls one of two functions depending on whether the installed
    version on the unit is 3.8.2 and newer, or older.  If newer then the
    --formatter=json option is used to simplify parsing of the cluster data.

    :param unit: the unit to fetch running nodes list from
    :type unit: :class:`juju.model.ModelEntity`
    :returns: List containing node names of running nodes
    :rtype: List[str]
    """
    if is_rabbitmq_version_ge_382(unit):
        return _get_cluster_running_nodes_38(unit)
    else:
        return _get_cluster_running_nodes_pre_38(unit)


def _get_cluster_running_nodes_pre_38(unit):
    """Get a list of RabbitMQ cluster's running nodes (pre 3.8.2).

    Parse rabbitmqctl cluster_status output string, return list of
    running rabbitmq cluster nodes.

    :param unit: unit pointer
    :type unit: :class:`juju.model.ModelEntity`
    :returns: List containing node names of running nodes
    :rtype: List[str]
    """
    # NOTE(beisner): rabbitmqctl cluster_status output is not
    # json-parsable, do string chop foo, then json.loads that.
    str_stat = get_cluster_status(unit)
    if 'running_nodes' in str_stat:
        pos_start = str_stat.find("{running_nodes,") + 15
        pos_end = str_stat.find("]},", pos_start) + 1
        str_run_nodes = str_stat[pos_start:pos_end].replace("'", '"')
        run_nodes = json.loads(str_run_nodes)
        return run_nodes
    else:
        return []


def _get_cluster_running_nodes_38(unit):
    """Get a list of RabbitMQ cluster's running nodes (3.8.2+).

    Return a list of the running rabbitmq cluster nodes from the specified
    unit.

    :param unit: the unit to fetch running nodes list from
    :type unit: :class:`juju.model.ModelEntity`
    :returns: List containing node names of running nodes
    :rtype: List[str]
    """
    cmd = 'rabbitmqctl cluster_status --formatter=json'
    output = zaza.model.run_on_unit(unit.entity_id, cmd)['Stdout'].strip()
    decoded = json.loads(output)
    return decoded['running_nodes']


def validate_cluster_running_nodes(units):
    """Check all rmq unit hostnames are represented in cluster_status.

    Check that all rmq unit hostnames are represented in the
    cluster_status output of all units.
    :param host_names: dict of juju unit names to host names
    :param units: list of unit pointers (all rmq units)
    :returns: None if successful, otherwise return error message
    """
    host_names = generic_utils.get_unit_hostnames(units)
    errors = []

    # Query every unit for cluster_status running nodes
    for query_unit in units:
        query_unit_name = query_unit.entity_id
        running_nodes = get_cluster_running_nodes(query_unit)

        # Confirm that every unit is represented in the queried unit's
        # cluster_status running nodes output.
        for validate_unit in units:
            val_host_name = host_names[validate_unit.entity_id]
            val_node_name = 'rabbit@{}'.format(val_host_name)

            if val_node_name not in running_nodes:
                errors.append('Cluster member check failed on {}: {} not '
                              'in {}\n'.format(query_unit_name,
                                               val_node_name,
                                               running_nodes))
    if errors:
        return ''.join(errors)


def validate_ssl_enabled_units(units, port=None):
    """Check that ssl is enabled on rmq juju units.

    :param units: list of all rmq units
    :param port: optional ssl port override to validate
    :returns: None if successful, otherwise return error message
    """
    for u in units:
        if not is_ssl_enabled_on_unit(u, port=port):
            return ('Unexpected condition:  ssl is disabled on unit '
                    '({})'.format(u.info['unit_name']))
    return None


def validate_ssl_disabled_units(units):
    """Check that ssl is enabled on listed rmq juju units.

    :param units: list of all rmq units
    :returns: True if successful.  Raise on error.
    """
    for u in units:
        if is_ssl_enabled_on_unit(u):
            return ('Unexpected condition:  ssl is enabled on unit '
                    '({})'.format(u.entity_id))
    return None


@tenacity.retry(
    retry=tenacity.retry_if_result(lambda errors: bool(errors)),
    wait=tenacity.wait_fixed(4),
    stop=tenacity.stop_after_attempt(15),
    after=_log_tenacity_retry)
def _retry_validate_ssl_enabled_units(units, port=None):
    return validate_ssl_enabled_units(units, port=port)


def configure_ssl_on(units, model_name=None, port=None):
    """Turn RabbitMQ charm SSL config option on.

    Turn ssl charm config option on, with optional non-default
    ssl port specification.  Confirm that it is enabled on every
    unit.
    :param units: list of units
    :param port: amqp port, use defaults if None
    :returns: None if successful.  Raise on error.
    """
    logging.debug('Setting ssl charm config option:  on')

    # Enable RMQ SSL
    config = {'ssl': 'on'}
    if port:
        config['ssl_port'] = str(port)

    zaza.model.set_application_config('rabbitmq-server',
                                      config,
                                      model_name=model_name)

    # Wait for unit status
    wait_for_cluster(model_name)

    ret = _retry_validate_ssl_enabled_units(units, port=port)
    if ret:
        raise Exception(ret)


@tenacity.retry(
    retry=tenacity.retry_if_result(lambda errors: bool(errors)),
    wait=tenacity.wait_fixed(4),
    stop=tenacity.stop_after_attempt(15),
    after=_log_tenacity_retry)
def _retry_validate_ssl_disabled_units(units):
    return validate_ssl_disabled_units(units)


def configure_ssl_off(units, model_name=None, max_wait=60):
    """Turn RabbitMQ charm SSL config option off.

    Turn ssl charm config option off, confirm that it is disabled
    on every unit.
    :param units: list of units
    :param max_wait: maximum time to wait in seconds to confirm
    :returns: None if successful.  Raise on error.
    """
    logging.debug('Setting ssl charm config option:  off')

    # Disable RMQ SSL
    config = {'ssl': 'off'}
    zaza.model.set_application_config('rabbitmq-server',
                                      config,
                                      model_name=model_name)

    # Wait for unit status
    wait_for_cluster(model_name)

    ret = _retry_validate_ssl_disabled_units(units)

    if ret:
        raise Exception(ret)


def is_ssl_enabled_on_unit(unit, port=None):
    """Check a single juju rmq unit for ssl and port in the config file."""
    host = zaza.model.get_unit_public_address(unit)
    unit_name = unit.entity_id

    conf_file = '/etc/rabbitmq/rabbitmq.conf'
    conf_contents = str(generic_utils.get_file_contents(unit,
                                                        conf_file))
    # Fallback to old style configuration file for
    # older RMQ releases if .conf is empty/not found
    if not conf_contents:
        conf_file = '/etc/rabbitmq/rabbitmq.config'
        conf_contents = str(generic_utils.get_file_contents(unit,
                                                            conf_file))
    # Checks
    conf_ssl = 'ssl' in conf_contents
    conf_port = str(port) in conf_contents

    # Port explicitly checked in config
    if port and conf_port and conf_ssl:
        logging.debug('SSL is enabled  @{}:{} '
                      '({})'.format(host, port, unit_name))
        return True
    elif port and not conf_port and conf_ssl:
        logging.debug('SSL is enabled @{} but not on port {} '
                      '({})'.format(host, port, unit_name))
        return False
    # Port not checked (useful when checking that ssl is disabled)
    elif not port and conf_ssl:
        logging.debug('SSL is enabled  @{}:{} '
                      '({})'.format(host, port, unit_name))
        return True
    elif not conf_ssl:
        logging.debug('SSL not enabled @{}:{} '
                      '({})'.format(host, port, unit_name))
        return False
    else:
        msg = ('Unknown condition when checking SSL status @{}:{} '
               '({})'.format(host, port, unit_name))
        raise ValueError(msg)


def connect_amqp_by_unit(unit, ssl=False,
                         port=None, fatal=True,
                         username="testuser1", password="changeme"):
    """Establish and return a pika amqp connection to the rabbitmq service.

    Establish and return a pika amqp connection to the rabbitmq service
    running on a rmq juju unit.
    :param unit: unit pointer
    :param ssl: boolean, default to False
    :param port: amqp port, use defaults if None
    :param fatal: boolean, default to True (raises on connect error)
    :param username: amqp user name, default to testuser1
    :param password: amqp user password
    :returns: pika amqp connection pointer or None if failed and non-fatal
    """
    host = zaza.model.get_unit_public_address(unit)
    unit_name = unit.entity_id

    if ssl:
        # TODO: when Python3.5 support is removed, investigate
        # changing protocol to PROTOCOL_TLS
        context = libssl.SSLContext(protocol=libssl.PROTOCOL_TLSv1_2)
        ssl_options = pika.SSLOptions(context)
    else:
        ssl_options = None

    # Default port logic if port is not specified
    if ssl and not port:
        port = 5671
    elif not ssl and not port:
        port = 5672

    logging.debug('Connecting to amqp on {}:{} ({}) as '
                  '{}...'.format(host, port, unit_name, username))

    try:
        # retry connections; it's possible during the testing that a
        # leader-setting-change hook will be running on the unit (which takes
        # up to 30s to run) and results in a restart of the underlying rabbitmq
        # process.  This retry get's past the restart.
        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_attempt(5),
                wait=tenacity.wait_exponential(multiplier=1, min=2, max=10)):
            with attempt:
                credentials = pika.PlainCredentials(username, password)
                parameters = pika.ConnectionParameters(host=host, port=port,
                                                       credentials=credentials,
                                                       ssl_options=ssl_options,
                                                       connection_attempts=3,
                                                       retry_delay=5,
                                                       socket_timeout=1)
                connection = pika.BlockingConnection(parameters)
                assert connection.is_open is True
                logging.debug('Connect OK')
                return connection
    except Exception as e:
        msg = ('amqp connection failed to {}:{} as '
               '{} ({})'.format(host, port, username, str(e)))
        if fatal:
            raise Exception(msg)
        else:
            logging.warn(msg)
            return None


def publish_amqp_message_by_unit(unit, message,
                                 queue="test", ssl=False,
                                 username="testuser1",
                                 password="changeme",
                                 port=None):
    """Publish an amqp message to a rmq juju unit.

    :param unit: unit pointer
    :param message: amqp message string
    :param queue: message queue, default to test
    :param username: amqp user name, default to testuser1
    :param password: amqp user password
    :param ssl: boolean, default to False
    :param port: amqp port, use defaults if None
    :returns: None.  Raises exception if publish failed.
    """
    logging.debug('Publishing message to {} queue:\n{}'.format(queue,
                                                               message))
    connection = connect_amqp_by_unit(unit, ssl=ssl,
                                      port=port,
                                      username=username,
                                      password=password)

    # NOTE(beisner): extra debug here re: pika hang potential:
    #   https://github.com/pika/pika/issues/297
    #   https://groups.google.com/forum/#!topic/rabbitmq-users/Ja0iyfF0Szw
    logging.debug('Defining channel...')
    channel = connection.channel()
    logging.debug('Declaring queue...')
    channel.queue_declare(queue=queue, auto_delete=False, durable=True)
    logging.debug('Publishing message...')
    channel.basic_publish(exchange='', routing_key=queue, body=message)
    logging.debug('Closing channel...')
    channel.close()
    logging.debug('Closing connection...')
    connection.close()


def get_amqp_message_by_unit(unit, queue="test",
                             username="testuser1",
                             password="changeme",
                             ssl=False, port=None):
    """Get an amqp message from a rmq juju unit.

    :param unit: unit pointer
    :param queue: message queue, default to test
    :param username: amqp user name, default to testuser1
    :param password: amqp user password
    :param ssl: boolean, default to False
    :param port: amqp port, use defaults if None
    :returns: amqp message body as string.  Raise if get fails.
    """
    connection = connect_amqp_by_unit(unit, ssl=ssl,
                                      port=port,
                                      username=username,
                                      password=password)
    channel = connection.channel()
    method_frame, _, body = channel.basic_get(queue)

    if method_frame:
        body = body.decode()
        logging.debug('Retreived message from {} queue:\n{}'.format(queue,
                                                                    body))
        channel.basic_ack(method_frame.delivery_tag)
        channel.close()
        connection.close()
        return body
    else:
        msg = 'No message retrieved.'
        raise RmqNoMessageException(msg)


def check_unit_cluster_nodes(unit, unit_node_names):
    """Check if unit exists in list of Rmq cluster node names.

    NOTE: this calls one of two functions depending on whether the installed
    version on the unit is 3.8.2 and newer, or older.  If newer then the
    --formatter=json option is used to simplify parsing of the cluster data.

    :param unit: the unit to fetch running nodes list from
    :type unit: :class:`juju.model.ModelEntity`
    :param unit_node_names: The unit node names to check against
    :type unit_node_names: List[str]
    :returns: List containing node names of running nodes
    :rtype: List[str]
    """
    if is_rabbitmq_version_ge_382(unit):
        return _check_unit_cluster_nodes_38(unit, unit_node_names)
    else:
        return _check_unit_cluster_nodes_pre_38(unit, unit_node_names)


def _check_unit_cluster_nodes_38(unit, unit_node_names):
    """Check if unit exists in list of Rmq cluster node names (3.8.2+).

    :param unit: the unit to fetch running nodes list from
    :type unit: :class:`juju.model.ModelEntity`
    :param unit_node_names: The unit node names to check against
    :type unit_node_names: List[str]
    :returns: List containing node names of running nodes
    :rtype: List[str]
    """
    cmd = 'rabbitmqctl cluster_status --formatter=json'
    output = zaza.model.run_on_unit(unit.entity_id, cmd)['Stdout'].strip()
    decoded = json.loads(output)
    return _post_check_unit_cluster_nodes(
        unit, decoded['disk_nodes'], unit_node_names)


def _check_unit_cluster_nodes_pre_38(unit, unit_node_names):
    """Check if unit exists in list of Rmq cluster node names (pre 3.8.2).

    :param unit: the unit to fetch running nodes list from
    :type unit: :class:`juju.model.ModelEntity`
    :param unit_node_names: The unit node names to check against
    :type unit_node_names: List[str]
    :returns: List containing node names of running nodes
    :rtype: List[str]
    """
    nodes = []
    str_stat = get_cluster_status(unit)
    # make the interesting part of rabbitmqctl cluster_status output
    # json-parseable.
    if 'nodes,[{disc,' in str_stat:
        pos_start = str_stat.find('nodes,[{disc,') + 13
        pos_end = str_stat.find(']}]},', pos_start) + 1
        str_nodes = str_stat[pos_start:pos_end].replace("'", '"')
        nodes = json.loads(str_nodes)
    return _post_check_unit_cluster_nodes(unit, nodes, unit_node_names)


def _post_check_unit_cluster_nodes(unit, nodes, unit_node_names):
    """Finish of the check_unit_cluster_nodes function (internal)."""
    unit_name = unit.entity_id
    errors = []
    for node in nodes:
        if node not in unit_node_names:
            errors.append('Cluster registration check failed on {}: '
                          '{} should not be registered with RabbitMQ '
                          'after unit removal.\n'
                          ''.format(unit_name, node))
    return errors


async def complete_cluster_series_upgrade():
    """Run the complete-cluster-series-upgrade action on the lead unit."""
    await zaza.model.async_run_action_on_leader(
        'rabbitmq-server',
        'complete-cluster-series-upgrade',
        action_params={})
