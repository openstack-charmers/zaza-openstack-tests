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
from novaclient import exceptions

import zaza.model
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils

# Resource and name constants
IMAGE_NAME = 'cirros-image-1'
KEYPAIR_NAME = 'testkey'
STACK_NAME = 'hello_world'
RESOURCE_TYPE = 'server'
TEMPLATES_PATH = 'tests/files'
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
        """Return a list services for OpenStack release."""
        services = ['heat-api', 'heat-api-cfn', 'heat-engine']
        return services

    def _image_create(self):
        """Create an image for use by the heat template, verify it exists."""
        logging.info('Creating glance image ({})...'.format(IMAGE_NAME))

        # Create a new image
        image_url = openstack_utils.find_cirros_image(arch='x86_64')
        image_new = openstack_utils.create_image(
            self.glance_client,
            image_url,
            IMAGE_NAME)

        # Confirm image is created and has status of 'active'
        if not image_new:
            message = 'glance image create failed'
            logging.error(message)

        # Verify new image name
        images_list = list(self.glance_client.images.list())
        if images_list[0].name != IMAGE_NAME:
            message = ('glance image create failed or unexpected '
                       'image name {}'.format(images_list[0].name))
            logging.error(message)

    def _keypair_create(self):
        """Create a keypair or get a keypair if it exists."""
        logging.info('Creating keypair {} if none exists'.format(KEYPAIR_NAME))
        if not openstack_utils.valid_key_exists(self.nova_client,
                                                KEYPAIR_NAME):
            key = openstack_utils.create_ssh_key(
                self.nova_client,
                KEYPAIR_NAME,
                replace=True)
            openstack_utils.write_private_key(
                KEYPAIR_NAME,
                key.private_key)
            logging.info('Keypair created')
        else:
            logging.info('Keypair not created')

    def _stack_create(self):
        """Create a heat stack from a heat template, verify its status."""
        logging.info('Creating heat stack...')

        t_name = 'hot_hello_world.yaml'
        if (openstack_utils.get_os_release() <
                openstack_utils.get_os_release('xenial_queens')):
            os_release = 'icehouse'
        else:
            os_release = 'queens'

        file_rel_path = os.path.join(TEMPLATES_PATH, os_release, t_name)
        file_abs_path = os.path.abspath(file_rel_path)
        t_url = urlparse.urlparse(file_abs_path, scheme='file').geturl()
        logging.info('template url: {}'.format(t_url))

        # Create flavor
        try:
            self.nova_client.flavors.find(name=FLAVOR_NAME)
        except (exceptions.NotFound, exceptions.NoUniqueMatch):
            logging.info('Creating flavor ({})'.format(FLAVOR_NAME))
            self.nova_client.flavors.create(FLAVOR_NAME, ram=512, vcpus=1,
                                            disk=1, flavorid=1)

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
                'key_name': KEYPAIR_NAME,
                'image': IMAGE_NAME
            },
            'template': template,
            'files': dict(list(t_files.items()) + list(env_files.items())),
            'environment': env
        }

        # Create the stack.
        try:
            _stack = self.heat_client.stacks.create(**fields)
            logging.info('Stack data: {}'.format(_stack))
            _stack_id = _stack['stack']['id']
            logging.info('Creating new stack, ID: {}'.format(_stack_id))
        except Exception as e:
            # Generally, an api or cloud config error if this is hit.
            msg = 'Failed to create heat stack: {}'.format(e)
            logging.error(msg)
            raise

        # Confirm stack reaches COMPLETE status.
        # /!\ Heat stacks reach a COMPLETE status even when nova cannot
        # find resources (a valid hypervisor) to fit the instance, in
        # which case the heat stack self-deletes!  Confirm anyway...
        openstack_utils.resource_reaches_status(self.heat_client.stacks,
                                                _stack_id,
                                                expected_status="COMPLETE",
                                                msg="Stack status wait")
        _stacks = list(self.heat_client.stacks.list())
        logging.info('All stacks: {}'.format(_stacks))

        # Confirm stack still exists.
        try:
            _stack = self.heat_client.stacks.get(STACK_NAME)
        except Exception as e:
            # Generally, a resource availability issue if this is hit.
            msg = 'Failed to get heat stack: {}'.format(e)
            logging.error(msg)

        # Confirm stack name.
        logging.info('Expected, actual stack name: {}, '
                     '{}'.format(STACK_NAME, _stack.stack_name))
        if STACK_NAME != _stack.stack_name:
            msg = 'Stack name mismatch, {} != {}'.format(STACK_NAME,
                                                         _stack.stack_name)
            logging.error(msg)

    def _stack_resource_compute(self):
        """Confirm the stack has created a nova resource and check status."""
        logging.info('Confirming heat stack resource status...')

        # Confirm existence of a heat-generated nova compute resource.
        _resource = self.heat_client.resources.get(STACK_NAME, RESOURCE_TYPE)
        _server_id = _resource.physical_resource_id
        if _server_id:
            logging.debug('Heat template spawned nova instance, '
                          'ID: {}'.format(_server_id))
        else:
            msg = 'Stack failed to spawn a nova compute resource (instance).'
            logging.error(msg)

        # Confirm nova instance reaches ACTIVE status.
        openstack_utils.resource_reaches_status(self.nova_client.servers,
                                                _server_id,
                                                expected_status="ACTIVE",
                                                msg="nova instance")
        logging.info('Nova instance reached ACTIVE status')

    def _stack_delete(self):
        """Delete a heat stack, verify."""
        logging.info('Deleting heat stack...')
        openstack_utils.delete_resource(self.heat_client.stacks,
                                        STACK_NAME, msg="heat stack")

    def _image_delete(self):
        """Delete that image."""
        logging.info('Deleting glance image...')
        image = self.nova_client.glance.find_image(IMAGE_NAME)
        openstack_utils.delete_resource(self.glance_client.images,
                                        image.id, msg="glance image")

    def _keypair_delete(self):
        """Delete that keypair."""
        logging.info('Deleting keypair...')
        openstack_utils.delete_resource(self.nova_client.keypairs,
                                        KEYPAIR_NAME, msg="nova keypair")

    def test_100_domain_setup(self):
        """Run required action for a working Heat unit."""
        # Action is REQUIRED to run for a functioning heat deployment
        logging.info('Running domain-setup action on heat unit...')
        unit = zaza.model.get_units(self.application_name)[0]
        assert unit.workload_status == "active"
        zaza.model.run_action(unit.entity_id, "domain-setup")
        zaza.model.block_until_unit_wl_status(unit.entity_id, "active")
        unit = zaza.model.get_unit_from_name(unit.entity_id)
        assert unit.workload_status == "active"

    def test_400_heat_resource_types_list(self):
        """Check default resource list behavior and confirm functionality."""
        logging.info('Checking default heat resource list...')
        try:
            types = list(self.heat_client.resource_types.list())
            if type(types) is list:
                logging.info('Resource type list check is ok.')
            else:
                msg = 'Resource type list is not a list!'
                logging.error('{}'.format(msg))
                raise
            if len(types) > 0:
                logging.info('Resource type list is populated '
                             '({}, ok).'.format(len(types)))
            else:
                msg = 'Resource type list length is zero!'
                logging.error(msg)
                raise
        except Exception as e:
            msg = 'Resource type list failed: {}'.format(e)
            logging.error(msg)
            raise

    def test_402_heat_stack_list(self):
        """Check default heat stack list behavior, confirm functionality."""
        logging.info('Checking default heat stack list...')
        try:
            stacks = list(self.heat_client.stacks.list())
            if type(stacks) is list:
                logging.info("Stack list check is ok.")
            else:
                msg = 'Stack list returned something other than a list.'
                logging.error(msg)
                raise
        except Exception as e:
            msg = 'Heat stack list failed: {}'.format(e)
            logging.error(msg)
            raise

    def test_410_heat_stack_create_delete(self):
        """Create stack, confirm nova compute resource, delete stack."""
        logging.info('Creating, deleting heat stack (compute)...')
        self._image_create()
        self._keypair_create()
        self._stack_create()
        self._stack_resource_compute()
        self._stack_delete()
        self._image_delete()
        self._keypair_delete()

    def test_500_auth_encryption_key_same_on_units(self):
        """Test the auth_encryption_key in heat.conf is same on all units."""
        logging.info("Checking the 'auth_encryption_key' is the same on "
                     "all units.")
        output, ret = self._run_arbitrary(
            "--application heat "
            "--format json "
            "grep auth_encryption_key /etc/heat/heat.conf")
        if ret:
            msg = "juju run returned error: ({}) -> {}".format(ret, output)
            logging.error("Error: {}".format(msg))
        output = json.loads(output)
        keys = {}
        for r in output:
            k = r['Stdout'].split('=')[1].strip()
            keys[r['UnitId']] = k
        # see if keys are different.
        ks = list(keys.values())
        if any(((k != ks[0]) for k in ks[1:])):
            msg = ("'auth_encryption_key' is not identical on every unit: {}"
                   .format("{}={}".format(k, v) for k, v in keys.items()))
            logging.error("Error: {}".format(msg))

    @staticmethod
    def _run_arbitrary(command, timeout=300):
        """Run an arbitrary command (as root), but not necessarily on a unit.

        (Otherwise the self.run(...) command could have been used for the unit

        :param str command: The command to run.
        :param int timeout: Seconds to wait before timing out.
        :return: A 2-tuple containing the output of the command and the exit
            code of the command.
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
