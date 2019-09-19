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

import json
import logging

import pika
import zaza.model

import ssl as libssl
import zaza.openstack.utilities.generic as generic_utils


def wait_for_cluster(model_name=None, timeout=1200):
    """Wait for rmq units extended status to show cluster readiness,
    after an optional initial sleep period.  Initial sleep is likely
    necessary to be effective following a config change, as status
    message may not instantly update to non-ready."""
    states = {
        'rabbitmq-server': {
            'workload-status-messages': 'Unit is ready and clustered'
        }
    }

    zaza.model.wait_for_application_states(model_name=model_name,
                                           states=states,
                                           timeout=timeout)


def add_user(units, username="testuser1", password="changeme"):
    """Add a user via the first rmq juju unit, check connection as
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


def get_cluster_status(unit):
    """Execute rabbitmq cluster status command on a unit and return
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
    """Parse rabbitmqctl cluster_status output string, return list of
    running rabbitmq cluster nodes.
    :param unit: unit pointer
    :returns: List containing node names of running nodes
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


def validate_cluster_running_nodes(units):
    """Check that all rmq unit hostnames are represented in the
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


def connect_amqp_by_unit(unit, ssl=False,
                         port=None, fatal=True,
                         username="testuser1", password="changeme"):
    """Establish and return a pika amqp connection to the rabbitmq service
    running on a rmq juju unit.
    :param unit: unit pointer
    :param ssl: boolean, default to False
    :param port: amqp port, use defaults if None
    :param fatal: boolean, default to True (raises on connect error)
    :param username: amqp user name, default to testuser1
    :param password: amqp user password
    :returns: pika amqp connection pointer or None if failed and non-fatal
    """
    host = unit.public_address
    unit_name = unit.entity_id

    if ssl:
        ssl_options = pika.SSLOptions(libssl.SSLContext())
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


