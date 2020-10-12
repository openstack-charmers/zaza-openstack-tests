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
from typing import List

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

    def __init__(self, id_: int):
        """
        Init service using its ID.

        e.g.: id_=1 -> ceph.-osd@1.service
        """
        self.id = id_
        self.name = 'ceph-osd@{}'.format(id_)


class ServiceTest(unittest.TestCase):
    """ceph-osd systemd service tests."""

    TESTED_UNIT = 'ceph-osd/0'
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
        # Note: This counter reset is needed because ceph-osd service is
        #       limited to 3 restarts per 30 mins which is insufficient
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
        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'service',
                                       action_params={'start': 'all'},
                                       raise_on_failure=True)

    @property
    def available_services(self) -> List[OsdService]:
        """Return list of all ceph-osd services present on the TESTED_UNIT."""
        if self._available_services is None:
            self._available_services = self._fetch_osd_services()
        return self._available_services

    def _fetch_osd_services(self) -> List[OsdService]:
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
        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'service',
                                       action_params={'stop': 'all'})
        zaza_model.block_until_service_status(unit_name=self.TESTED_UNIT,
                                              services=service_list,
                                              target_status='stopped')

        logging.info("Running 'service start=all' action on {} "
                     "unit".format(self.TESTED_UNIT))
        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'service',
                                       action_params={'start': 'all'})
        zaza_model.block_until_service_status(unit_name=self.TESTED_UNIT,
                                              services=service_list,
                                              target_status='running',
                                              pgrep_full=True)

    def test_start_stop_all_by_list(self):
        """Start and Stop all ceph-osd services using explicit list."""
        service_list = [service.name for service in self.available_services]
        service_ids = [str(service.id) for service in self.available_services]
        action_params = ','.join(service_ids)

        logging.info("Running 'service stop={}' action on {} "
                     "unit".format(action_params, self.TESTED_UNIT))
        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'service',
                                       action_params={'stop': action_params})
        zaza_model.block_until_service_status(unit_name=self.TESTED_UNIT,
                                              services=service_list,
                                              target_status='stopped')

        logging.info("Running 'service start={}' action on {} "
                     "unit".format(action_params, self.TESTED_UNIT))
        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'service',
                                       action_params={'start': action_params})
        zaza_model.block_until_service_status(unit_name=self.TESTED_UNIT,
                                              services=service_list,
                                              target_status='running',
                                              pgrep_full=True)

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

        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'service',
                                       action_params={'stop': to_stop.id})

        zaza_model.block_until_service_status(unit_name=self.TESTED_UNIT,
                                              services=[to_stop.name, ],
                                              target_status='stopped')
        zaza_model.block_until_service_status(unit_name=self.TESTED_UNIT,
                                              services=should_run,
                                              target_status='running',
                                              pgrep_full=True)

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

        logging.info("Stopping all running ceph-osd services")
        service_stop_cmd = 'systemctl stop ceph-osd.target'
        zaza_model.run_on_unit(self.TESTED_UNIT, service_stop_cmd)

        zaza_model.block_until_service_status(unit_name=self.TESTED_UNIT,
                                              services=service_names,
                                              target_status='stopped')

        logging.info("Running 'service start={} on {} "
                     "unit".format(to_start.id, self.TESTED_UNIT))

        zaza_model.run_action_on_units([self.TESTED_UNIT, ], 'service',
                                       action_params={'start': to_start.id})

        zaza_model.block_until_service_status(unit_name=self.TESTED_UNIT,
                                              services=[to_start.name, ],
                                              target_status='running',
                                              pgrep_full=True)
        zaza_model.block_until_service_status(unit_name=self.TESTED_UNIT,
                                              services=should_stop,
                                              target_status='stopped')
