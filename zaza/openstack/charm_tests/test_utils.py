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
"""Module containing base class for implementing charm tests."""
import contextlib
import logging
import subprocess
import sys
import tenacity
import unittest

import novaclient

import zaza.model as model
import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.openstack.configure.guest as configure_guest
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup


def skipIfNotHA(service_name):
    """Run decorator to skip tests if application not in HA configuration."""
    def _skipIfNotHA_inner_1(f):
        def _skipIfNotHA_inner_2(*args, **kwargs):
            ips = model.get_app_ips(
                service_name)
            if len(ips) > 1:
                return f(*args, **kwargs)
            else:
                logging.warn("Skipping HA test for non-ha service {}".format(
                    service_name))
        return _skipIfNotHA_inner_2

    return _skipIfNotHA_inner_1


def skipUntilVersion(service, package, release):
    """Run decorator to skip this test if application version is too low."""
    def _skipUntilVersion_inner_1(f):
        def _skipUntilVersion_inner_2(*args, **kwargs):
            package_version = generic_utils.get_pkg_version(service, package)
            try:
                subprocess.check_call(['dpkg', '--compare-versions',
                                       package_version, 'ge', release],
                                      stderr=subprocess.STDOUT,
                                      universal_newlines=True)
                return f(*args, **kwargs)
            except subprocess.CalledProcessError:
                logging.warn("Skipping test for older ({})"
                             "service {}, requested {}".format(
                                 package_version, service, release))
        return _skipUntilVersion_inner_2
    return _skipUntilVersion_inner_1


def audit_assertions(action,
                     expected_passes,
                     expected_failures=None,
                     expected_to_pass=True):
    """Check expected assertion failures in security-checklist actions.

    :param action: Action object from running the security-checklist action
    :type action: juju.action.Action
    :param expected_passes: List of test names that are expected to pass
    :type expected_passes: List[str]
    :param expected_failures: List of test names that are expected to fail
    :type expected_failures: List[str]
    :raises: AssertionError if the assertion fails.
    """
    if expected_failures is None:
        expected_failures = []
    if expected_to_pass:
        assert action.data["status"] == "completed", \
            "Security check is expected to pass by default"
    else:
        assert action.data["status"] == "failed", \
            "Security check is not expected to pass by default"

    results = action.data['results']
    for key, value in results.items():
        if key in expected_failures:
            assert "FAIL" in value, "Unexpected test pass: {}".format(key)
        if key in expected_passes:
            assert value == "PASS", "Unexpected failure: {}".format(key)


class BaseCharmTest(unittest.TestCase):
    """Generic helpers for testing charms."""

    run_resource_cleanup = False

    def resource_cleanup(self):
        """Cleanup any resources created during the test run.

        Override this method with a method which removes any resources
        which were created during the test run. If the test sets
        "self.run_resource_cleanup = True" then cleanup will be
        performed.
        """
        pass

    # this must be a class instance method otherwise descentents will not be
    # able to influence if cleanup should be run.
    def tearDown(self):
        """Run teardown for test class."""
        if self.run_resource_cleanup:
            logging.info('Running resource cleanup')
            self.resource_cleanup()

    @classmethod
    def setUpClass(cls, application_name=None, model_alias=None):
        """Run setup for test class to create common resources."""
        cls.model_aliases = model.get_juju_model_aliases()
        if model_alias:
            cls.model_name = cls.model_aliases[model_alias]
        else:
            cls.model_name = model.get_juju_model()
        cls.test_config = lifecycle_utils.get_charm_config(fatal=False)
        if application_name:
            cls.application_name = application_name
        else:
            cls.application_name = cls.test_config['charm_name']
        cls.lead_unit = model.get_lead_unit_name(
            cls.application_name,
            model_name=cls.model_name)
        logging.debug('Leader unit is {}'.format(cls.lead_unit))

    def config_current(self, application_name=None, keys=None):
        """Get Current Config of an application normalized into key-values.

        :param application_name: String application name for use when called
                                 by a charm under test other than the object's
                                 application.
        :type application_name:  Optional[str]
        :param keys: iterable of strs to index into the current config.  If
                     None, return all keys from the config
        :type keys:  Optional[Iterable[str]]
        :return: Dictionary of requested config from application
        :rtype: Dict[str, Any]
        """
        if not application_name:
            application_name = self.application_name

        _app_config = model.get_application_config(application_name)

        keys = keys or _app_config.keys()
        return {
            k: _app_config.get(k, {}).get('value')
            for k in keys
        }

    @staticmethod
    def _stringed_value_config(config):
        """Stringify values in a dict.

        Workaround:
        libjuju refuses to accept data with types other than strings
        through the zaza.model.set_application_config

        :param config: Config dictionary with any typed values
        :type  config: Dict[str,Any]
        :return:       Config Dictionary with string-ly typed values
        :rtype:        Dict[str,str]
        """
        # if v is None, stringify to ''
        # otherwise use a strict cast with str(...)
        return {
            k: '' if v is None else str(v)
            for k, v in config.items()
        }

    @contextlib.contextmanager
    def config_change(self, default_config, alternate_config,
                      application_name=None, reset_to_charm_default=False):
        """Run change config tests.

        Change config to `alternate_config`, wait for idle workload status,
        yield, return config to `default_config` and wait for idle workload
        status before return from function.

        Example usage:
            with self.config_change({'preferred-api-version': '2'},
                                    {'preferred-api-version': '3'}):
                do_something()

        :param default_config: Dict of charm settings to set on completion
        :type default_config: dict
        :param alternate_config: Dict of charm settings to change to
        :type alternate_config: dict
        :param application_name: String application name for use when called
                                 by a charm under test other than the object's
                                 application.
        :type application_name: str
        :param reset_to_charm_default: When True we will ask Juju to reset each
                                       configuration option mentioned in the
                                       `alternate_config` dictionary back to
                                       the charm default and ignore the
                                       `default_config` dictionary.
        :type reset_to_charm_default: bool
        """
        if not application_name:
            application_name = self.application_name

        # we need to compare config values to what is already applied before
        # attempting to set them.  otherwise the model will behave differently
        # than we would expect while waiting for completion of the change
        app_config = self.config_current(
            application_name, keys=alternate_config.keys()
        )

        if all(item in app_config.items()
                for item in alternate_config.items()):
            logging.debug('alternate_config equals what is already applied '
                          'config')
            yield
            if default_config == alternate_config:
                logging.debug('default_config also equals what is already '
                              'applied config')
                return
            logging.debug('alternate_config already set, and default_config '
                          'needs to be applied before return')
        else:
            logging.debug('Changing charm setting to {}'
                          .format(alternate_config))
            model.set_application_config(
                application_name,
                self._stringed_value_config(alternate_config),
                model_name=self.model_name)

            logging.debug(
                'Waiting for units to execute config-changed hook')
            model.wait_for_agent_status(model_name=self.model_name)

            logging.debug(
                'Waiting for units to reach target states')
            model.wait_for_application_states(
                model_name=self.model_name,
                states=self.test_config.get('target_deploy_status', {}))
            # TODO: Optimize with a block on a specific application until idle.
            model.block_until_all_units_idle()

            yield

        if reset_to_charm_default:
            logging.debug('Resetting these charm configuration options to the '
                          'charm default: "{}"'
                          .format(alternate_config.keys()))
            model.reset_application_config(application_name,
                                           alternate_config.keys(),
                                           model_name=self.model_name)
        elif default_config == alternate_config:
            logging.debug('default_config == alternate_config, not attempting '
                          ' to restore configuration')
            return
        else:
            logging.debug('Restoring charm setting to {}'
                          .format(default_config))
            model.set_application_config(
                application_name,
                self._stringed_value_config(default_config),
                model_name=self.model_name)

        logging.debug(
            'Waiting for units to execute config-changed hook')
        model.wait_for_agent_status(model_name=self.model_name)
        logging.debug(
            'Waiting for units to reach target states')
        model.wait_for_application_states(
            model_name=self.model_name,
            states=self.test_config.get('target_deploy_status', {}))
        # TODO: Optimize with a block on a specific application until idle.
        model.block_until_all_units_idle()

    def restart_on_changed_debug_oslo_config_file(self, config_file, services,
                                                  config_section='DEFAULT'):
        """Check restart happens on config change by flipping debug mode.

        Change debug mode and assert that change propagates to the correct
        file and that services are restarted as a result. config_file must be
        an oslo config file and debug option must be set in the
        `config_section` section.

        :param config_file: OSLO Config file to check for settings
        :type config_file: str
        :param services: Services expected to be restarted when config_file is
                         changed.
        :type services: list
        """
        # Expected default and alternate values
        current_value = model.get_application_config(
            self.application_name)['debug']['value']
        new_value = str(not bool(current_value)).title()
        current_value = str(current_value).title()

        set_default = {'debug': current_value}
        set_alternate = {'debug': new_value}
        default_entry = {config_section: {'debug': [current_value]}}
        alternate_entry = {config_section: {'debug': [new_value]}}

        # Make config change, check for service restarts
        logging.info(
            'Changing settings on {} to {}'.format(
                self.application_name, set_alternate))
        self.restart_on_changed(
            config_file,
            set_default,
            set_alternate,
            default_entry,
            alternate_entry,
            services)

    def restart_on_changed(self, config_file, default_config, alternate_config,
                           default_entry, alternate_entry, services,
                           pgrep_full=False):
        """Run restart on change tests.

        Test that changing config results in config file being updated and
        services restarted. Return config to default_config afterwards

        :param config_file: Config file to check for settings
        :type config_file: str
        :param default_config: Dict of charm settings to set on completion
        :type default_config: dict
        :param alternate_config: Dict of charm settings to change to
        :type alternate_config: dict
        :param default_entry: Config file entries that correspond to
                              default_config
        :type default_entry: dict
        :param alternate_entry: Config file entries that correspond to
                                alternate_config
        :type alternate_entry: dict
        :param services: Services expected to be restarted when config_file is
                         changed.
        :type services: list
        :param pgrep_full: Should pgrep be used rather than pidof to identify
                           a service.
        :type  pgrep_full: bool
        """
        # lead_unit is only useed to grab a timestamp, the assumption being
        # that all the units times are in sync.

        mtime = model.get_unit_time(
            self.lead_unit,
            model_name=self.model_name)
        logging.debug('Remote unit timestamp {}'.format(mtime))

        with self.config_change(default_config, alternate_config):
            # If this is not an OSLO config file set default_config={}
            if alternate_entry:
                logging.debug(
                    'Waiting for updates to propagate to {}'
                    .format(config_file))
                model.block_until_oslo_config_entries_match(
                    self.application_name,
                    config_file,
                    alternate_entry,
                    model_name=self.model_name)
            else:
                model.block_until_all_units_idle(model_name=self.model_name)

            # Config update has occured and hooks are idle. Any services should
            # have been restarted by now:
            logging.debug(
                'Waiting for services ({}) to be restarted'.format(services))
            model.block_until_services_restarted(
                self.application_name,
                mtime,
                services,
                model_name=self.model_name,
                pgrep_full=pgrep_full)

        # If this is not an OSLO config file set default_config={}
        if default_entry:
            logging.debug(
                'Waiting for updates to propagate to {}'.format(config_file))
            model.block_until_oslo_config_entries_match(
                self.application_name,
                config_file,
                default_entry,
                model_name=self.model_name)
        else:
            model.block_until_all_units_idle(model_name=self.model_name)

    @contextlib.contextmanager
    def pause_resume(self, services, pgrep_full=False):
        """Run Pause and resume tests.

        Pause and then resume a unit checking that services are in the
        required state after each action

        :param services: Services expected to be restarted when the unit is
                         paused/resumed.
        :type services: list
        :param pgrep_full: Should pgrep be used rather than pidof to identify
                           a service.
        :type  pgrep_full: bool
        """
        model.block_until_service_status(
            self.lead_unit,
            services,
            'running',
            model_name=self.model_name,
            pgrep_full=pgrep_full)
        model.block_until_unit_wl_status(
            self.lead_unit,
            'active',
            model_name=self.model_name)
        generic_utils.assertActionRanOK(model.run_action(
            self.lead_unit,
            'pause',
            model_name=self.model_name))
        model.block_until_unit_wl_status(
            self.lead_unit,
            'maintenance',
            model_name=self.model_name)
        model.block_until_all_units_idle(model_name=self.model_name)
        model.block_until_service_status(
            self.lead_unit,
            services,
            'stopped',
            model_name=self.model_name,
            pgrep_full=pgrep_full)
        yield
        generic_utils.assertActionRanOK(model.run_action(
            self.lead_unit,
            'resume',
            model_name=self.model_name))
        model.block_until_unit_wl_status(
            self.lead_unit,
            'active',
            model_name=self.model_name)
        model.block_until_all_units_idle(model_name=self.model_name)
        model.block_until_service_status(
            self.lead_unit,
            services,
            'running',
            model_name=self.model_name,
            pgrep_full=pgrep_full)

    def get_my_tests_options(self, key, default=None):
        """Retrieve tests_options for specific test.

        Prefix for key is built from dot-notated absolute path to calling
        method or function.

        Example:
           # In tests.yaml:
           tests_options:
             zaza.charm_tests.noop.tests.NoopTest.test_foo.key: true
           # called from zaza.charm_tests.noop.tests.NoopTest.test_foo()
           >>> get_my_tests_options('key')
           True

        :param key: Suffix for tests_options key.
        :type key: str
        :param default: Default value to return if key is not found.
        :type default: any
        :returns: Value associated with key in tests_options.
        :rtype: any
        """
        # note that we need to do this in-line otherwise we would get the path
        # to ourself. I guess we could create a common method that would go two
        # frames back, but that would be kind of useless for anyone else than
        # this method.
        caller_path = []

        # get path to module
        caller_path.append(sys.modules[
            sys._getframe().f_back.f_globals['__name__']].__name__)

        # attempt to get class name
        try:
            caller_path.append(
                sys._getframe().f_back.f_locals['self'].__class__.__name__)
        except KeyError:
            pass

        # get method or function name
        caller_path.append(sys._getframe().f_back.f_code.co_name)

        return self.test_config.get('tests_options', {}).get(
            '.'.join(caller_path + [key]), default)


class OpenStackBaseTest(BaseCharmTest):
    """Generic helpers for testing OpenStack API charms."""

    @classmethod
    def setUpClass(cls, application_name=None, model_alias=None):
        """Run setup for test class to create common resources."""
        super(OpenStackBaseTest, cls).setUpClass(application_name, model_alias)
        cls.keystone_session = openstack_utils.get_overcloud_keystone_session(
            model_name=cls.model_name)
        cls.cacert = openstack_utils.get_cacert()
        cls.nova_client = (
            openstack_utils.get_nova_session_client(cls.keystone_session))

    def resource_cleanup(self):
        """Remove test resources."""
        try:
            logging.info('Removing instances launched by test ({}*)'
                         .format(self.RESOURCE_PREFIX))
            for server in self.nova_client.servers.list():
                if server.name.startswith(self.RESOURCE_PREFIX):
                    openstack_utils.delete_resource(
                        self.nova_client.servers,
                        server.id,
                        msg="server")
        except AssertionError as e:
            # Resource failed to be removed within the expected time frame,
            # log this fact and carry on.
            logging.warning('Gave up waiting for resource cleanup: "{}"'
                            .format(str(e)))
        except AttributeError:
            # Test did not define self.RESOURCE_PREFIX, ignore.
            pass

    def launch_guest(self, guest_name, userdata=None, use_boot_volume=False,
                     instance_key=None):
        """Launch two guests to use in tests.

        Note that it is up to the caller to have set the RESOURCE_PREFIX class
        variable prior to calling this method.

        Also note that this method will remove any already existing instance
        with same name as what is requested.

        :param guest_name: Name of instance
        :type guest_name: str
        :param userdata: Userdata to attach to instance
        :type userdata: Optional[str]
        :param use_boot_volume: Whether to boot guest from a shared volume.
        :type use_boot_volume: boolean
        :param instance_key: Key to collect associated config data with.
        :type instance_key: Optional[str]
        :returns: Nova instance objects
        :rtype: Server
        """
        instance_key = instance_key or glance_setup.LTS_IMAGE_NAME
        instance_name = '{}-{}'.format(self.RESOURCE_PREFIX, guest_name)

        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_attempt(3),
                wait=tenacity.wait_exponential(
                    multiplier=1, min=2, max=10)):
            with attempt:
                old_instance_with_same_name = self.retrieve_guest(
                    instance_name)
                if old_instance_with_same_name:
                    logging.info(
                        'Removing already existing instance ({}) with '
                        'requested name ({})'
                        .format(old_instance_with_same_name.id, instance_name))
                    openstack_utils.delete_resource(
                        self.nova_client.servers,
                        old_instance_with_same_name.id,
                        msg="server")

                return configure_guest.launch_instance(
                    instance_key,
                    vm_name=instance_name,
                    use_boot_volume=use_boot_volume,
                    userdata=userdata)

    def launch_guests(self, userdata=None):
        """Launch two guests to use in tests.

        Note that it is up to the caller to have set the RESOURCE_PREFIX class
        variable prior to calling this method.

        :param userdata: Userdata to attach to instance
        :type userdata: Optional[str]
        :returns: List of launched Nova instance objects
        :rtype: List[Server]
        """
        launched_instances = []
        for guest_number in range(1, 2+1):
            launched_instances.append(
                self.launch_guest(
                    guest_name='ins-{}'.format(guest_number),
                    userdata=userdata))
        return launched_instances

    def retrieve_guest(self, guest_name):
        """Return guest matching name.

        :param nova_client: Nova client to use when checking status
        :type nova_client: Nova client
        :returns: the matching guest
        :rtype: Union[novaclient.Server, None]
        """
        try:
            return self.nova_client.servers.find(name=guest_name)
        except novaclient.exceptions.NotFound:
            return None

    def retrieve_guests(self):
        """Return test guests.

        Note that it is up to the caller to have set the RESOURCE_PREFIX class
        variable prior to calling this method.

        :param nova_client: Nova client to use when checking status
        :type nova_client: Nova client
        :returns: the matching guest
        :rtype: Union[novaclient.Server, None]
        """
        instance_1 = self.retrieve_guest(
            '{}-ins-1'.format(self.RESOURCE_PREFIX))
        instance_2 = self.retrieve_guest(
            '{}-ins-1'.format(self.RESOURCE_PREFIX))
        return instance_1, instance_2
