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

If a charm doesn't require a specific test, then the GenericPolicydTest class
can be used that just includes the two generic tests.  The config in the
tests.yaml would stil be required.  See the PolicydTest class docstring for
further details.
"""

import logging
import os
import shutil
import tempfile
import tenacity
import unittest
import zipfile

from octaviaclient.api.v2 import octavia as octaviaclient
import cinderclient.exceptions
import heatclient.exc
import glanceclient.common.exceptions
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

    good = {
        "file1.yaml": "{'rule1': '!'}"
    }
    bad = {
        "file2.yaml": "{'rule': '!}"
    }
    path_infix = ""

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running Policyd charm operation tests."""
        super(PolicydTest, cls).setUpClass(application_name)
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
        zaza_model.wait_for_agent_status()

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

    def _set_policy_with(self, rules, filename='rules.zip'):
        rules_zip_path = self._make_zip_file_from(filename, rules)
        zaza_model.attach_resource(self.application_name,
                                   'policyd-override',
                                   rules_zip_path)
        self._set_config(True)
        zaza_model.block_until_wl_status_info_starts_with(
            self.application_name, "PO:", negate_match=False)

    def test_001_policyd_good_yaml(self):
        """Test that the policyd with a good zipped yaml file."""
        good = self.good
        good_zip_path = self._make_zip_file_from('good.zip', good)
        logging.info("Attaching good zip file as a resource.")
        zaza_model.attach_resource(self.application_name,
                                   'policyd-override',
                                   good_zip_path)
        zaza_model.block_until_all_units_idle()
        logging.debug("Now setting config to true")
        self._set_config(True)
        # check that the file gets to the right location
        if self.path_infix:
            path = os.path.join(
                "/etc", self._service_name, "policy.d", self.path_infix,
                'file1.yaml')
        else:
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

    def test_002_policyd_bad_yaml(self):
        """Test bad yaml file in the zip file is handled."""
        bad = self.bad
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
        if self.path_infix:
            path = os.path.join(
                "/etc", self._service_name, "policy.d", self.path_infix,
                'file2.yaml')
        else:
            path = os.path.join(
                "/etc", self._service_name, "policy.d", 'file2.yaml')
        logging.info("Now checking that file {} is not present.".format(path))
        zaza_model.block_until_file_missing(self.application_name, path)
        self._set_config(False)
        zaza_model.block_until_all_units_idle()
        logging.info("OK")


class GenericPolicydTest(PolicydTest, test_utils.OpenStackBaseTest):
    """Generic policyd test for any charm without a specific test."""

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running KeystonePolicydTest tests."""
        super(GenericPolicydTest, cls).setUpClass(application_name)
        if (openstack_utils.get_os_release()
                < openstack_utils.get_os_release('xenial_queens')):
            raise unittest.SkipTest(
                "zaza.openstack.charm_tests.policyd.tests.GenericPolicydTest "
                "not valid before xenial_queens")


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
    """Base test for specialising Policyd override tests.

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

    To use this class, follow the keystone example:

        class KeystonePolicydTest(BasePolicydSpecialization):

            _rule = {'rule.yaml': "{'identity:list_services': '!'}"}

            def get_client_and_attempt_operation(self, keystone_session):
                ... etc.
    """

    # this needs to be defined as the rule that gets placed into a yaml policy
    # override.  It is a string of the form: 'some-rule: "!"'
    # i.e. disable some policy and then try and test it.
    _rule = None

    # Optional: the name to log at the beginning of the test
    _test_name = None

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running KeystonePolicydTest tests."""
        super(BasePolicydSpecialization, cls).setUpClass(application_name)
        if (openstack_utils.get_os_release()
                < openstack_utils.get_os_release('xenial_queens')):
            raise unittest.SkipTest(
                "zaza.openstack.charm_tests.policyd.tests.* "
                "not valid before xenial_queens")
        if cls._rule is None:
            raise unittest.SkipTest(
                "zaza.openstack.charm_tests.policyd.tests.* "
                "not valid if {}.rule is not configured"
                .format(cls.__name__))

    def setup_for_attempt_operation(self, ip):
        """Set-up for the policy override if needed.

        This method allows the test being performed in
        get_client_and_attempt_operation() to have some setup done before the
        test is performed.  This is because the method
        get_client_and_attempt_operation() is run twice; once to succeed and
        once to fail.

        :param ip: the ip of for keystone.
        :type ip: str
        """
        pass

    def cleanup_for_attempt_operation(self, ip):
        """Clean-up after a successful (or not) policy override operation.

        :param ip: the ip of for keystone.
        :type ip: str
        """
        pass

    def get_client_and_attempt_operation(self, keystone_session):
        """Override this method to perform the operation.

        This operation should pass normally for the demo_user, and fail when
        the rule has been overriden (see the `rule` class variable.

        :param keystone_session: the keystone session to use to obtain the
            client necessary for the test.
        :type keystone_session: keystoneauth1.session.Session
        :raises: PolicydOperationFailedException if operation fails.
        """
        raise NotImplementedError("This method must be overridden")

    def _get_keystone_session(self, ip, openrc, scope='DOMAIN'):
        """Return the keystone session for the IP address passed.

        :param ip: the IP address to get the session against.
        :type ip: str
        :param openrc: the params to authenticate with.
        :type openrc: Dict[str, str]
        :param scope: the scope of the token
        :type scope: str
        :returns: a keystone session to the IP address
        :rtype: keystoneauth1.session.Session
        """
        logging.info('Authentication for {} on keystone IP {}'
                     .format(openrc['OS_USERNAME'], ip))
        if self.tls_rid:
            openrc['OS_CACERT'] = \
                openstack_utils.KEYSTONE_LOCAL_CACERT
            openrc['OS_AUTH_URL'] = (
                openrc['OS_AUTH_URL'].replace('http', 'https'))
        logging.info('keystone IP {}'.format(ip))
        keystone_session = openstack_utils.get_keystone_session(
            openrc, scope=scope)
        return keystone_session

    def get_keystone_session_demo_user(self, ip, scope='PROJECT'):
        """Return the keystone session for demo user.

        :param ip: the IP address to get the session against.
        :type ip: str
        :param scope: the scope of the token
        :type scope: str
        :returns: a keystone session to the IP address
        :rtype: keystoneauth1.session.Session
        """
        return self._get_keystone_session(ip, {
            'API_VERSION': 3,
            'OS_USERNAME': ch_keystone.DEMO_USER,
            'OS_PASSWORD': ch_keystone.DEMO_PASSWORD,
            'OS_AUTH_URL': 'http://{}:5000/v3'.format(ip),
            'OS_USER_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
            'OS_PROJECT_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
            'OS_PROJECT_NAME': ch_keystone.DEMO_PROJECT,
            'OS_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
        }, scope)

    def get_keystone_session_demo_admin_user(self, ip, scope='PROJECT'):
        """Return the keystone session demo_admin user.

        :param ip: the IP address to get the session against.
        :type ip: str
        :param scope: the scope of the token
        :type scope: str
        :returns: a keystone session to the IP address
        :rtype: keystoneauth1.session.Session
        """
        return self._get_keystone_session(ip, {
            'API_VERSION': 3,
            'OS_USERNAME': ch_keystone.DEMO_ADMIN_USER,
            'OS_PASSWORD': ch_keystone.DEMO_ADMIN_USER_PASSWORD,
            'OS_AUTH_URL': 'http://{}:5000/v3'.format(ip),
            'OS_USER_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
            'OS_PROJECT_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
            'OS_PROJECT_NAME': ch_keystone.DEMO_PROJECT,
            'OS_DOMAIN_NAME': ch_keystone.DEMO_DOMAIN,
        }, scope)

    def get_keystone_session_admin_user(self, ip):
        """Return the keystone session admin user.

        :param ip: the IP address to get the session against.
        :type ip: str
        :returns: a keystone session to the IP address
        :rtype: keystoneauth1.session.Session
        """
        return openstack_utils.get_keystone_session(
            openstack_utils.get_overcloud_auth(address=ip))

    def test_003_test_overide_is_observed(self):
        """Test that the override is observed by the underlying service."""
        if self._test_name is None:
            logging.info("Doing policyd override for {}"
                         .format(self._service_name))
        else:
            logging.info(self._test_name)
        # note policyd override only works with Xenial-queens and so keystone
        # is already v3

        # Allow the overriden class to setup the environment before the policyd
        # test is performed.
        self.setup_for_attempt_operation(self.keystone_ips[0])

        # verify that the operation works before performing the policyd
        # override.
        zaza_model.block_until_wl_status_info_starts_with(
            self.application_name, "PO:", negate_match=True)
        zaza_model.block_until_all_units_idle()
        logging.info("First verify that operation works prior to override")
        try:
            self.get_client_and_attempt_operation(self.keystone_ips[0])
        except Exception as e:
            self.cleanup_for_attempt_operation(self.keystone_ips[0])
            raise zaza_exceptions.PolicydError(
                'Service action failed and should have passed. "{}"'
                .format(str(e)))

        # now do the policyd override.
        logging.info("Doing policyd override with: {}".format(self._rule))
        self._set_policy_with(self._rule)
        zaza_model.block_until_all_units_idle()

        # now make sure the operation fails
        logging.info("Now verify that operation doesn't work with override")
        try:
            self.get_client_and_attempt_operation(self.keystone_ips[0])
            raise zaza_exceptions.PolicydError(
                "Service action passed and should have failed.")
        except PolicydOperationFailedException:
            pass
        except zaza_exceptions.PolicydError as e:
            logging.info("{}".format(str(e)))
            raise
        except Exception as e:
            logging.info("exception was: {}".format(e.__class__.__name__))
            import traceback
            logging.info(traceback.format_exc())
            self.cleanup_for_attempt_operation(self.keystone_ips[0])
            raise zaza_exceptions.PolicydError(
                'Service action failed in an unexpected way: {}'
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

        # Finally make sure it works again!
        logging.info("Finally verify that operation works after removing the "
                     "override.")
        try:
            self.get_client_and_attempt_operation(self.keystone_ips[0])
        except Exception as e:
            raise zaza_exceptions.PolicydError(
                'Service action failed and should have passed after removing '
                'policy override: "{}"'
                .format(str(e)))
        finally:
            self.cleanup_for_attempt_operation(self.keystone_ips[0])

    logging.info('OK')


class KeystoneTests(BasePolicydSpecialization):
    """Test the policyd override using the keystone client."""

    _rule = {'rule.yaml': "{'identity:list_services': '!'}"}

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running NeutronApiTest charm operation tests."""
        super(KeystoneTests, cls).setUpClass(
            application_name="keystone")

    def get_client_and_attempt_operation(self, ip):
        """Attempt to list services.  If it fails, raise an exception.

        This operation should pass normally for the demo_user, and fail when
        the rule has been overriden (see the `rule` class variable.

        :param ip: the IP address to get the session against.
        :type ip: str
        :raises: PolicydOperationFailedException if operation fails.
        """
        keystone_client = openstack_utils.get_keystone_session_client(
            self.get_keystone_session_demo_admin_user(ip))
        try:
            keystone_client.services.list()
        except keystoneauth1.exceptions.http.Forbidden:
            raise PolicydOperationFailedException()


class NeutronApiTests(BasePolicydSpecialization):
    """Test the policyd override using the neutron client."""

    _rule = {'rule.yaml': "{'get_network': '!'}"}

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running NeutronApiTest charm operation tests."""
        super(NeutronApiTests, cls).setUpClass(application_name="neutron-api")
        cls.application_name = "neutron-api"

    # NOTE(fnordahl): There is a race between `neutron-api` signalling unit is
    # ready and the service actually being ready to serve requests.  The test
    # will fail intermittently unless we gracefully accept this.
    # Issue: openstack-charmers/zaza-openstack-tests#138
    @tenacity.retry(wait=tenacity.wait_fixed(1),
                    reraise=True, stop=tenacity.stop_after_delay(8))
    def get_client_and_attempt_operation(self, ip):
        """Attempt to list the networks as a policyd override.

        This operation should pass normally for the demo_user, and fail when
        the rule has been overriden (see the `rule` class variable.

        :param ip: the IP address to get the session against.
        :type ip: str
        :raises: PolicydOperationFailedException if operation fails.
        """
        neutron_client = openstack_utils.get_neutron_session_client(
            self.get_keystone_session_demo_user(ip))
        try:
            # If we are allowed to list networks, this will return something.
            # if the policyd override is present, then no error is generated,
            # but no networks are returned.
            networks = neutron_client.list_networks()
            logging.debug("networks: {}".format(networks))
            if len(networks['networks']) == 0:
                raise PolicydOperationFailedException()
        except Exception:
            raise PolicydOperationFailedException()


class GlanceTests(BasePolicydSpecialization):
    """Test the policyd override using the glance client."""

    _rule = {'rule.yaml': "{'get_images': '!'}"}

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running GlanceTests charm operation tests."""
        super(GlanceTests, cls).setUpClass(application_name="glance")
        cls.application_name = "glance"

    def get_client_and_attempt_operation(self, ip):
        """Attempt to list the images as a policyd override.

        This operation should pass normally for the demo_user, and fail when
        the rule has been overriden (see the `rule` class variable.

        :param ip: the IP address to get the session against.
        :type ip: str
        :raises: PolicydOperationFailedException if operation fails.
        """
        glance_client = openstack_utils.get_glance_session_client(
            self.get_keystone_session_demo_user(ip))
        try:
            # NOTE(ajkavanagh) - it turns out that the list() is very important
            # as it forces the generator to iterate which only then checkes if
            # the api call is authorized.  Just getting the generator (from
            # .list()) doesn't perform the API call.
            images = list(glance_client.images.list())
            logging.debug("images is: {}".format(images))
        except glanceclient.common.exceptions.HTTPForbidden:
            raise PolicydOperationFailedException()


class CinderTests(BasePolicydSpecialization):
    """Test the policyd override using the cinder client."""

    _rule = {'rule.yaml': "{'volume:get_all': '!'}"}

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running CinderTests charm operation tests."""
        super(CinderTests, cls).setUpClass(application_name="cinder")
        cls.application_name = "cinder"

    def get_client_and_attempt_operation(self, ip):
        """Attempt to list the images as a policyd override.

        This operation should pass normally for the demo_user, and fail when
        the rule has been overriden (see the `rule` class variable.

        :param ip: the IP address to get the session against.
        :type ip: str
        :raises: PolicydOperationFailedException if operation fails.
        """
        cinder_client = openstack_utils.get_cinder_session_client(
            self.get_keystone_session_admin_user(ip))
        try:
            cinder_client.volumes.list()
        except cinderclient.exceptions.Forbidden:
            raise PolicydOperationFailedException()


class HeatTests(BasePolicydSpecialization):
    """Test the policyd override using the heat client."""

    _rule = {'rule.yaml': "{'stacks:index': '!'}"}

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running HeatTests charm operation tests."""
        super(HeatTests, cls).setUpClass(application_name="heat")
        cls.application_name = "heat"

    def get_client_and_attempt_operation(self, ip):
        """Attempt to list the heat stacks as a policyd override.

        This operation should pass normally, and fail when
        the rule has been overriden (see the `rule` class variable).

        :param ip: the IP address to get the session against.
        :type ip: str
        :raises: PolicydOperationFailedException if operation fails.
        """
        heat_client = openstack_utils.get_heat_session_client(
            self.get_keystone_session_admin_user(ip))
        try:
            # stacks.list() returns a generator (as opposed to a list), so to
            # force the client to actually connect, the generator has to be
            # iterated.
            list(heat_client.stacks.list())
        except heatclient.exc.HTTPForbidden:
            raise PolicydOperationFailedException()


class OctaviaTests(BasePolicydSpecialization):
    """Test the policyd override using the octavia client."""

    _rule = {'rule.yaml': "{'os_load-balancer_api:loadbalancer:get_one': '!'}"}

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running OctaviaTests charm operation tests."""
        super(OctaviaTests, cls).setUpClass(application_name="octavia")
        cls.application_name = "octavia"

    def setup_for_attempt_operation(self, ip):
        """Create a loadbalancer.

        This is necessary so that the attempt is to show the load-balancer and
        this is an operator that the policy can stop.  Unfortunately, octavia,
        whilst it has a policy for just listing load-balancers, unfortunately,
        it doesn't work; whereas showing the load-balancer can be stopped.

        NB this only works if the setup phase of the octavia tests have been
        completed.

        :param ip: the ip of for keystone.
        :type ip: str
        """
        logging.info("Setting up loadbalancer.")
        auth = openstack_utils.get_overcloud_auth(address=ip)
        sess = openstack_utils.get_keystone_session(auth)

        octavia_client = openstack_utils.get_octavia_session_client(sess)
        neutron_client = openstack_utils.get_neutron_session_client(sess)

        if openstack_utils.dvr_enabled():
            network_name = 'private_lb_fip_network'
        else:
            network_name = 'private'
        resp = neutron_client.list_networks(name=network_name)

        vip_subnet_id = resp['networks'][0]['subnets'][0]

        res = octavia_client.load_balancer_create(
            json={
                'loadbalancer': {
                    'description': 'Created by Zaza',
                    'admin_state_up': True,
                    'vip_subnet_id': vip_subnet_id,
                    'name': 'zaza-lb-0',
                }})
        self.lb_id = res['loadbalancer']['id']
        # now wait for it to get to the active state

        @tenacity.retry(wait=tenacity.wait_fixed(1),
                        reraise=True, stop=tenacity.stop_after_delay(900))
        def wait_for_lb_resource(client, resource_id):
            resp = client.load_balancer_show(resource_id)
            logging.info(resp['provisioning_status'])
            assert resp['provisioning_status'] == 'ACTIVE', (
                'load balancer resource has not reached '
                'expected provisioning status: {}'
                .format(resp))
            return resp

        logging.info('Awaiting loadbalancer to reach provisioning_status '
                     '"ACTIVE"')
        resp = wait_for_lb_resource(octavia_client, self.lb_id)
        logging.info(resp)
        logging.info("Setup loadbalancer complete.")

    def cleanup_for_attempt_operation(self, ip):
        """Remove the loadbalancer.

        :param ip: the ip of for keystone.
        :type ip: str
        """
        logging.info("Deleting loadbalancer {}.".format(self.lb_id))
        auth = openstack_utils.get_overcloud_auth(address=ip)
        sess = openstack_utils.get_keystone_session(auth)

        octavia_client = openstack_utils.get_octavia_session_client(sess)
        octavia_client.load_balancer_delete(self.lb_id)
        logging.info("Deleting loadbalancer in progress ...")

        @tenacity.retry(wait=tenacity.wait_fixed(1),
                        reraise=True, stop=tenacity.stop_after_delay(900))
        def wait_til_deleted(client, lb_id):
            lb_list = client.load_balancer_list()
            ids = [lb['id'] for lb in lb_list['loadbalancers']]
            assert lb_id not in ids, 'load balancer still deleting'

        wait_til_deleted(octavia_client, self.lb_id)
        logging.info("Deleted loadbalancer.")

    def get_client_and_attempt_operation(self, ip):
        """Attempt to show the loadbalancer as a policyd override.

        This operation should pass normally, and fail when
        the rule has been overriden (see the `rule` class variable.

        :param ip: the IP address to get the session against.
        :type ip: str
        :raises: PolicydOperationFailedException if operation fails.
        """
        octavia_client = openstack_utils.get_octavia_session_client(
            self.get_keystone_session_admin_user(ip))
        try:
            octavia_client.load_balancer_show(self.lb_id)
        except octaviaclient.OctaviaClientException:
            raise PolicydOperationFailedException()
