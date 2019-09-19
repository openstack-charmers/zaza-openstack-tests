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

import logging
import time
import uuid

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

