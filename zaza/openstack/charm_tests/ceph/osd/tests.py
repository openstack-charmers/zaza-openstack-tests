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

"""Ceph-osd Testing."""

import logging
import unittest
import re

from copy import deepcopy

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.model as zaza_model


class SecurityTest(unittest.TestCase):
    """Ceph Security Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph security tests."""
        super(SecurityTest, cls).setUpClass()

    def test_osd_security_checklist(self):
        """Verify expected state with security-checklist."""
        expected_failures = []
        expected_passes = [
            'validate-file-ownership',
            'validate-file-permissions',
        ]

        logging.info('Running `security-checklist` action'
                     ' on Ceph OSD leader unit')
        test_utils.audit_assertions(
            zaza_model.run_action_on_leader(
                'ceph-osd',
                'security-checklist',
                action_params={}),
            expected_passes,
            expected_failures,
            expected_to_pass=True)


class OsdService:
    """Simple representation of ceph-osd systemd service."""

    def __init__(self, id_):
        """
        Init service using its ID.

        e.g.: id_=1 -> ceph-osd@1
        """
        self.id = id_
        self.name = 'ceph-osd@{}'.format(id_)


async def async_wait_for_service_status(unit_name, services, target_status,
                                        model_name=None, timeout=2700):
    """Wait for all services on the unit to be in the desired state.

    Note: This function emulates the
    `zaza.model.async_block_until_service_status` function, but it's using
    `systemctl is-active` command instead of `pidof/pgrep` of the original
    function.

    :param unit_name: Name of unit to run action on
    :type unit_name: str
    :param services: List of services to check
    :type services: List[str]
    :param target_status: State services must be in (stopped or running)
    :type target_status: str
    :param model_name: Name of model to query.
    :type model_name: str
    :param timeout: Time to wait for status to be achieved
    :type timeout: int
    """
    async def _check_service():
        services_ok = True
        for service in services:
            command = r"systemctl is-active '{}'".format(service)
            out = await zaza_model.async_run_on_unit(
                unit_name,
                command,
                model_name=model_name,
                timeout=timeout)
            response = out['Stdout'].strip()

            if target_status == "running" and response == 'active':
                continue
            elif target_status == "stopped" and response == 'inactive':
                continue
            else:
                services_ok = False
                break

        return services_ok

    accepted_states = ('stopped', 'running')
    if target_status not in accepted_states:
        raise RuntimeError('Invalid target state "{}". Accepted states: '
                           '{}'.format(target_status, accepted_states))

    async with zaza_model.run_in_model(model_name):
        await zaza_model.async_block_until(_check_service, timeout=timeout)


wait_for_service = zaza_model.sync_wrapper(async_wait_for_service_status)


class ServiceTest(unittest.TestCase):
    """ceph-osd systemd service tests."""

    TESTED_UNIT = 'ceph-osd/0'  # This can be any ceph-osd unit in the model
    SERVICE_PATTERN = re.compile(r'ceph-osd@(?P<service_id>\d+)\.service')

    def __init__(self, methodName='runTest'):
        """Initialize Test Case."""
        super(ServiceTest, self).__init__(methodName)
        self._available_services = None

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph service tests."""
        super(ServiceTest, cls).setUpClass()

    def setUp(self):
        """Run test setup."""
        # Skip 'service' action tests on systems without systemd
        result = zaza_model.run_on_unit(self.TESTED_UNIT, 'which systemctl')
        if not result['Stdout']:
            raise unittest.SkipTest("'service' action is not supported on "
                                    "systems without 'systemd'. Skipping "
                                    "tests.")
        # Note(mkalcok): This counter reset is needed because ceph-osd service
        #       is limited to 3 restarts per 30 mins which is insufficient
        #       when running functional tests for 'service' action. This
        #       limitation is defined in /lib/systemd/system/ceph-osd@.service
        #       in section [Service] with options 'StartLimitInterval' and
        #       'StartLimitBurst'
        reset_counter = 'systemctl reset-failed'
        zaza_model.run_on_unit(self.TESTED_UNIT, reset_counter)

    def tearDown(self):
        """Start ceph-osd services after each test.

        This ensures that the environment is ready for the next tests.
        """
        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'start',
                                       action_params={'osds': 'all'},
                                       raise_on_failure=True)

    @property
    def available_services(self):
        """Return list of all ceph-osd services present on the TESTED_UNIT."""
        if self._available_services is None:
            self._available_services = self._fetch_osd_services()
        return self._available_services

    def _fetch_osd_services(self):
        """Fetch all ceph-osd services present on the TESTED_UNIT."""
        service_list = []
        service_list_cmd = 'systemctl list-units --full --all ' \
                           '--no-pager -t service'
        result = zaza_model.run_on_unit(self.TESTED_UNIT, service_list_cmd)
        for line in result['Stdout'].split('\n'):
            service_name = self.SERVICE_PATTERN.search(line)
            if service_name:
                service_id = int(service_name.group('service_id'))
                service_list.append(OsdService(service_id))
        return service_list

    def test_start_stop_all_by_keyword(self):
        """Start and Stop all ceph-osd services using keyword 'all'."""
        service_list = [service.name for service in self.available_services]

        logging.info("Running 'service stop=all' action on {} "
                     "unit".format(self.TESTED_UNIT))
        zaza_model.run_action_on_units([self.TESTED_UNIT], 'stop',
                                       action_params={'osds': 'all'})
        wait_for_service(unit_name=self.TESTED_UNIT,
                         services=service_list,
                         target_status='stopped')

        logging.info("Running 'service start=all' action on {} "
                     "unit".format(self.TESTED_UNIT))
        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'start',
                                       action_params={'osds': 'all'})
        wait_for_service(unit_name=self.TESTED_UNIT,
                         services=service_list,
                         target_status='running')

    def test_start_stop_all_by_list(self):
        """Start and Stop all ceph-osd services using explicit list."""
        service_list = [service.name for service in self.available_services]
        service_ids = [str(service.id) for service in self.available_services]
        action_params = ','.join(service_ids)

        logging.info("Running 'service stop={}' action on {} "
                     "unit".format(action_params, self.TESTED_UNIT))
        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'stop',
                                       action_params={'osds': action_params})
        wait_for_service(unit_name=self.TESTED_UNIT,
                         services=service_list,
                         target_status='stopped')

        logging.info("Running 'service start={}' action on {} "
                     "unit".format(action_params, self.TESTED_UNIT))
        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'start',
                                       action_params={'osds': action_params})
        wait_for_service(unit_name=self.TESTED_UNIT,
                         services=service_list,
                         target_status='running')

    def test_stop_specific(self):
        """Stop only specified ceph-osd service."""
        if len(self.available_services) < 2:
            raise unittest.SkipTest('This test can be performed only if '
                                    'there\'s more than one ceph-osd service '
                                    'present on the tested unit')

        should_run = deepcopy(self.available_services)
        to_stop = should_run.pop()
        should_run = [service.name for service in should_run]

        logging.info("Running 'service stop={} on {} "
                     "unit".format(to_stop.id, self.TESTED_UNIT))

        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'stop',
                                       action_params={'osds': to_stop.id})

        wait_for_service(unit_name=self.TESTED_UNIT,
                         services=[to_stop.name, ],
                         target_status='stopped')
        wait_for_service(unit_name=self.TESTED_UNIT,
                         services=should_run,
                         target_status='running')

    def test_start_specific(self):
        """Start only specified ceph-osd service."""
        if len(self.available_services) < 2:
            raise unittest.SkipTest('This test can be performed only if '
                                    'there\'s more than one ceph-osd service '
                                    'present on the tested unit')

        service_names = [service.name for service in self.available_services]
        should_stop = deepcopy(self.available_services)
        to_start = should_stop.pop()
        should_stop = [service.name for service in should_stop]

        # Note: can't stop ceph-osd.target as restarting a single OSD will
        # cause this to start all of the OSDs when a single one starts.
        logging.info("Stopping all running ceph-osd services")
        service_stop_cmd = '; '.join(['systemctl stop {}'.format(service)
                                      for service in service_names])
        zaza_model.run_on_unit(self.TESTED_UNIT, service_stop_cmd)

        wait_for_service(unit_name=self.TESTED_UNIT,
                         services=service_names,
                         target_status='stopped')

        logging.info("Running 'service start={} on {} "
                     "unit".format(to_start.id, self.TESTED_UNIT))

        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'start',
                                       action_params={'osds': to_start.id})

        wait_for_service(unit_name=self.TESTED_UNIT,
                         services=[to_start.name, ],
                         target_status='running')

        wait_for_service(unit_name=self.TESTED_UNIT,
                         services=should_stop,
                         target_status='stopped')

    def test_active_after_pristine_block(self):
        """Test if we can get back to active state after pristine block.

        Set a non-pristine status, then trigger update-status to see if it
        clears.
        """
        logging.info('Setting Non-pristine status')
        zaza_model.run_on_leader(
            "ceph-osd",
            "status-set blocked 'Non-pristine'"
        )
        ceph_osd_states = {
            'ceph-osd': {
                'workload-status': 'blocked',
                'workload-status-message-prefix': 'Non-pristine'
            }
        }
        zaza_model.wait_for_application_states(states=ceph_osd_states)
        logging.info('Running update-status action')
        zaza_model.run_on_leader('ceph-osd', 'hooks/update-status')
        logging.info('Wait for idle/ready status')
        zaza_model.wait_for_application_states()
