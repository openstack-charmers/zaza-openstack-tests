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


