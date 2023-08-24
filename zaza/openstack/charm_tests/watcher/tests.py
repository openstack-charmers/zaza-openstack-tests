# Copyright 2023 Canonical Ltd.
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
"""Encapsulate Cinder testing."""

import logging

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.configure.guest as guest
import watcherclient.common.apiclient.exceptions as watcherclient_exceptions

logger = logging.getLogger(__name__)


class WatcherTests(test_utils.OpenStackBaseTest):
    """Encapsulate Watcher tests."""

    AUDIT_TEMPLATE_NAME = 'zaza-at1'
    AUDIT_TEMPLATE_GOAL = 'server_consolidation'
    AUDIT_TEMPLATE_STRATEGY = 'vm_workload_consolidation'
    AUDIT_TYPE = 'ONESHOT'

    BLOCK_SECS = 600

    @classmethod
    def setUpClass(cls):
        """Configure Watcher tests class."""
        super().setUpClass()
        cls.watcher_client = openstack_utils.get_watcher_session_client(
            cls.keystone_session,
        )

    def test_server_consolidation(self):
        """Test server consolidation policy."""
        try:
            at = self.watcher_client.audit_template.get(
                self.AUDIT_TEMPLATE_NAME
            )
            logger.info('Re-using audit template: %s (%s)', at.name, at.uuid)
        except watcherclient_exceptions.NotFound:
            at = self.watcher_client.audit_template.create(
                name=self.AUDIT_TEMPLATE_NAME,
                goal=self.AUDIT_TEMPLATE_GOAL,
                strategy=self.AUDIT_TEMPLATE_STRATEGY,
            )
            logger.info('Audit template created: %s (%s)', at.name, at.uuid)

        hypervisors_before = {
            'enabled': [],
            'disabled': [],
        }
        for i, hypervisor in enumerate(self.nova_client.hypervisors.list()):
            hypervisors_before[hypervisor.status].append(
                hypervisor.hypervisor_hostname
            )
            # There is a need to have instances running to allow Watcher not
            # fail when calling gnocchi for cpu_util metric measures.
            logger.info('Launching instance on hypervisor %s',
                        hypervisor.hypervisor_hostname)
            guest.launch_instance(
                'cirros',
                vm_name='zaza-watcher-%s' % i,
                perform_connectivity_check=False,
                host=hypervisor.hypervisor_hostname,
                nova_api_version='2.74',
            )

        audit = self.watcher_client.audit.create(
            audit_template_uuid=at.uuid,
            audit_type=self.AUDIT_TYPE,
            parameters={'period': 600, 'granularity': 300},
        )
        logger.info('Audit created: %s', audit.uuid)

        openstack_utils.resource_reaches_status(self.watcher_client.audit,
                                                audit.uuid,
                                                msg='audit',
                                                resource_attribute='state',
                                                expected_status='SUCCEEDED',
                                                wait_iteration_max_time=180,
                                                stop_after_attempt=30,
                                                stop_status='FAILED')
        action_plans = self.watcher_client.action_plan.list(audit=audit.uuid)
        assert len(action_plans) == 1
        action_plan = action_plans[0]
        actions = self.watcher_client.action.list(action_plan=action_plan.uuid)

        for action in actions:
            logger.info('Action %s: %s %s',
                        action.uuid, action.state, action.action_type)
            self.assertEqual(action.state, 'PENDING',
                             'Action %s state %s != PENDING' % (action.uuid,
                                                                action.state))

        self.watcher_client.action_plan.start(action_plan.uuid)

        openstack_utils.resource_reaches_status(
            self.watcher_client.action_plan,
            action_plan.uuid,
            resource_attribute='state',
            expected_status='SUCCEEDED',
            wait_iteration_max_time=180,
            stop_after_attempt=30,
        )
        # get fresh list of action objects
        actions = self.watcher_client.action.list(action_plan=action_plan.uuid)
        for action in actions:
            logger.info('Action %s: %s %s',
                        action.uuid, action.state, action.action_type)
            self.assertEqual(
                action.state, 'SUCCEEDED',
                'Action %s state %s != SUCCEEDED' % (action.uuid,
                                                     action.state),
            )

        hypervisors_after = {
            'enabled': [],
            'disabled': [],
        }
        for i, hypervisor in enumerate(self.nova_client.hypervisors.list()):
            hypervisors_after[hypervisor.status].append(
                hypervisor.hypervisor_hostname
            )
        self.assertNotEqual(hypervisors_before, hypervisors_after)
