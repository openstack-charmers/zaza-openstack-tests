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
import yaml

import novaclient

import zaza.model as model
import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.openstack.configure.guest as configure_guest
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.utilities.machine_os


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
    """Run decorator to skip this test if application version is too low.

    :param service: the name of the application to check the package's version
    :param package: the name of the package to check
    :param releases: package version to compare with.
    """
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


def package_version_matches(application, package, versions, op):
    """Determine if the application is running any matching package versions.

    The version comparison is delegated to `dpkg --compare-versions`, if the
    command returns 0, means the version matches.

    Usage examples:

    * Return true if hacluster application has crmsh-4.4.0-1ubuntu1 installed

        def test_hacluster():
            if package_version_matches('keystone-hacluster', 'crmsh',
                                       ['4.4.0-1ubuntu1'], 'eq')
                return
            ...

    :param application: the name of the application to check the package's
           versions.
    :param package: the name of the package to check
    :param versions: list of versions to compare with
    :param op: operation to do the comparison (e.g. lt le eq ne ge gt, see for
               more details dpkg(1))
    :return: Matching package version
    :rtype: str

    """
    package_version = generic_utils.get_pkg_version(application, package)
    for version in versions:
        p = subprocess.run(['dpkg', '--compare-versions',
                            package_version, op, version],
                           stderr=subprocess.STDOUT,
                           universal_newlines=True)
        if p.returncode == 0:
            logging.info("Package version {version} matches")
            return package_version
    return None


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
        """Run setup for test class to create common resources.

        Note: the derived class may not use the application_name; if it's set
        to None then this setUpClass() method will attempt to extract the
        application name from the charm_config (essentially the test.yaml)
        using the key 'charm_name' in the test_config.  If that isn't present,
        then there will be no application_name set, and this is considered a
        generic scenario of a whole model rather than a particular charm under
        test.

        :param application_name: the name of the applications that the derived
            class is testing.  If None, then it's a generic test not connected
            to any single charm.
        :type application_name: Optional[str]
        :param model_alias: the alias to use if needed.
        :type model_alias: Optional[str]
        """
        cls.model_aliases = model.get_juju_model_aliases()
        if model_alias:
            cls.model_name = cls.model_aliases[model_alias]
        else:
            cls.model_name = model.get_juju_model()
        cls.test_config = lifecycle_utils.get_charm_config(fatal=False)

        if application_name:
            cls.application_name = application_name
        else:
            try:
                charm_under_test_name = cls.test_config['charm_name']
            except KeyError:
                logging.warning("No application_name and no charm config so "
                                "not setting the application_name. Likely a "
                                "scenario test.")
                return
            deployed_app_names = model.sync_deployed(model_name=cls.model_name)
            if charm_under_test_name in deployed_app_names:
                # There is an application named like the charm under test.
                # Let's consider it the application under test:
                cls.application_name = charm_under_test_name
            else:
                # Let's search for any application whose name starts with the
                # name of the charm under test and assume it's the application
                # under test:
                for app_name in deployed_app_names:
                    if app_name.startswith(charm_under_test_name):
                        cls.application_name = app_name
                        break
                else:
                    logging.warning('Could not find application under test')
                    return

        cls.lead_unit = model.get_lead_unit_name(
            cls.application_name,
            model_name=cls.model_name)
        logging.debug('Leader unit is {}'.format(cls.lead_unit))

    def config_current_separate_non_string_type_keys(
            self, non_string_type_keys, config_keys=None,
            application_name=None):
        """Obtain current config and the non-string type config separately.

        If the charm config option is not string, it will not accept being
        reverted back in "config_change()" method if the current value is None.
        Therefore, obtain the current config and separate those out, so they
        can be used for a separate invocation of "config_change()" with
        reset_to_charm_default set to True.

        :param config_keys: iterable of strs to index into the current config.
                            If None, return all keys from the config
        :type config_keys:  Optional[Iterable[str]]
        :param non_string_type_keys: list of non-string type keys to be
                                     separated out only if their current value
                                     is None
        :type non_string_type_keys: list
        :param application_name: String application name for use when called
                                 by a charm under test other than the object's
                                 application.
        :type application_name:  Optional[str]
        :return: Dictionary of current charm configs without the
                 non-string type keys provided, and dictionary of the
                 non-string keys found in the supplied config_keys list.
        :rtype: Dict[str, Any], Dict[str, None]
        """
        current_config = self.config_current(application_name, config_keys)
        non_string_type_config = {}
        if config_keys is None:
            config_keys = list(current_config.keys())
        for key in config_keys:
            # We only care if the current value is None, otherwise it will
            # not face issues being reverted by "config_change()"
            if key in non_string_type_keys and current_config[key] is None:
                non_string_type_config[key] = None
                current_config.pop(key)

        return current_config, non_string_type_config

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
                                           list(alternate_config.keys()),
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

    def get_applications_with_substring_in_name(self, substring):
        """Get applications with substring in name.

        :param substring: String to search for in application names
        :type substring: str
        :returns: List of matching applictions
        :rtype: List
        """
        status = model.get_status().applications
        applications = []
        for application in status.keys():
            if substring in application:
                applications.append(application)
        return applications

    def run_update_status_hooks(self, units):
        """Run update status hooks on units.

        :param units: List of unit names or unit.entity_id
        :type units: List[str]
        :returns: None
        :rtype: None
        """
        for unit in units:
            model.run_on_unit(unit, "hooks/update-status")

    def assert_unit_cpu_topology(self, unit, nr_1g_hugepages):
        r"""Assert unit under test CPU topology.

        When using OpenStack as CI substrate:

        By default, when instance NUMA placement is not specified,
        a topology of N sockets, each with one core and one thread,
        is used for an instance, where N corresponds to the number of
        instance vCPUs requested.

        In this context a socket is a physical socket on the motherboard
        where a CPU is connected.

        The DPDK Environment Abstraction Layer (EAL) allocates memory per
        CPU socket, so we want the CPU topology inside the instance to
        mimic something we would be likely to find in the real world and
        at the same time not make the test too heavy.

        The charm default is to have Open vSwitch allocate 1GB RAM per
        CPU socket.

        The following command would set the apropriate CPU topology for a
        4 VCPU, 8 GB RAM flavor:

            openstack flavor set onesocketm1.large \
                --property hw:cpu_sockets=1 \
                --property hw:cpu_cores=2 \
                --property hw:cpu_threads=2

        For validation of operation with multiple sockets, the following
        command would set the apropriate CPU topology for a
        8 VCPU, 16GB RAM flavor:

            openstack flavor set twosocketm1.xlarge \
                --property hw:cpu_sockets=2 \
                --property hw:cpu_cores=2 \
                --property hw:cpu_threads=2 \
                --property hw:numa_nodes=2
        """
        # Get number of sockets
        cmd = 'lscpu -p|grep -v ^#|cut -f3 -d,|sort|uniq|wc -l'
        sockets = int(zaza.utilities.juju.remote_run(
            unit.name, cmd, model_name=self.model_name, fatal=True).rstrip())

        # Get total memory
        cmd = 'cat /proc/meminfo |grep ^MemTotal'
        _, meminfo_value, _ = zaza.utilities.juju.remote_run(
            unit.name,
            cmd,
            model_name=self.model_name,
            fatal=True).rstrip().split()
        mbtotal = int(meminfo_value) * 1024 / 1000 / 1000
        mbtotalhugepages = nr_1g_hugepages * 1024

        # headroom for operating system and daemons in instance
        mbsystemheadroom = 2048
        # memory to be consumed by the nested instance
        mbinstance = 1024

        # the amount of hugepage memory OVS / DPDK EAL will allocate
        mbovshugepages = sockets * 1024
        # the amount of hugepage memory available for nested instance
        mbfreehugepages = mbtotalhugepages - mbovshugepages

        assert (mbtotal - mbtotalhugepages >= mbsystemheadroom and
                mbfreehugepages >= mbinstance), (
            'Unit {} is not suitable for test, please adjust instance '
            'type CPU topology or provide suitable physical machine. '
            'CPU Sockets: {} '
            'Available memory: {} MB '
            'Details:\n{}'
            .format(unit.name,
                    sockets,
                    mbtotal,
                    self.assert_unit_cpu_topology.__doc__))

    def enable_hugepages_vfio_on_hvs_in_vms(self, nr_1g_hugepages):
        """Enable hugepages and unsafe VFIO NOIOMMU on virtual hypervisors."""
        for unit in model.get_units(
                zaza.utilities.machine_os.get_hv_application(),
                model_name=self.model_name):
            if not zaza.utilities.machine_os.is_vm(unit.name,
                                                   model_name=self.model_name):
                logging.info('Unit {} is a physical machine, assuming '
                             'hugepages and IOMMU configuration already '
                             'performed through kernel command line.')
                continue
            logging.info('Checking CPU topology on {}'.format(unit.name))
            self.assert_unit_cpu_topology(unit, nr_1g_hugepages)
            logging.info('Enabling hugepages on {}'.format(unit.name))
            zaza.utilities.machine_os.enable_hugepages(
                unit, nr_1g_hugepages, model_name=self.model_name)
            logging.info('Enabling unsafe VFIO NOIOMMU mode on {}'
                         .format(unit.name))
            zaza.utilities.machine_os.enable_vfio_unsafe_noiommu_mode(
                unit, model_name=self.model_name)

    def disable_hugepages_vfio_on_hvs_in_vms(self):
        """Disable hugepages and unsafe VFIO NOIOMMU on virtual hypervisors."""
        for unit in model.get_units(
                zaza.utilities.machine_os.get_hv_application(),
                model_name=self.model_name):
            if not zaza.utilities.machine_os.is_vm(unit.name,
                                                   model_name=self.model_name):
                logging.info('Unit {} is a physical machine, assuming '
                             'hugepages and IOMMU configuration already '
                             'performed through kernel command line.')
                continue
            logging.info('Disabling hugepages on {}'.format(unit.name))
            zaza.utilities.machine_os.disable_hugepages(
                unit, model_name=self.model_name)
            logging.info('Disabling unsafe VFIO NOIOMMU mode on {}'
                         .format(unit.name))
            zaza.utilities.machine_os.disable_vfio_unsafe_noiommu_mode(
                unit, model_name=self.model_name)


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
                     instance_key=None, flavor_name=None,
                     attach_to_external_network=False,
                     keystone_session=None):
        """Launch one guest to use in tests.

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
        :param attach_to_external_network: Attach instance directly to external
                                           network.
        :type attach_to_external_network: bool
        :param keystone_session: Keystone session to use.
        :type keystone_session: Optional[keystoneauth1.session.Session]
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
                    userdata=userdata,
                    flavor_name=flavor_name,
                    attach_to_external_network=attach_to_external_network,
                    keystone_session=keystone_session)

    def launch_guests(self, userdata=None, attach_to_external_network=False,
                      flavor_name=None):
        """Launch two guests to use in tests.

        Note that it is up to the caller to have set the RESOURCE_PREFIX class
        variable prior to calling this method.

        :param userdata: Userdata to attach to instance
        :type userdata: Optional[str]
        :param attach_to_external_network: Attach instance directly to external
                                           network.
        :type attach_to_external_network: bool
        :returns: List of launched Nova instance objects
        :rtype: List[Server]
        """
        launched_instances = []
        for guest_number in range(1, 2+1):
            launched_instances.append(
                self.launch_guest(
                    guest_name='ins-{}'.format(guest_number),
                    userdata=userdata,
                    attach_to_external_network=attach_to_external_network,
                    flavor_name=flavor_name))
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


class BaseDeferredRestartTest(BaseCharmTest):
    """Check deferred restarts.

    Example of adding a deferred restart test::

        class NeutronOVSDeferredRestartTest(
            test_utils.BaseDeferredRestartTest):

            @classmethod
            def setUpClass(cls):
                super().setUpClass(application_name='neutron-openvswitch')

            def run_tests(self):
                # Trigger a config change which triggers a deferred hook.
                self.run_charm_change_hook_test('config-changed')

                # Trigger a package change which requires a restart
                self.run_package_change_test(
                    'openvswitch-switch',
                    'openvswitch-switch')


    NOTE: The test has been broken into various class methods which may require
          specialisation if the charm being tested is not a standard OpenStack
          charm e.g. `trigger_deferred_hook_via_charm` if the charm is not
          an oslo config or does not have a debug option.
    """

    @classmethod
    def setUpClass(cls, application_name):
        """Run test setup.

        :param application_name: Name of application to run tests against.
        :type application_name: str
        """
        cls.application_name = application_name
        super().setUpClass(application_name=cls.application_name)

    def check_status_message_is_clear(self):
        """Check each units status message show no defeerred events."""
        # Check workload status no longer shows deferred restarts.
        for unit in model.get_units(self.application_name):
            model.block_until_unit_wl_message_match(
                unit.entity_id,
                'Unit is ready')
        model.block_until_all_units_idle()

    def check_clear_restarts(self):
        """Clear and deferred restarts and check status.

        Clear and deferred restarts and then check the workload status message
        for each unit.
        """
        # Use action to run any deferred restarts
        for unit in model.get_units(self.application_name):
            logging.info("Running restart-services on {}".format(
                unit.entity_id))
            model.run_action(
                unit.entity_id,
                'restart-services',
                action_params={'deferred-only': True},
                raise_on_failure=True)

        # Check workload status no longer shows deferred restarts.
        self.check_status_message_is_clear()

    def clear_hooks(self):
        """Clear and deferred hooks.

        Run any deferred hooks.
        """
        # Use action to run any deferred restarts
        for unit in model.get_units(self.application_name):
            logging.info("Running run-deferred-hooks on {}".format(
                unit.entity_id))
            model.run_action(
                unit.entity_id,
                'run-deferred-hooks',
                raise_on_failure=True)

    def check_clear_hooks(self):
        """Clear deferred hooks and check status.

        Clear deferred hooks and then check the workload status message
        for each unit.
        """
        self.clear_hooks()
        # Check workload status no longer shows deferred restarts.
        self.check_status_message_is_clear()

    def run_show_deferred_events_action(self):
        """Run show-deferred-events and return results.

        :returns: Data from action run
        :rtype: Dict
        """
        unit = model.get_units(self.application_name)[0]
        action = model.run_action(
            unit.entity_id,
            'show-deferred-events',
            raise_on_failure=True)
        return yaml.safe_load(action.data['results']['output'])

    def check_show_deferred_events_action_restart(self, test_service,
                                                  restart_reason):
        """Check the output from the action to list deferred restarts.

        Run the action to list any deferred restarts and check it has entry for
        the given service and reason.

        :param test_service: Service that should need a restart
        :type test_service: str
        :param restart_reason: The reason the action should list for the
                               service needing to be restarted. This can be a
                               substring.
        :type restart_reason: str
        """
        # Ensure that the deferred restart and cause are listed via action
        logging.info(
            ("Checking {} is marked as needing restart in "
             "show-deferred-events action").format(
                test_service))
        for event in self.run_show_deferred_events_action()['restarts']:
            logging.info("{} in {} and {} in {}".format(
                test_service,
                event,
                restart_reason,
                event))
            if test_service in event and restart_reason in event:
                break
        else:
            msg = 'No entry for restart of {} for reason {} found'.format(
                test_service,
                restart_reason)
            raise Exception(msg)

    def check_show_deferred_events_action_hook(self, hook):
        """Check the output from the action to list deferred eveents.

        Run the action to list any deferred events and check it has entry for
        the given hook.

        :param hook: Hook or method name
        :type hook: str
        """
        # Ensure that the deferred restart and cause are listed via action
        logging.info(
            ("Checking {} is marked as skipped in "
             "show-deferred-events action").format(hook))
        for event in self.run_show_deferred_events_action()['hooks']:
            logging.info("{} in {}".format(hook, event))
            if hook in event:
                break
        else:
            msg = '{} not found in {}'.format(hook, event)
            raise Exception(msg)

    def check_show_deferred_restarts_wlm(self, test_service):
        """Check the workload status message lists deferred restart.

        :param test_service: Service that should need a restart
        :type test_service: str
        """
        # Ensure that the deferred restarts are visible in Juju status
        for unit in model.get_units(self.application_name):
            # Just checking one example service should we be checking all?
            logging.info(
                ("Checking {} is marked as needing restart in workload "
                 "message of {}".format(test_service, unit.entity_id)))
            assert test_service in unit.workload_status_message

    def check_deferred_hook_wlm(self, deferred_hook):
        """Check the workload status message lists deferred event.

        :param deferred_hook: Hook or method name which should be showing as
                              deferred.
        :type deferred_hook: str
        """
        # Ensure that the deferred restarts are visible in Juju status
        for unit in model.get_units(self.application_name):
            logging.info(
                ("Checking {} is marked as having deferred hook in workload "
                 "message".format(unit.entity_id)))
            assert deferred_hook in unit.workload_status_message

    def get_new_config(self):
        """Return the config key and new value to trigger a hook execution.

        NOTE: The implementation assumes the charm has a `debug` option and
              If that is not true the derived class should override this
              method.
        :returns: Config key and new value
        :rtype: (str, bool)
        """
        app_config = model.get_application_config(self.application_name)
        return 'debug', str(not app_config['debug']['value'])

    def set_new_config(self):
        """Change applications charm config."""
        logging.info("Triggering deferred restart via config change")
        config_key, new_value = self.get_new_config()
        logging.info("Setting {}: {}".format(config_key, new_value))
        model.set_application_config(
            self.application_name,
            {config_key: new_value})
        return new_value

    def trigger_deferred_restart_via_charm(self, restart_config_file):
        """Set charm config option which requires a service start.

        Set the charm debug option and wait for that change to be renderred in
        applications config file.

        NOTE: The implementation assumes the restart_config_file in an oslo
              config file. If that is not true the derived class should
              override this method.

        :param restart_config_file: Config file that updated value is expected
                                    in.
        :type restart_config_file: str
        """
        new_debug_value = self.set_new_config()
        expected_contents = {
            'DEFAULT': {
                'debug': [new_debug_value]}}
        logging.info("Waiting for debug to be {} in {}".format(
            new_debug_value,
            restart_config_file))
        model.block_until_oslo_config_entries_match(
            self.application_name,
            restart_config_file,
            expected_contents)
        logging.info("Waiting for units to be idle")
        model.block_until_all_units_idle()

    def trigger_deferred_hook_via_charm(self, deferred_hook):
        """Set charm config option which requires a service start.

        Set the charm debug option and wait for that change to be rendered in
        applications config file.

        :param deferred_hook: Hook or method name which should be showing as
                              deferred.
        :type deferred_hook: str
        :returns: New config value
        :rtype: Union[str, int, float]
        """
        new_debug_value = self.set_new_config()
        for unit in model.get_units(self.application_name):
            logging.info('Waiting for {} to show deferred hook'.format(
                unit.entity_id))
            model.block_until_unit_wl_message_match(
                unit.entity_id,
                status_pattern='.*{}.*'.format(deferred_hook))
        logging.info("Waiting for units to be idle")
        model.block_until_all_units_idle()
        return new_debug_value

    def trigger_deferred_restart_via_package(self, restart_package):
        """Update a package which requires a service restart.

        :param restart_package: Package that will be changed to trigger a
                                service restart.
        :type restart_package: str
        """
        logging.info("Triggering deferred restart via package change")
        # Test restart requested by package
        for unit in model.get_units(self.application_name):
            model.run_on_unit(
                unit.entity_id,
                ('dpkg-reconfigure {}; '
                 'JUJU_HOOK_NAME=update-status ./hooks/update-status').format(
                    restart_package))

    def run_charm_change_restart_test(self, test_service, restart_config_file):
        """Trigger a deferred restart by updating a config file via the charm.

        Trigger a hook in the charm which the charm will defer.

        :param test_service: Service that should need a restart
        :type test_service: str
        :param restart_config_file: Config file that updated value is expected
                                    in.
        :type restart_config_file: str
        """
        self.trigger_deferred_restart_via_charm(restart_config_file)

        self.check_show_deferred_restarts_wlm(test_service)
        self.check_show_deferred_events_action_restart(
            test_service,
            restart_config_file)
        logging.info("Running restart action to clear deferred restarts")
        self.check_clear_restarts()

    def run_charm_change_hook_test(self, deferred_hook):
        """Trigger a deferred restart by updating a config file via the charm.

        :param deferred_hook: Hook or method name which should be showing as
                              defeerred.
        :type deferred_hook: str
        """
        self.trigger_deferred_hook_via_charm(deferred_hook)

        self.check_deferred_hook_wlm(deferred_hook)
        self.check_show_deferred_events_action_hook(deferred_hook)
        # Rerunning to flip config option back to previous value.
        self.trigger_deferred_hook_via_charm(deferred_hook)
        logging.info("Running restart action to clear deferred hooks")
        # If there are a number of units in the application and restarts take
        # time then another deferred hook can occur so do not block on a
        # clear status message.
        self.clear_hooks()

    def get_service_timestamps(self, service):
        """For units of self.application_name get start time of service.

        :param service: Service to check, must be a systemd service
        :type service: str
        :returns: A dict timestamps keyed on unit name.
        :rtype: dict
        """
        timestamps = {}
        for unit in model.get_units(self.application_name):
            timestamps[unit.entity_id] = model.get_systemd_service_active_time(
                unit.entity_id,
                service)
        return timestamps

    def run_package_change_test(self, restart_package, restart_package_svc):
        """Trigger a deferred restart by updating a package.

        Update a package which requires will add a deferred restart.

        :param restart_package: Package that will be changed to trigger a
                                service restart.
        :type restart_package: str
        :param restart_package_service: Service that will require a restart
                                        after restart_package has changed.
        :type restart_package_service: str
        """
        pre_timestamps = self.get_service_timestamps(
            restart_package_svc)
        self.trigger_deferred_restart_via_package(restart_package)
        post_timestamps = self.get_service_timestamps(
            restart_package_svc)
        broken_units = []
        for unit_name in post_timestamps.keys():
            if pre_timestamps[unit_name] != post_timestamps[unit_name]:
                logging.error(
                    "Service {} on unit {} should have start time of {} but"
                    " it has {}".format(
                        restart_package_svc,
                        unit_name,
                        pre_timestamps[unit_name],
                        post_timestamps[unit_name]))
                broken_units.append(unit_name)
        if broken_units:
            msg = (
                "Units {} restarted service {} when disallowed by "
                "deferred_restarts").format(
                    ','.join(broken_units),
                    restart_package_svc)
            raise Exception(msg)
        else:
            logging.info(
                "Service was {} not restarted.".format(restart_package_svc))
        self.check_show_deferred_restarts_wlm(restart_package_svc)
        self.check_show_deferred_events_action_restart(
            restart_package_svc,
            'Package update')
        logging.info("Running restart action to clear deferred restarts")
        self.check_clear_restarts()

    def run_tests(self):
        """Run charm tests. should specify which tests to run.

        The charm test that implements this test should specify which tests to
        run, for example:

            def run_tests(self):
                # Trigger a config change which triggers a deferred hook.
                self.run_charm_change_hook_test('config-changed')

                # Trigger a config change which requires a restart
                self.run_charm_change_restart_test(
                    'neutron-l3-agent',
                    '/etc/neutron/neutron.conf')

                # Trigger a package change which requires a restart
                self.run_package_change_test(
                    'openvswitch-switch',
                    'openvswitch-switch')
        """
        raise NotImplementedError

    def test_deferred_restarts(self):
        """Run deferred restart tests."""
        app_config = model.get_application_config(self.application_name)
        auto_restart_config_key = 'enable-auto-restarts'
        if auto_restart_config_key not in app_config:
            raise unittest.SkipTest("Deferred restarts not implemented")

        # Ensure auto restarts are off.
        policy_file = '/etc/policy-rc.d/charm-{}.policy'.format(
            self.application_name)
        if app_config[auto_restart_config_key]['value']:
            logging.info("Turning off auto restarts")
            model.set_application_config(
                self.application_name, {auto_restart_config_key: 'False'})
            logging.info("Waiting for {} to appear on units of {}".format(
                policy_file,
                self.application_name))
            model.block_until_file_has_contents(
                self.application_name,
                policy_file,
                'policy_requestor_name')
            # The block_until_file_has_contents ensures the change we waiting
            # for has happened, now just wait for any hooks to finish.
            logging.info("Waiting for units to be idle")
            model.block_until_all_units_idle()
        else:
            logging.info("Auto restarts already disabled")

        self.run_tests()

        # Finished so turn auto-restarts back on.
        logging.info("Turning on auto restarts")
        model.set_application_config(
            self.application_name, {auto_restart_config_key: 'True'})
        model.block_until_file_missing(
            self.application_name,
            policy_file)
        model.block_until_all_units_idle()
        self.check_clear_hooks()
