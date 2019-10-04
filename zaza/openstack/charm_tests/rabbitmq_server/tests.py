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

"""RabbitMQ Testing."""

import json
import logging
import time
import uuid

import juju
import tenacity
import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.generic as generic_utils

from charmhelpers.core.host import CompareHostReleases

from zaza.openstack.utilities.generic import (
    get_series,
    get_client_series,
)

from . import utils as rmq_utils
from .utils import RmqNoMessageException


class RmqTests(test_utils.OpenStackBaseTest):
    """Zaza tests on a basic rabbitmq cluster deployment."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(RmqTests, cls).setUpClass()

    def _get_uuid_epoch_stamp(self):
        """Return a string based on uuid4 and epoch time.

        Useful in generating test messages which need to be unique-ish.
        """
        return '[{}-{}]'.format(uuid.uuid4(), time.time())

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(RmqNoMessageException),
        wait=tenacity.wait_fixed(10),
        stop=tenacity.stop_after_attempt(2))
    def _retry_get_amqp_message(self, check_unit, ssl=None, port=None):
        return rmq_utils.get_amqp_message_by_unit(check_unit,
                                                  ssl=ssl,
                                                  port=port)

    def _test_rmq_amqp_messages_all_units(self, units,
                                          ssl=False, port=None):
        """Reusable test to send/check amqp messages to every listed rmq unit.

        Reusable test to send amqp messages to every listed rmq
        unit. Checks every listed rmq unit for messages.
        :param units: list of units
        :returns: None if successful.  Raise on error.

        """
        # Add test user if it does not already exist
        rmq_utils.add_user(units)

        # Handle ssl (includes wait-for-cluster)
        if ssl:
            rmq_utils.configure_ssl_on(units, port=port)
        else:
            rmq_utils.configure_ssl_off(units)

        # Publish and get amqp messages in all possible unit combinations.
        # Qty of checks == (qty of units) ^ 2
        amqp_msg_counter = 1
        host_names = generic_utils.get_unit_hostnames(units)

        for dest_unit in units:
            dest_unit_name = dest_unit.entity_id
            dest_unit_host = dest_unit.public_address
            dest_unit_host_name = host_names[dest_unit_name]

            for check_unit in units:
                check_unit_name = check_unit.entity_id
                check_unit_host = check_unit.public_address
                check_unit_host_name = host_names[check_unit_name]

                amqp_msg_stamp = self._get_uuid_epoch_stamp()
                amqp_msg = ('Message {}@{} {}'.format(amqp_msg_counter,
                                                      dest_unit_host,
                                                      amqp_msg_stamp)).upper()
                # Publish amqp message
                logging.debug('Publish message to: {} '
                              '({} {})'.format(dest_unit_host,
                                               dest_unit_name,
                                               dest_unit_host_name))

                rmq_utils.publish_amqp_message_by_unit(dest_unit,
                                                       amqp_msg, ssl=ssl,
                                                       port=port)

                # Get amqp message
                logging.debug('Get message from:   {} '
                              '({} {})'.format(check_unit_host,
                                               check_unit_name,
                                               check_unit_host_name))

                amqp_msg_rcvd = self._retry_get_amqp_message(check_unit,
                                                             ssl=ssl,
                                                             port=port)

                # Validate amqp message content
                if amqp_msg == amqp_msg_rcvd:
                    logging.debug('Message {} received '
                                  'OK.'.format(amqp_msg_counter))
                else:
                    logging.error('Expected: {}'.format(amqp_msg))
                    logging.error('Actual:   {}'.format(amqp_msg_rcvd))
                    msg = 'Message {} mismatch.'.format(amqp_msg_counter)
                    raise Exception(msg)

                amqp_msg_counter += 1

        # Delete the test user
        rmq_utils.delete_user(units)

    def test_400_rmq_cluster_running_nodes(self):
        """Verify cluster status shows every cluster node as running member."""
        logging.debug('Checking that all units are in cluster_status '
                      'running nodes...')

        units = zaza.model.get_units(self.application_name)

        ret = rmq_utils.validate_cluster_running_nodes(units)
        self.assertIsNone(ret, msg=ret)

        logging.info('OK')

    def test_406_rmq_amqp_messages_all_units_ssl_off(self):
        """Send (and check) amqp messages to every rmq unit.

        Sends amqp messages to every rmq unit, and check every rmq
        unit for messages. Uses Standard amqp tcp port, no ssl.

        """
        logging.debug('Checking amqp message publish/get on all units '
                      '(ssl off)...')

        units = zaza.model.get_units(self.application_name)
        self._test_rmq_amqp_messages_all_units(units, ssl=False)
        logging.info('OK')

    def test_408_rmq_amqp_messages_all_units_ssl_on(self):
        """Send (and check) amqp messages to every rmq unit (ssl enabled).

        Sends amqp messages to every rmq unit, and check every rmq
        unit for messages. Uses Standard ssl tcp port.

        """
        units = zaza.model.get_units(self.application_name)

        # http://pad.lv/1625044
        if (CompareHostReleases(get_client_series()) >= 'xenial' and
                CompareHostReleases(get_series(units[0])) <= 'trusty'):
            logging.info('SKIP')
            logging.info('Skipping SSL tests due to client'
                         ' compatibility issues')
            return
        logging.debug('Checking amqp message publish/get on all units '
                      '(ssl on)...')

        self._test_rmq_amqp_messages_all_units(units,
                                               ssl=True, port=5671)
        logging.info('OK')

    def test_410_rmq_amqp_messages_all_units_ssl_alt_port(self):
        """Send (and check) amqp messages to every rmq unit (alt ssl port).

        Send amqp messages with ssl on, to every rmq unit and check
        every rmq unit for messages.  Custom ssl tcp port.

        """
        units = zaza.model.get_units(self.application_name)

        # http://pad.lv/1625044
        if (CompareHostReleases(get_client_series()) >= 'xenial' and
                CompareHostReleases(get_series(units[0])) <= 'trusty'):
            logging.info('SKIP')
            logging.info('Skipping SSL tests due to client'
                         ' compatibility issues')
            return
        logging.debug('Checking amqp message publish/get on all units '
                      '(ssl on)...')

        units = zaza.model.get_units(self.application_name)
        self._test_rmq_amqp_messages_all_units(units,
                                               ssl=True, port=5999)
        logging.info('OK')

    def test_412_rmq_management_plugin(self):
        """Enable and check management plugin."""
        logging.debug('Checking tcp socket connect to management plugin '
                      'port on all rmq units...')

        units = zaza.model.get_units(self.application_name)
        mgmt_port = 15672

        # Enable management plugin
        logging.debug('Enabling management_plugin charm config option...')
        config = {'management_plugin': 'True'}
        zaza.model.set_application_config('rabbitmq-server', config)
        rmq_utils.wait_for_cluster()

        # Check tcp connect to management plugin port
        max_wait = 600
        tries = 0
        ret = generic_utils.port_knock_units(units, mgmt_port)
        while ret and tries < (max_wait / 30):
            time.sleep(30)
            logging.debug('Attempt {}: {}'.format(tries, ret))
            ret = generic_utils.port_knock_units(units, mgmt_port)
            tries += 1

        self.assertIsNone(ret, msg=ret)
        logging.debug('Connect to all units (OK)')

        # Disable management plugin
        logging.debug('Disabling management_plugin charm config option...')
        config = {'management_plugin': 'False'}
        zaza.model.set_application_config('rabbitmq-server', config)
        rmq_utils.wait_for_cluster()

        # Negative check - tcp connect to management plugin port
        logging.info('Expect tcp connect fail since charm config '
                     'option is disabled.')
        tries = 0
        ret = generic_utils.port_knock_units(units,
                                             mgmt_port,
                                             expect_success=False)

        while ret and tries < (max_wait / 30):
            time.sleep(30)
            logging.debug('Attempt {}: {}'.format(tries, ret))
            ret = generic_utils.port_knock_units(units, mgmt_port,
                                                 expect_success=False)
            tries += 1

        self.assertIsNone(ret, msg=ret)
        logging.info('Confirm mgmt port closed on all units (OK)')

    @tenacity.retry(
        retry=tenacity.retry_if_result(lambda ret: ret is not None),
        # sleep for 2mins to allow 1min cron job to run...
        wait=tenacity.wait_fixed(120),
        stop=tenacity.stop_after_attempt(2))
    def _retry_check_commands_on_units(self, cmds, units):
        return generic_utils.check_commands_on_units(cmds, units)

    def test_414_rmq_nrpe_monitors(self):
        """Check rabbimq-server nrpe monitor basic functionality."""
        units = zaza.model.get_units(self.application_name)
        host_names = generic_utils.get_unit_hostnames(units)

        # check_rabbitmq monitor
        logging.debug('Checking nrpe check_rabbitmq on units...')
        cmds = ['egrep -oh /usr/local.* /etc/nagios/nrpe.d/'
                'check_rabbitmq.cfg']
        ret = self._retry_check_commands_on_units(cmds, units)
        self.assertIsNone(ret, msg=ret)

        # check_rabbitmq_queue monitor
        logging.debug('Checking nrpe check_rabbitmq_queue on units...')
        cmds = ['egrep -oh /usr/local.* /etc/nagios/nrpe.d/'
                'check_rabbitmq_queue.cfg']
        ret = self._retry_check_commands_on_units(cmds, units)
        self.assertIsNone(ret, msg=ret)

        # check dat file existence
        logging.debug('Checking nrpe dat file existence on units...')
        for u in units:
            unit_host_name = host_names[u.entity_id]

            cmds = [
                'stat /var/lib/rabbitmq/data/{}_general_stats.dat'.format(
                    unit_host_name),
                'stat /var/lib/rabbitmq/data/{}_queue_stats.dat'.format(
                    unit_host_name)
            ]

            ret = generic_utils.check_commands_on_units(cmds, [u])
            self.assertIsNone(ret, msg=ret)

        logging.info('OK')

    def test_910_pause_and_resume(self):
        """The services can be paused and resumed."""
        logging.debug('Checking pause and resume actions...')

        unit = zaza.model.get_units(self.application_name)[0]
        assert unit.workload_status == "active"

        zaza.model.run_action(unit.entity_id, "pause")
        zaza.model.block_until_unit_wl_status(unit.entity_id, "maintenance")
        unit = zaza.model.get_unit_from_name(unit.entity_id)
        assert unit.workload_status == "maintenance"

        zaza.model.run_action(unit.entity_id, "resume")
        zaza.model.block_until_unit_wl_status(unit.entity_id, "active")
        unit = zaza.model.get_unit_from_name(unit.entity_id)
        assert unit.workload_status == "active"

        rmq_utils.wait_for_cluster()
        logging.debug('OK')

    def test_911_cluster_status(self):
        """Test rabbitmqctl cluster_status action can be returned."""
        logging.debug('Checking cluster status action...')

        unit = zaza.model.get_units(self.application_name)[0]
        action = zaza.model.run_action(unit.entity_id, "cluster-status")
        self.assertIsInstance(action, juju.action.Action)

        logging.debug('OK')

    def test_912_check_queues(self):
        """Test rabbitmqctl check_queues action can be returned."""
        logging.debug('Checking cluster status action...')

        unit = zaza.model.get_units(self.application_name)[0]
        action = zaza.model.run_action(unit.entity_id, "check-queues")
        self.assertIsInstance(action, juju.action.Action)

    def test_913_list_unconsumed_queues(self):
        """Test rabbitmqctl list-unconsumed-queues action can be returned."""
        logging.debug('Checking list-unconsumed-queues action...')

        unit = zaza.model.get_units(self.application_name)[0]
        self._test_rmq_amqp_messages_all_units([unit])
        action = zaza.model.run_action(unit.entity_id,
                                       'list-unconsumed-queues')
        self.assertIsInstance(action, juju.action.Action)

        queue_count = int(action.results['unconsumed-queue-count'])
        assert queue_count > 0, 'Did not find any unconsumed queues.'

        queue_name = 'test'  # publish_amqp_message_by_unit default queue name
        for i in range(queue_count):
            queue_data = json.loads(
                action.results['unconsumed-queues'][str(i)])
            if queue_data['name'] == queue_name:
                break
        else:
            assert False, 'Did not find expected queue in result.'

        # Since we just reused _test_rmq_amqp_messages_all_units, we should
        # have created the queue if it didn't already exist, but all messages
        # should have already been consumed.
        assert queue_data['messages'] == 0, 'Found unexpected message count.'

        logging.debug('OK')

    def test_921_remove_unit(self):
        """Test if unit cleans up when removed from Rmq cluster.

        Test if a unit correctly cleans up by removing itself from the
        RabbitMQ cluster on removal

        """
        logging.debug('Checking that units correctly clean up after '
                      'themselves on unit removal...')
        config = {'min-cluster-size': '2'}
        zaza.model.set_application_config('rabbitmq-server', config)
        rmq_utils.wait_for_cluster()

        units = zaza.model.get_units(self.application_name)
        removed_unit = units[-1]
        left_units = units[:-1]

        zaza.model.run_on_unit(removed_unit.entity_id, 'hooks/stop')
        zaza.model.block_until_unit_wl_status(removed_unit.entity_id,
                                              "waiting")

        unit_host_names = generic_utils.get_unit_hostnames(left_units)
        unit_node_names = []
        for unit in unit_host_names:
            unit_node_names.append('rabbit@{}'.format(unit_host_names[unit]))
        errors = []

        for u in left_units:
            e = rmq_utils.check_unit_cluster_nodes(u, unit_node_names)
            if e:
                # NOTE: cluster status may not have been updated yet so wait a
                # little and try one more time. Need to find a better way to do
                # this.
                time.sleep(10)
                e = rmq_utils.check_unit_cluster_nodes(u, unit_node_names)
                if e:
                    errors.append(e)

        self.assertFalse(errors)
        logging.debug('OK')
