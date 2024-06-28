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

These methods test the rendering of the charm api-paste.ini file to
ensure the appropriate sections are rendered or not rendered depending
on the state of the audit-middleware configuration option. OpenStack
releases older than Yoga are skipped as this feature is not supported.
"""

import textwrap
import logging
import zaza.model
from zaza.openstack.utilities import openstack as openstack_utils
import zaza.openstack.charm_tests.test_utils as test_utils


class KeystoneAuditMiddlewareTest(test_utils.OpenStackBaseTest):
    """Keystone audit middleware test class."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for Keystone audit middleware tests."""
        super(KeystoneAuditMiddlewareTest, cls).setUpClass()
        os_version = openstack_utils.get_openstack_release(
            cls.application_name,
            cls.model_name
        )

        if os_version < 'yoga':
            cls.skipTest(cls, 'Skipping audit middleware test in unsupported'
                         ' version of OpenStack: %s' % os_version)

        test_config = cls.test_config['tests_options']['audit-middleware']
        cls.service_name = test_config['service']

        cls.application_name = test_config.get('application', cls.service_name)
        logging.info('Using application name: %s', cls.application_name)

        cls.initial_audit_middleware = zaza.model.get_application_config(
            cls.application_name)['audit-middleware']['value']

    @classmethod
    def tearDownClass(cls):
        """Restore the audit-middleware configuration to its original state."""
        super(KeystoneAuditMiddlewareTest, cls).tearDownClass()
        logging.info("Running teardown on %s" % cls.application_name)
        zaza.model.set_application_config(
            cls.application_name,
            {'audit-middleware': str(cls.initial_audit_middleware)},
            model_name=cls.model_name
        )
        zaza.model.wait_for_application_states(
            states={cls.application_name: {
                'workload-status': 'active',
                'workload-status-message': 'Unit is ready'}},
            model_name=cls.model_name
        )

    def fetch_api_paste_content(self):
        """Fetch content of api-paste.ini file."""
        api_paste_ini_path = f"/etc/{self.service_name}/api-paste.ini"
        lead_unit = zaza.model.get_lead_unit_name(
            self.application_name,
            model_name=self.model_name
        )
        try:
            return zaza.model.file_contents(
                lead_unit,
                api_paste_ini_path,
            )
        except zaza.model.CommandRunFailed as e:
            self.fail("Error fetching api-paste.ini: %s" % e)

    def test_101_apipaste_includes_audit_section(self):
        """Test api-paste.ini renders audit section when enabled."""
        expected_content = textwrap.dedent(f"""\
            [filter:audit]
            paste.filter_factory = keystonemiddleware.audit:filter_factory
            audit_map_file = /etc/{self.service_name}/api_audit_map.conf
            service_name = {self.service_name}
            """)

        set_default = {'audit-middleware': False}
        set_alternate = {'audit-middleware': True}

        with self.config_change(default_config=set_default,
                                alternate_config=set_alternate,
                                application_name=self.application_name):
            api_paste_content = self.fetch_api_paste_content()
            self.assertIn(expected_content, api_paste_content)

    def test_102_apipaste_excludes_audit_section(self):
        """Test api_paste.ini does not render audit section when disabled."""
        section_heading = '[filter:audit]'
        set_default = {'audit-middleware': True}
        set_alternate = {'audit-middleware': False}

        with self.config_change(default_config=set_default,
                                alternate_config=set_alternate,
                                application_name=self.application_name):
            api_paste_content = self.fetch_api_paste_content()
            self.assertNotIn(section_heading, api_paste_content)


class IronicAuditMiddlewareTest(KeystoneAuditMiddlewareTest):
    """Ironic-API audit middleware test class."""

    def test_101_apipaste_includes_audit_section(self):
        """Test api-paste.ini renders audit section when enabled."""
        self.skipTest('ironic-api does not use an api-paste.ini file')

    def test_102_apipaste_excludes_audit_section(self):
        """Test api_paste.ini does not render audit section when disabled."""
        self.skipTest('ironic-api does not use an api-paste.ini file')
