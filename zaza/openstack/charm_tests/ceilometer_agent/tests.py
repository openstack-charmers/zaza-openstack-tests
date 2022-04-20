#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
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

"""Encapsulate ceilometer-agent testing."""

import logging
import time
from gnocchiclient.v1 import client as gnocchi_client

import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class CeilometerAgentTest(test_utils.OpenStackBaseTest):
    """Encapsulate ceilometer-agent tests."""

    def tearDown(self):
        """Cleanup of VM guests."""
        self.resource_cleanup()

    def test_400_gnocchi_metrics(self):
        """Verify that ceilometer-agent publishes metrics to gnocchi."""
        current_os_release = openstack_utils.get_os_release()
        openstack_pike_or_older = (
            current_os_release <=
            openstack_utils.get_os_release('xenial_pike'))
        if openstack_pike_or_older:
            # Both the charm and Ceilometer itself had different behaviors in
            # terms of which metrics were published and how fast, which would
            # lead to a combinatorial explosion if we had to maintain test
            # expectations for these old releases.
            logging.info(
                'OpenStack Pike or older, skipping')
            return

        # ceilometer-agent-compute reports metrics for each existing VM, so at
        # least one VM is needed:
        self.RESOURCE_PREFIX = 'zaza-ceilometer-agent'
        self.launch_guest(
            'ubuntu', instance_key=glance_setup.LTS_IMAGE_NAME)

        logging.info('Instantiating gnocchi client...')
        overcloud_auth = openstack_utils.get_overcloud_auth()
        keystone = openstack_utils.get_keystone_client(overcloud_auth)
        gnocchi_ep = keystone.service_catalog.url_for(
            service_type='metric',
            interface='publicURL'
        )
        gnocchi = gnocchi_client.Client(
            session=openstack_utils.get_overcloud_keystone_session(),
            adapter_options={
                'endpoint_override': gnocchi_ep,
            }
        )

        expected_metric_names = self.__get_expected_metric_names(
            current_os_release)

        min_timeout_seconds = 500
        polling_interval_seconds = (
            openstack_utils.get_application_config_option(
                self.application_name, 'polling-interval'))
        timeout_seconds = max(10 * polling_interval_seconds,
                              min_timeout_seconds)
        logging.info('Giving ceilometer-agent {}s to publish all metrics to '
                     'gnocchi...'.format(timeout_seconds))

        max_time = time.time() + timeout_seconds
        while time.time() < max_time:
            found_metric_names = {metric['name']
                                  for metric in gnocchi.metric.list()}
            missing_metric_names = expected_metric_names - found_metric_names
            if len(missing_metric_names) == 0:
                logging.info('All expected metrics found.')
                break
            time.sleep(polling_interval_seconds)

        unexpected_found_metric_names = (
            found_metric_names - expected_metric_names)
        if len(unexpected_found_metric_names) > 0:
            logging.info(
                'Unexpected metrics '
                'published: ' + ', '.join(unexpected_found_metric_names))

        if len(missing_metric_names) > 0:
            self.fail('These metrics should have been published but '
                      "weren't: " + ', '.join(missing_metric_names))

    def __get_expected_metric_names(self, current_os_release):
        expected_metric_names = {
            'compute.instance.booting.time',
            'disk.ephemeral.size',
            'disk.root.size',
            'image.download',
            'image.serve',
            'image.size',
            'memory',
            'vcpus',
        }

        all_polsters_are_enabled = (
            openstack_utils.get_application_config_option(
                self.application_name, 'enable-all-pollsters'))

        if all_polsters_are_enabled:
            expected_metric_names |= {
                'disk.device.allocation',
                'disk.device.capacity',
                'disk.device.read.latency',
                'disk.device.usage',
                'disk.device.write.latency',
                'memory.resident',
                'memory.swap.in',
                'memory.swap.out',
                'network.incoming.packets.drop',
                'network.incoming.packets.error',
                'network.outgoing.packets.drop',
                'network.outgoing.packets.error',
            }

        openstack_queens_or_older = (
            current_os_release <=
            openstack_utils.get_os_release('bionic_queens'))
        openstack_rocky_or_older = (
            current_os_release <=
            openstack_utils.get_os_release('bionic_rocky'))
        openstack_victoria_or_older = (
            current_os_release <=
            openstack_utils.get_os_release('groovy_victoria'))

        if openstack_victoria_or_older:
            expected_metric_names |= {
                'cpu',
                'disk.device.read.bytes',
                'disk.device.read.requests',
                'disk.device.write.bytes',
                'disk.device.write.requests',
                'memory.usage',
                'network.incoming.bytes',
                'network.incoming.packets',
                'network.outgoing.bytes',
                'network.outgoing.packets',
            }

        if openstack_rocky_or_older:
            expected_metric_names |= {
                'cpu.delta',
                'cpu_util',
                'disk.device.read.bytes.rate',
                'disk.device.read.requests.rate',
                'disk.device.write.bytes.rate',
                'disk.device.write.requests.rate',
                'network.incoming.bytes.rate',
                'network.incoming.packets.rate',
                'network.outgoing.bytes.rate',
                'network.outgoing.packets.rate',
            }
            if all_polsters_are_enabled:
                expected_metric_names |= {
                    'disk.allocation',
                    'disk.capacity',
                    'disk.read.bytes',
                    'disk.read.bytes.rate',
                    'disk.read.requests',
                    'disk.read.requests.rate',
                    'disk.usage',
                    'disk.write.bytes',
                    'disk.write.bytes.rate',
                    'disk.write.requests',
                    'disk.write.requests.rate',
                }

        if openstack_queens_or_older:
            expected_metric_names |= {
                'cpu_l3_cache',
                'disk.allocation',
                'disk.capacity',
                'disk.device.allocation',
                'disk.device.capacity',
                'disk.device.iops',
                'disk.device.latency',
                'disk.device.read.latency',
                'disk.device.usage',
                'disk.device.write.latency',
                'disk.iops',
                'disk.latency',
                'disk.read.bytes',
                'disk.read.bytes.rate',
                'disk.read.requests',
                'disk.read.requests.rate',
                'disk.usage',
                'disk.write.bytes',
                'disk.write.bytes.rate',
                'disk.write.requests',
                'disk.write.requests.rate',
                'memory.bandwidth.local',
                'memory.bandwidth.total',
                'memory.resident',
                'memory.swap.in',
                'memory.swap.out',
                'network.incoming.packets.drop',
                'network.incoming.packets.error',
                'network.outgoing.packets.drop',
                'network.outgoing.packets.error',
                'perf.cache.misses',
                'perf.cache.references',
                'perf.cpu.cycles',
                'perf.instructions',
            }

        return expected_metric_names
