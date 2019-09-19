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
import time
import uuid

import juju
import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.generic as generic_utils


from . import utils as rmq_utils


class RmqTests(test_utils.OpenStackBaseTest):
    """Zaza tests on a basic rabbitmq cluster deployment. Verify
       relations, service status, users and endpoint service catalog."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(RmqTests, cls).setUpClass()

    def _get_uuid_epoch_stamp(self):
        """Returns a stamp string based on uuid4 and epoch time.  Useful in
        generating test messages which need to be unique-ish."""
        return '[{}-{}]'.format(uuid.uuid4(), time.time())

    def _test_rmq_amqp_messages_all_units(self, units,
                                          ssl=False, port=None):
        """Reusable test to send amqp messages to every listed rmq unit
        and check every listed rmq unit for messages.

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

                # Wait a bit before checking for message
                time.sleep(10)

                # Get amqp message
                logging.debug('Get message from:   {} '
                              '({} {})'.format(check_unit_host,
                                               check_unit_name,
                                               check_unit_host_name))

                amqp_msg_rcvd = rmq_utils.get_amqp_message_by_unit(check_unit,
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
        """Verify that cluster status from each rmq juju unit shows
        every cluster node as a running member in that cluster."""
        logging.debug('Checking that all units are in cluster_status '
                      'running nodes...')

        units = zaza.model.get_units(self.application_name)

        ret = rmq_utils.validate_cluster_running_nodes(units)
        self.assertIsNone(ret)

        logging.info('OK\n')

    def test_406_rmq_amqp_messages_all_units_ssl_off(self):
        """Send amqp messages to every rmq unit and check every rmq unit
        for messages.  Standard amqp tcp port, no ssl."""
        logging.debug('Checking amqp message publish/get on all units '
                      '(ssl off)...')

        units = zaza.model.get_units(self.application_name)
        self._test_rmq_amqp_messages_all_units(units, ssl=False)
        logging.info('OK\n')

    def test_408_rmq_amqp_messages_all_units_ssl_on(self):
        """Send amqp messages with ssl enabled, to every rmq unit and
        check every rmq unit for messages.  Standard ssl tcp port."""
        # http://pad.lv/1625044
        # TODO: exsdev: find out if there's a function to determine unit's release
        # Otherwise run_on_unit: lsb_release -cs
        # if (CompareHostReleases(self.client_series) >= 'xenial' and
        #         CompareHostReleases(self.series) <= 'trusty'):
        #     logging.info('SKIP')
        #     logging.info('Skipping SSL tests due to client'
        #                ' compatibility issues')
        #     return
        logging.debug('Checking amqp message publish/get on all units '
                      '(ssl on)...')

        units = zaza.model.get_units(self.application_name)
        self._test_rmq_amqp_messages_all_units(units,
                                               ssl=True, port=5671)
        logging.info('OK\n')

    def test_410_rmq_amqp_messages_all_units_ssl_alt_port(self):
        """Send amqp messages with ssl on, to every rmq unit and check
        every rmq unit for messages.  Custom ssl tcp port."""
        # http://pad.lv/1625044
        # TODO: exsdev: find out if there's a function to determine unit's release
        # Otherwise run_on_unit: lsb_release -cs
        # if (CompareHostReleases(self.client_series) >= 'xenial' and
        #         CompareHostReleases(self.series) <= 'trusty'):
        #     logging.info('SKIP')
        #     logging.info('Skipping SSL tests due to client'
        #                ' compatibility issues')
        #     return
        logging.debug('Checking amqp message publish/get on all units '
                      '(ssl on)...')

        units = zaza.model.get_units(self.application_name)
        self._test_rmq_amqp_messages_all_units(units,
                                               ssl=True, port=5999)
        logging.info('OK\n')

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

        self.assertIsNone(ret)
        logging.debug('Connect to all units (OK)\n')

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

        self.assertIsNone(ret)
        logging.info('Confirm mgmt port closed on all units (OK)\n')

    def test_414_rmq_nrpe_monitors(self):
        """Check rabbimq-server nrpe monitor basic functionality."""
        units = zaza.model.get_units(self.application_name)
        host_names = generic_utils.get_unit_hostnames(units)

        # check_rabbitmq monitor
        logging.debug('Checking nrpe check_rabbitmq on units...')
        cmds = ['egrep -oh /usr/local.* /etc/nagios/nrpe.d/'
                'check_rabbitmq.cfg']
        ret = generic_utils.check_commands_on_units(cmds, units)
        self.assertIsNone(ret)

        logging.debug('Sleeping 2ms for 1m cron job to run...')
        time.sleep(120)

        # check_rabbitmq_queue monitor
        logging.debug('Checking nrpe check_rabbitmq_queue on units...')
        cmds = ['egrep -oh /usr/local.* /etc/nagios/nrpe.d/'
                'check_rabbitmq_queue.cfg']
        ret = generic_utils.check_commands_on_units(cmds, units)
        self.assertIsNone(ret)

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
            self.assertIsNone(ret)

        logging.info('OK\n')

    def test_910_pause_and_resume(self):
        """The services can be paused and resumed. """

        logging.debug('Checking pause and resume actions...')

        unit = zaza.model.get_units(self.application_name)[0]
        assert unit.workload_status == "active"

        zaza.model.run_action(unit.entity_id, "pause")
        zaza.model.block_until_unit_wl_status(unit.entity_id, "maintenance")
        # TODO: investigate possible bug (the following line is
        # required, otherwise it looks like workload_status is
        # reporting cached information, no matter how long you sleep)
        unit = zaza.model.get_unit_from_name(unit.entity_id)
        assert unit.workload_status == "maintenance"

        zaza.model.run_action(unit.entity_id, "resume")
        zaza.model.block_until_unit_wl_status(unit.entity_id, "active")
        unit = zaza.model.get_unit_from_name(unit.entity_id)
        assert unit.workload_status == "active"

        rmq_utils.wait_for_cluster()
        logging.debug('OK')

    def test_911_cluster_status(self):
        """ rabbitmqctl cluster_status action can be returned. """
        logging.debug('Checking cluster status action...')

        unit = zaza.model.get_units(self.application_name)[0]
        action = zaza.model.run_action(unit.entity_id, "cluster-status")
        self.assertIsInstance(action, juju.action.Action)

        logging.debug('OK')

    def test_912_check_queues(self):
        """ rabbitmqctl check_queues action can be returned. """
        logging.debug('Checking cluster status action...')

        unit = zaza.model.get_units(self.application_name)[0]
        action = zaza.model.run_action(unit.entity_id, "check-queues")
        self.assertIsInstance(action, juju.action.Action)

    def test_913_list_unconsumed_queues(self):
        """ rabbitmqctl list-unconsumed-queues action can be returned. """
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
