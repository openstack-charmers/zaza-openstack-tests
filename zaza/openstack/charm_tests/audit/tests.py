#!/usr/bin/env python3
#
# Copyright 2024 Canonical Ltd.
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

"""
Keystone audit middleware API logging testing.

These methods test the
rendering of the charm's api-paste.ini file to ensure the appropriate sections
are rendered or not rendered depending on the state of the audit-middleware
configuration option.
"""

import logging
import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils


class KeystoneAuditMiddlewareBaseTest(test_utils.OpenStackBaseTest):
    """Base class for Keystone audit middleware tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for Keystone audit middleware tests."""
        super(KeystoneAuditMiddlewareBaseTest, cls).setUpClass()
        test_config = cls.test_config['tests_options']['audit-middleware']
        cls.service_name = test_config['service']

        # For cases when service name and application name differ
        if not test_config["application"]:
            cls.application_name = cls.service_name
        else:
            cls.application_name = test_config['application']
        print(test_config)
        print(cls.model_name)
        cls.lead_unit = zaza.model.get_lead_unit_name(
            cls.application_name,
            model_name=cls.model_name
        )
        print(cls.lead_unit)
        logging.info('Leader unit is %s', cls.lead_unit)
        logging.info('Service name is %s', cls.service_name)

    def fetch_api_paste_content(self):
        """Fetch content of api-paste.ini file."""
        api_paste_ini_path = f"/etc/{self.service_name}/api-paste.ini"
        try:
            return zaza.model.file_contents(
                self.lead_unit,
                api_paste_ini_path,
            )
        except zaza.model.CommandRunFailed as e:
            self.fail("Error fetching api-paste.ini: {}".format(str(e)))


class KeystoneAuditMiddlewareTest(KeystoneAuditMiddlewareBaseTest):
    """Keystone audit middleware API logging feature tests."""

    def test_101_apipaste_includes_audit_section(self):
        """Test api-paste.ini renders audit section when enabled."""
        expected_content = [
            "[filter:audit]",
            "paste.filter_factory = keystonemiddleware.audit:filter_factory",
            f"audit_map_file = /etc/{self.service_name}/api_audit_map.conf",
            f"service_name = {self.service_name}"
        ]

        set_default = {'audit-middleware': False}
        set_alternate = {'audit-middleware': True}

        with self.config_change(default_config=set_default,
                                alternate_config=set_alternate,
                                application_name=self.application_name):
            api_paste_content = self.fetch_api_paste_content()
            for line in expected_content:
                self.assertIn(line, api_paste_content)

    def test_102_apipaste_excludes_audit_section(self):
        """Test api_paste.ini does not render audit section when disabled."""
        section_heading = '[filter:audit]'

        if not self.config_current(self.application_name)['audit-middleware']:
            api_paste_content = self.fetch_api_paste_content()
            self.assertNotIn(section_heading, api_paste_content)
        else:
            self.fail("Config option audit-middleware incorrectly set to true")
