#!/usr/bin/env python3
#
# Copyright 2019 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Encapsulate heat testing."""
import logging
import json
import os
import subprocess
from urllib import parse as urlparse
from heatclient.common import template_utils

import zaza.model
import zaza.openstack.charm_tests.nova.utils as nova_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.charm_lifecycle.utils as charm_lifecycle_utils

# Resource and name constants
IMAGE_NAME = 'cirros'
STACK_NAME = 'hello_world'
RESOURCE_TYPE = 'server'
TEMPLATES_PATH = 'files'
FLAVOR_NAME = 'm1.tiny'


class HeatBasicDeployment(test_utils.OpenStackBaseTest):
    """Encapsulate Heat tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Heat tests."""
        super(HeatBasicDeployment, cls).setUpClass()
        cls.application = 'heat'
        cls.keystone_session = openstack_utils.get_overcloud_keystone_session()
        cls.heat_client = openstack_utils.get_heat_session_client(
            cls.keystone_session)
        cls.glance_client = openstack_utils.get_glance_session_client(
            cls.keystone_session)
        cls.nova_client = openstack_utils.get_nova_session_client(
            cls.keystone_session)

    @property
    def services(self):
        """Return a list services for the selected OpenStack release.

        :returns: List of services
        :rtype: [str]
        """
        services = ['heat-api', 'heat-api-cfn', 'heat-engine']
        return services

    # TODO: Deprecate this function
    # domain-setup action has been added as a setup configuration option
    def test_100_domain_setup(self):
        """Run required action for a working Heat unit."""
        # Action is REQUIRED to run for a functioning heat deployment
        logging.info('Running domain-setup action on heat unit...')
        unit = zaza.model.get_units(self.application_name)[0]
        zaza.model.block_until_unit_wl_status(unit.entity_id, "active")
        zaza.model.run_action(unit.entity_id, "domain-setup")
        zaza.model.block_until_unit_wl_status(unit.entity_id, "active")

    def test_400_heat_resource_types_list(self):
        """Check default resource list behavior and confirm functionality."""
        logging.info('Checking default heat resource list...')
        types = self.heat_client.resource_types.list()
        self.assertIsInstance(types, list, "Resource type is not a list!")
        self.assertGreater(len(types), 0, "Resource type list len is zero")

    def test_410_heat_stack_create_delete(self):
        """Create stack, confirm nova compute resource, delete stack."""
        # Verify new image name
        images_list = list(self.glance_client.images.list())
        self.assertEqual(images_list[0].name, IMAGE_NAME,
                         "glance image create failed or unexpected")

        # Create a heat stack from a heat template, verify its status
        logging.info('Creating heat stack...')
        t_name = 'hot_hello_world.yaml'
        if (openstack_utils.get_os_release() <
                openstack_utils.get_os_release('xenial_queens')):
            os_release = 'icehouse'
        else:
            os_release = 'queens'

        # Get location of template files in charm-heat
        bundle_path = charm_lifecycle_utils.BUNDLE_DIR
        if bundle_path[-1:] == "/":
            bundle_path = bundle_path[0:-1]

        file_rel_path = os.path.join(os.path.dirname(bundle_path),
                                     TEMPLATES_PATH, os_release, t_name)
        file_abs_path = os.path.abspath(file_rel_path)
        t_url = urlparse.urlparse(file_abs_path, scheme='file').geturl()
        logging.info('template url: {}'.format(t_url))

        r_req = self.heat_client.http_client
        t_files, template = template_utils.get_template_contents(t_url, r_req)
        env_files, env = template_utils.process_environment_and_files(
            env_path=None)

        fields = {
            'stack_name': STACK_NAME,
            'timeout_mins': '15',
            'disable_rollback': False,
            'parameters': {
                'admin_pass': 'Ubuntu',
                'key_name': nova_utils.KEYPAIR_NAME,
                'image': IMAGE_NAME
            },
            'template': template,
            'files': dict(list(t_files.items()) + list(env_files.items())),
            'environment': env
        }

        # Create the stack
        try:
            stack = self.heat_client.stacks.create(**fields)
            logging.info('Stack data: {}'.format(stack))
            stack_id = stack['stack']['id']
            logging.info('Creating new stack, ID: {}'.format(stack_id))
        except Exception as e:
            # Generally, an api or cloud config error if this is hit.
            msg = 'Failed to create heat stack: {}'.format(e)
            self.fail(msg)

        # Confirm stack reaches COMPLETE status.
        # /!\ Heat stacks reach a COMPLETE status even when nova cannot
        # find resources (a valid hypervisor) to fit the instance, in
        # which case the heat stack self-deletes!  Confirm anyway...
        openstack_utils.resource_reaches_status(self.heat_client.stacks,
                                                stack_id,
                                                expected_status="COMPLETE",
                                                msg="Stack status wait")
        # List stack
        stacks = list(self.heat_client.stacks.list())
        logging.info('All stacks: {}'.format(stacks))

        # Get stack information
        try:
            stack = self.heat_client.stacks.get(STACK_NAME)
        except Exception as e:
            # Generally, a resource availability issue if this is hit.
            msg = 'Failed to get heat stack: {}'.format(e)
            self.fail(msg)

        # Confirm stack name.
        logging.info('Expected, actual stack name: {}, '
                     '{}'.format(STACK_NAME, stack.stack_name))
        self.assertEqual(stack.stack_name, STACK_NAME,
                         'Stack name mismatch, '
                         '{} != {}'.format(STACK_NAME, stack.stack_name))

        # Confirm existence of a heat-generated nova compute resource
        logging.info('Confirming heat stack resource status...')
        resource = self.heat_client.resources.get(STACK_NAME, RESOURCE_TYPE)
        server_id = resource.physical_resource_id
        self.assertTrue(server_id, "Stack failed to spawn a compute resource.")

        # Confirm nova instance reaches ACTIVE status
        openstack_utils.resource_reaches_status(self.nova_client.servers,
                                                server_id,
                                                expected_status="ACTIVE",
                                                msg="nova instance")
        logging.info('Nova instance reached ACTIVE status')

        # Delete stack
        logging.info('Deleting heat stack...')
        openstack_utils.delete_resource(self.heat_client.stacks,
                                        STACK_NAME, msg="heat stack")

    def test_500_auth_encryption_key_same_on_units(self):
        """Test the auth_encryption_key in heat.conf is same on all units."""
        logging.info("Checking the 'auth_encryption_key' is the same on "
                     "all units.")
        output, ret = self._run_arbitrary(
            "--application heat "
            "--format json "
            "grep auth_encryption_key /etc/heat/heat.conf")
        if ret:
            msg = "juju run error: ret: {}, output: {}".format(ret, output)
            self.assertEqual(ret, 0, msg)
        output = json.loads(output)
        keys = {}
        for r in output:
            k = r['Stdout'].split('=')[1].strip()
            keys[r['UnitId']] = k
        # see if keys are different
        ks = set(keys.values())
        self.assertEqual(len(ks), 1, "'auth_encryption_key' is not identical "
                         "on every unit: {}".format("{}={}".format(k, v)
                                                    for k, v in keys.items()))

    @staticmethod
    def _run_arbitrary(command, timeout=300):
        """Run an arbitrary command (as root), but not necessarily on a unit.

        (Otherwise the self.run(...) command could have been used for the unit

        :param command: The command to run.
        :type command: str
        :param timeout: Seconds to wait before timing out.
        :type timeout: int
        :raises: subprocess.CalledProcessError.
        :returns: A pair containing the output of the command and exit value
        :rtype: (str, int)
        """
        cmd = ['juju', 'run', '--timeout', "{}s".format(timeout),
               ] + command.split()
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        output = stdout if p.returncode == 0 else stderr
        return output.decode('utf8').strip(), p.returncode

    def test_900_heat_restart_on_config_change(self):
        """Verify the specified services are restarted when config changes."""
        logging.info('Testing restart on configuration change')

        # Expected default and alternate values
        set_default = {'use-syslog': 'False'}
        set_alternate = {'use-syslog': 'True'}

        # Config file affected by juju set config change
        conf_file = '/etc/heat/heat.conf'

        # Make config change, check for service restarts
        # In Amulet we waited 30 seconds...do we still need to?
        logging.info('Making configuration change')
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            None,
            None,
            self.services)

    def test_910_pause_and_resume(self):
        """Run services pause and resume tests."""
        logging.info('Checking pause and resume actions...')

        with self.pause_resume(self.services):
            logging.info("Testing pause resume")
