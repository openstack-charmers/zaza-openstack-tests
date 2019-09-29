# Copyright 2019 Canonical Ltd.
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

"""Encapsulate policyd testing.

The Policyd Tests test the following:

- Two general tests in the PolicydTest class that check that a policy zip can
  drop policy files in the correct service policy.d directory.  One test tests
  that a valid yaml file is dropped; the 2nd that an invalid one is not dropped
  and the workload info status line shows that it is broken.
- A custom policyd test that is per charm and tests that a policy zip file
  attached does actually disable something in the associated service (i.e.
  verify that the charm has implemented policy overrides and ensured that the
  service actually picks them up).

In order to use the generic tests, just include them in the specific test
class.  The KeystonePolicydTest as an example does:

    class KeystonePolicydTest(PolicydTest,
                              ch_keystone.BaseKeystoneTest,
                              test_utils.OpenStackBaseTest):

        @classmethod
        def setUpClass(cls, application_name=None):
            super(KeystonePolicydTest, cls).setUpClass(application_name)

Note that the generic test class (PolicyDTest) comes first, and then the
ch_keystone.BaseKeystoneTest, followed by the test_utils.OpenStackBaseTest.
This is to get the order of super().setUpClass(...) calls to work with
application_name.

If a charm doesn't require a specific test, then the GenericPolicydTest class
can be used that just includes the two generic tests.  The config in the
tests.yaml would stil be required.  See the PolicydTest class docstring for
further details.
"""

import logging
import os
import shutil
import tempfile
import zipfile

import keystoneauth1

import zaza.model as zaza_model

import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.keystone as ch_keystone
import zaza.openstack.utilities.exceptions as zaza_exceptions


class PolicydTest(object):
    """Charm operation tests.

    The policyd test needs some config from the tests.yaml in order to work
    properly.  A top level key of "tests_options".  Under that key is
    'policyd', and then the k:v of 'service': <name>.  e.g. for keystone

    tests_options:
      policyd:
        service: keystone
    """

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running Policyd charm operation tests."""
        super(PolicydTest, cls).setUpClass(application_name)
        if (openstack_utils.get_os_release() <
                openstack_utils.get_os_release('xenial_queens')):
            cls.SkipTest("Test not valid before xenial_queens")
        cls._tmp_dir = tempfile.mkdtemp()
        cls._service_name = \
            cls.test_config['tests_options']['policyd']['service']

    @classmethod
    def tearDownClass(cls):
        """Run class tearDown for running Policyd charm operation tests."""
        super(PolicydTest, cls).tearDownClass()
        try:
            shutil.rmtree(cls._tmp_dir, ignore_errors=True)
        except Exception as e:
            logging.error("Removing the policyd tempdir/files failed: {}"
                          .format(str(e)))

    def _set_config(self, state):
        s = "True" if state else "False"
        config = {"use-policyd-override": s}
        logging.info("Setting config to {}".format(config))
        zaza_model.set_application_config(self.application_name, config)

    def _make_zip_file_from(self, name, files):
        """Make a zip file from a dictionary of filename: string.

        :param name: the name of the zip file
        :type name: PathLike
        :param files: a dict of name: string to construct the files from.
        :type files: Dict[str, str]
        :returns: temp file that is the zip file.
        :rtype: PathLike
        """
        path = os.path.join(self._tmp_dir, name)
        with zipfile.ZipFile(path, "w") as zfp:
            for name, contents in files.items():
                zfp.writestr(name, contents)
        return path

    def _set_policy_with(self, rules):
        rules_zip_path = self._make_zip_file_from('rules.zip', rules)
        zaza_model.attach_resource(self.application_name,
                                   'policyd-override',
                                   rules_zip_path)
        self._set_config(True)
        zaza_model.block_until_wl_status_info_starts_with(
            self.application_name, "PO:", negate_match=False)

    def test_002_policyd_bad_yaml(self):
        """Test bad yaml file in the zip file is handled."""
        bad = {
            "file2.yaml": "{'rule': '!}"
        }
        bad_zip_path = self._make_zip_file_from('bad.zip', bad)
        logging.info("Attaching bad zip file as a resource")
        zaza_model.attach_resource(self.application_name,
                                   'policyd-override',
                                   bad_zip_path)
        zaza_model.block_until_all_units_idle()
        logging.debug("Now setting config to true")
        self._set_config(True)
        # ensure that the workload status info line starts with PO (broken):
        # to show that it didn't work
        logging.info(
            "Checking for workload status line starts with PO (broken):")
        zaza_model.block_until_wl_status_info_starts_with(
            self.application_name, "PO (broken):")
        logging.debug("App status is valid for broken yaml file")
        zaza_model.block_until_all_units_idle()
        # now verify that no file got landed on the machine
        path = os.path.join(
            "/etc", self._service_name, "policy.d", 'file2.yaml')
        logging.info("Now checking that file {} is not present.".format(path))
        zaza_model.block_until_file_missing(self.application_name, path)
        self._set_config(False)
        zaza_model.block_until_all_units_idle()
        logging.info("OK")


class GenericPolicydTest(PolicydTest, test_utils.OpenStackBaseTest):
    """Generic policyd test for any charm without a specific test.

    It includes a single additional test to test_002_policyd_bad_yaml() in the
    base class PolicydTest which checks that a good yaml file is placed into
    the correct directory.  This additional test (test_001_policyd_good_yaml)
    is not needed in the specialised tests as the feature is implicitly tested
    when the specialised test fails with the rule overrided.
    """

    def test_001_policyd_good_yaml(self):
        """Test that the policyd with a good zipped yaml file."""
        good = {
            'file1.yaml': "{'rule1': '!'}"
        }
        good_zip_path = self._make_zip_file_from('good.zip', good)
        logging.info("Attaching good zip file as a resource.")
        zaza_model.attach_resource(self.application_name,
                                   'policyd-override',
                                   good_zip_path)
        zaza_model.block_until_all_units_idle()
        logging.debug("Now setting config to true")
        self._set_config(True)
        # check that the file gets to the right location
        path = os.path.join(
            "/etc", self._service_name, "policy.d", 'file1.yaml')
        logging.info("Now checking for file contents: {}".format(path))
        zaza_model.block_until_file_has_contents(self.application_name,
                                                 path,
                                                 "rule1: '!'")
        # ensure that the workload status info line starts with PO:
        logging.info("Checking for workload status line starts with PO:")
        zaza_model.block_until_wl_status_info_starts_with(
            self.application_name, "PO:")
        logging.debug("App status is valid")

        # disable the policy override
        logging.info("Disabling policy override by setting config to false")
        self._set_config(False)
        # check that the status no longer has "PO:" on it.
        # we have to do it twice due to async races and that some info lines
        # erase the PO: bit prior to actuall getting back to idle.  The double
        # check verifies that the charms have started, the idle waits until it
        # is finished, and then the final check really makes sure they got
        # switched off.
        zaza_model.block_until_wl_status_info_starts_with(
            self.application_name, "PO:", negate_match=True)
        zaza_model.block_until_all_units_idle()
        zaza_model.block_until_wl_status_info_starts_with(
            self.application_name, "PO:", negate_match=True)

        # verify that the file no longer exists
        logging.info("Checking that {} has been removed".format(path))
        zaza_model.block_until_file_missing(self.application_name, path)

        logging.info("OK")


class PolicydOperationFailedException(Exception):
    """This is raised by the get_client_and_attempt_operation() method.

    This is used to signal that the operation in the
    get_client_and_attempt_operation() method in the BaseSpecialization class
    has failed.
    """

    pass


class BasePolicydSpecialization(PolicydTest,
                                ch_keystone.BaseKeystoneTest,
                                test_utils.OpenStackBaseTest):
    """Base test for specialising Policyd override tests

    This class is for specialization of the test to verify that a yaml file
    placed in the policy.d director is observed.  This is done by first calling
    the get_client_and_attempt_operation() method and ensuring that it works.
    This method should attempt an operation on the service that can be blocked
    by the policy override in the `_rule` class variable.  The method should
    pass cleanly without the override in place.

    The test_003_test_overide_is_observed will then apply the override and then
    call get_client_and_attempt_operation() again, and this time it should
    detect the failure and raise the PolicydOperationFailedException()
    exception.  This will be detected as the override working and thus the test
    will pass.

    The test will fail if the first call fails for any reason, or if the 2nd
    call doesn't raise PolicydOperationFailedException or raises any other
    exception.
    """

    # this needs to be defined as the rule that gets placed into a yaml policy
    # override.  It is a string of the form: 'some-rule: "!"'
    # i.e. disable some policy and then try and test it.
    _rule = None

    # the name to log at the beginning of the test
    _test_name = None

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running KeystonePolicydTest tests."""
        super(BasePolicydSpecialization, cls).setUpClass(application_name)
        if cls._rule is None:
            cls.SkipTest("Test not valid if {}.rule is not configured"
                         .format(cls.__name__))
            return

    def get_client_and_attempt_operation(self, keystone_session):
        """Override this method to perform the operation.

        This operation should pass normally for the demo_user, and fail when
        the rule has been overriden (see the `rule` class variable.

        :param keystone_session: the keystone session to use to obtain the
            client necessary for the test.
        :type keystone_session: ???
        :raises: PolicydOperationFailedException if operation fails.
        """
        raise NotImplementedError("This method must be overridden")

    def _get_keystone_session(self, ip):
        """Return the keystone session for the IP address passed.

        :param ip: the IP address to get the session against.
        :type ip: str
        :returns: a keystone session to the IP address
        :rtype: ???
        """
        logging.info('keystone IP {}'.format(ip))
        openrc = {
            'API_VERSION': 3,
            'OS_USERNAME': ch_keystone.DEMO_ADMIN_USER,
            'OS_PASSWORD': ch_keystone.DEMO_ADMIN_USER_PASSWORD,
            'OS_AUTH_URL': 'http://{}:5000/v3'.format(ip),
            'OS_USER_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
            'OS_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
        }
        if self.tls_rid:
            openrc['OS_CACERT'] = \
                openstack_utils.KEYSTONE_LOCAL_CACERT
            openrc['OS_AUTH_URL'] = (
                openrc['OS_AUTH_URL'].replace('http', 'https'))
        logging.info('keystone IP {}'.format(ip))
        keystone_session = openstack_utils.get_keystone_session(
            openrc, scope='DOMAIN')
        return keystone_session

    def test_003_test_overide_is_observed(self):
        """Test that the override is observed by the underlying service"""
        if self._test_name is None:
            logging.info("Doing policyd override for {}"
                         .format(self._service_name))
        else:
            logging.info(self._test_name)
        # note policyd override only works with Xenial-queens and so keystone
        # is already v3
        # get a keystone session from any keystone unit; we only need one
        # to check to see if it's working.
        user_keystone_session = self._get_keystone_session(
            self.keystone_ips[0])

        # verify that the operation works before performing the policyd
        # override.
        try:
            self.get_client_and_attempt_operation(user_keystone_session)
        except Exception as e:
            raise zaza_exceptions.PolicydError(
                'Retrieve service action as demo user with domain scoped '
                'token failed and should have passed. "{}"'
                .format(str(e)))

        # now do the policyd override.
        logging.info("Doing policyd override with: {}".format(self._rule))
        self._set_policy_with({'rule.yaml': self._rule})
        zaza_model.block_until_all_units_idle()

        # now make sure the operation fails
        try:
            self.get_client_and_attempt_operation(user_keystone_session)
            raise zaza_exceptions.PolicydError(
                'Retrieve service action as demo user with domain scoped '
                'token passed but should have failed due to the policy '
                'override.')
        except PolicydOperationFailedException:
            pass
        except Exception as e:
            raise zaza_exceptions.PolicydError(
                'Retrieve service action as demo user with domain scoped '
                'token failed: "{}"'
                .format(str(e)))

        # clean out the policy and wait
        self._set_config(False)
        # check that the status no longer has "PO:" on it.
        # we have to do it twice due to async races and that some info lines
        # erase the PO: bit prior to actuall getting back to idle.  The double
        # check verifies that the charms have started, the idle waits until it
        # is finished, and then the final check really makes sure they got
        # switched off.
        zaza_model.block_until_wl_status_info_starts_with(
            self.application_name, "PO:", negate_match=True)
        zaza_model.block_until_all_units_idle()
        zaza_model.block_until_wl_status_info_starts_with(
            self.application_name, "PO:", negate_match=True)

    logging.info('OK')


class KeystonePolicydTest(BasePolicydSpecialization):
    """Test the policyd override using the keystone client."""

    _rule = "{'identity:list_services': '!'}"

    def get_client_and_attempt_operation(self, keystone_session):
        """Override this method to perform the operation.

        This operation should pass normally for the demo_user, and fail when
        the rule has been overriden (see the `rule` class variable.

        :param keystone_session: the keystone session to use to obtain the
            client necessary for the test.
        :type keystone_session: ???
        :raises: PolicydOperationFailedException if operation fails.
        """
        keystone_client = openstack_utils.get_keystone_session_client(
            keystone_session)
        try:
            keystone_client.services.list()
        except keystoneauth1.exceptions.http.Forbidden:
            raise PolicydOperationFailedException()


class OldKeystonePolicydTest(PolicydTest,
                             ch_keystone.BaseKeystoneTest,
                             test_utils.OpenStackBaseTest):
    """Specific test for policyd for keystone charm."""

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running KeystonePolicydTest tests."""
        super(KeystonePolicydTest, cls).setUpClass(application_name)

    def test_disable_service(self):
        """Test that service can be disabled."""
        logging.info("Doing policyd override to disable listing domains")
        self._set_policy_with(
            {'rule.yaml': "{'identity:list_services': '!'}"})

        # verify that the policy.d override does disable the endpoint
        with self.config_change(
                {'preferred-api-version': self.default_api_version,
                 'use-policyd-override': 'False'},
                {'preferred-api-version': '3',
                 'use-policyd-override': 'True'},
                application_name="keystone"):
            zaza_model.block_until_all_units_idle()
            for ip in self.keystone_ips:
                try:
                    logging.info('keystone IP {}'.format(ip))
                    openrc = {
                        'API_VERSION': 3,
                        'OS_USERNAME': ch_keystone.DEMO_ADMIN_USER,
                        'OS_PASSWORD': ch_keystone.DEMO_ADMIN_USER_PASSWORD,
                        'OS_AUTH_URL': 'http://{}:5000/v3'.format(ip),
                        'OS_USER_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
                        'OS_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
                    }
                    if self.tls_rid:
                        openrc['OS_CACERT'] = \
                            openstack_utils.KEYSTONE_LOCAL_CACERT
                        openrc['OS_AUTH_URL'] = (
                            openrc['OS_AUTH_URL'].replace('http', 'https'))
                    logging.info('keystone IP {}'.format(ip))
                    keystone_session = openstack_utils.get_keystone_session(
                        openrc, scope='DOMAIN')
                    keystone_client = (
                        openstack_utils.get_keystone_session_client(
                            keystone_session))
                    keystone_client.services.list()
                    raise zaza_exceptions.PolicydError(
                        'Retrieve service list as admin with project scoped '
                        'token passed and should have failed. IP = {}'
                        .format(ip))
                except keystoneauth1.exceptions.http.Forbidden:
                    logging.info("keystone IP:{} policyd override disabled "
                                 "services listing by demo user"
                                 .format(ip))

        # now verify (with the config off) that we can actually access
        # these points
        with self.config_change(
                {'preferred-api-version': self.default_api_version},
                {'preferred-api-version': '3'},
                application_name="keystone"):
            zaza_model.block_until_all_units_idle()
            for ip in self.keystone_ips:
                try:
                    logging.info('keystone IP {}'.format(ip))
                    openrc = {
                        'API_VERSION': 3,
                        'OS_USERNAME': ch_keystone.DEMO_ADMIN_USER,
                        'OS_PASSWORD': ch_keystone.DEMO_ADMIN_USER_PASSWORD,
                        'OS_AUTH_URL': 'http://{}:5000/v3'.format(ip),
                        'OS_USER_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
                        'OS_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
                    }
                    if self.tls_rid:
                        openrc['OS_CACERT'] = \
                            openstack_utils.KEYSTONE_LOCAL_CACERT
                        openrc['OS_AUTH_URL'] = (
                            openrc['OS_AUTH_URL'].replace('http', 'https'))
                    logging.info('keystone IP {}'.format(ip))
                    keystone_session = openstack_utils.get_keystone_session(
                        openrc, scope='DOMAIN')
                    keystone_client = (
                        openstack_utils.get_keystone_session_client(
                            keystone_session))
                    keystone_client.services.list()
                    logging.info("keystone IP:{} without policyd override "
                                 "services list working"
                                 .format(ip))
                except keystoneauth1.exceptions.http.Forbidden:
                    raise zaza_exceptions.PolicydError(
                        'Retrieve services list as demo user with project '
                        'scoped token passed and should have passed. IP = {}'
                        .format(ip))

        logging.info('OK')


# class NeutronAPITest(PolicydTest,
                     # test_utils.OpenStackBaseTest):
    # """Specific test for policyd for neutron-api charm."""

    # def test_disable_service(self):
        # """Test that service can be disabled."""
        # logging.info("Doing policyd override to disable listing domains")
        # self._set_policy_with(
            # {'rule.yaml': "{'identity:list_services': '!'}"})
        # # Get authenticated clients
        # keystone_client = openstack_utils.get_keystone_session_client(
            # keystone_session)
        # neutron_client = openstack_utils.get_neutron_session_client(
            # keystone_session)


