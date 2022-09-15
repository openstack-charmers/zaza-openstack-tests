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

"""Keystone SAML Mellon Testing."""

import logging
from lxml import etree
import requests

import zaza.model
from zaza.openstack.charm_tests.keystone import BaseKeystoneTest
import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.openstack.utilities.openstack as openstack_utils


class FailedToReachIDP(Exception):
    """Custom Exception for failing to reach the IDP."""

    pass


# This testing class is deprecated. It will be removed once we fully drop the
# `samltest.id` dependency.
class CharmKeystoneSAMLMellonTest(BaseKeystoneTest):
    """Charm Keystone SAML Mellon tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone SAML Mellon charm tests."""
        super(CharmKeystoneSAMLMellonTest, cls).setUpClass()
        # Note: The BaseKeystoneTest class sets the application_name to
        # "keystone" which breaks keystone-saml-mellon actions. Explicitly set
        # application name here.
        cls.test_config = lifecycle_utils.get_charm_config()
        cls.application_name = cls.test_config['charm_name']
        cls.action = "get-sp-metadata"
        cls.current_release = openstack_utils.get_os_release()
        cls.FOCAL_USSURI = openstack_utils.get_os_release("focal_ussuri")

    def test_run_get_sp_metadata_action(self):
        """Validate the get-sp-metadata action."""
        unit = zaza.model.get_units(self.application_name)[0]
        if self.vip:
            ip = self.vip
        else:
            ip = zaza.model.get_unit_public_address(unit)

        action = zaza.model.run_action(unit.entity_id, self.action)
        if "failed" in action.data["status"]:
            raise Exception(
                "The action failed: {}".format(action.data["message"]))

        output = action.data["results"]["output"]
        root = etree.fromstring(output)
        for item in root.items():
            if "entityID" in item[0]:
                assert ip in item[1]

        for appt in root.getchildren():
            for elem in appt.getchildren():
                for item in elem.items():
                    if "Location" in item[0]:
                        assert ip in item[1]

        logging.info("Successul get-sp-metadata action")

    def test_saml_mellon_redirects(self):
        """Validate the horizon -> keystone -> IDP redirects."""
        if self.vip:
            keystone_ip = self.vip
        else:
            unit = zaza.model.get_units(self.application_name)[0]
            keystone_ip = zaza.model.get_unit_public_address(unit)

        horizon = "openstack-dashboard"
        horizon_vip = (zaza.model.get_application_config(horizon)
                       .get("vip").get("value"))
        if horizon_vip:
            horizon_ip = horizon_vip
        else:
            unit = zaza.model.get_units("openstack-dashboard")[0]
            horizon_ip = zaza.model.get_unit_public_address(unit)

        if self.tls_rid:
            proto = "https"
        else:
            proto = "http"

        # Use Keystone URL for < Focal
        if self.current_release < self.FOCAL_USSURI:
            region = "{}://{}:5000/v3".format(proto, keystone_ip)
        else:
            region = "default"

        url = "{}://{}/horizon/auth/login/".format(proto, horizon_ip)
        horizon_expect = ('<option value="samltest_mapped">'
                          'samltest.id</option>')

        # This is the message samltest.id gives when it has not had
        # SP XML uploaded. It still shows we have been directed to:
        # horizon -> keystone -> samltest.id
        idp_expect = ("The application you have accessed is not registered "
                      "for use with this service.")

        def _do_redirect_check(url, region, idp_expect, horizon_expect):

            # start session, get csrftoken
            client = requests.session()
            # Verify=False see note below
            login_page = client.get(url, verify=False)

            # Validate SAML method is available
            assert horizon_expect in login_page.text

            # Get cookie
            if "csrftoken" in client.cookies:
                csrftoken = client.cookies["csrftoken"]
            else:
                raise Exception("Missing csrftoken")

            # Build and send post request
            form_data = {
                "auth_type": "samltest_mapped",
                "csrfmiddlewaretoken": csrftoken,
                "next": "/horizon/project/api_access",
                "region": region,
            }

            # Verify=False due to CA certificate bundles.
            # If we point to the CA for keystone/horizon they work but
            # samltest.id does not.
            # If we don't set it validation fails for keystone/horizon
            # We would have to install the keystone CA onto the system
            # to validate end to end.
            response = client.post(
                url, data=form_data,
                headers={"Referer": url},
                allow_redirects=True,
                verify=False)

            if idp_expect not in response.text:
                msg = "FAILURE code={} text={}".format(response, response.text)
                # Raise a custom exception.
                raise FailedToReachIDP(msg)

        # Execute the check
        # We may need to try/except to allow horizon to build its pages
        _do_redirect_check(url, region, idp_expect, horizon_expect)
        logging.info("SUCCESS")


class BaseCharmKeystoneSAMLMellonTest(BaseKeystoneTest):
    """Charm Keystone SAML Mellon tests."""

    @classmethod
    def setUpClass(cls,
                   application_name="keystone-saml-mellon",
                   test_saml_idp_app_name="test-saml-idp",
                   horizon_idp_option_name="myidp_mapped",
                   horizon_idp_display_name="myidp via mapped"):
        """Run class setup for running Keystone SAML Mellon charm tests."""
        super(BaseCharmKeystoneSAMLMellonTest, cls).setUpClass()
        # Note: The BaseKeystoneTest class sets the application_name to
        # "keystone" which breaks keystone-saml-mellon actions. Explicitly set
        # application name here.
        cls.application_name = application_name
        cls.test_saml_idp_app_name = test_saml_idp_app_name
        cls.horizon_idp_option_name = horizon_idp_option_name
        cls.horizon_idp_display_name = horizon_idp_display_name
        cls.action = "get-sp-metadata"
        cls.current_release = openstack_utils.get_os_release()
        cls.FOCAL_USSURI = openstack_utils.get_os_release("focal_ussuri")
        keystone_config = zaza.model.get_application_config('keystone')
        cls.keystone_ip = keystone_config.get("vip").get("value")
        if not cls.keystone_ip:
            keystone_unit = zaza.model.get_units('keystone')[0]
            cls.keystone_ip = zaza.model.get_unit_public_address(keystone_unit)

    @staticmethod
    def check_horizon_redirect(horizon_url, horizon_expect,
                               horizon_idp_option_name, horizon_region,
                               idp_url, idp_expect):
        """Validate the Horizon -> Keystone -> IDP redirects.

        This validation is done through `requests.session()`, and the proper
        get / post http calls.

        :param horizon_url: The login page for the Horizon OpenStack dashboard.
        :type horizon_url: string
        :param horizon_expect: Information that needs to be displayed by
                               Horizon login page, when there is a proper
                               SAML IdP configuration.
        :type horizon_expect: string
        :param horizon_idp_option_name: The name of the IdP that is chosen
                                        in the Horizon dropdown from the login
                                        screen. This will go in the post body
                                        as 'auth_type'.
        :type horizon_idp_option_name: string
        :param horizon_region: Information needed to complete the http post
                               data for the Horizon login.
        :type horizon_region: string
        :param idp_url: The url for the IdP where the user needs to be
                        redirected.
        :type idp_url: string
        :param idp_expect: Information that needs to be displayed by the IdP
                           after the user is redirected there.
        :type idp_expect: string
        :returns: None
        """
        # start session, get csrftoken
        client = requests.session()
        # Verify=False see note below
        login_page = client.get(horizon_url, verify=False)

        # Validate SAML method is available
        assert horizon_expect in login_page.text

        # Get cookie
        if "csrftoken" in client.cookies:
            csrftoken = client.cookies["csrftoken"]
        else:
            raise Exception("Missing csrftoken")

        # Build and send post request
        form_data = {
            "auth_type": horizon_idp_option_name,
            "csrfmiddlewaretoken": csrftoken,
            "next": "/horizon/project/api_access",
            "region": horizon_region,
        }

        # Verify=False due to CA certificate bundles.
        # If we don't set it validation fails for keystone/horizon
        # We would have to install the keystone CA onto the system
        # to validate end to end.
        response = client.post(
            horizon_url,
            data=form_data,
            headers={"Referer": horizon_url},
            allow_redirects=True,
            verify=False)

        if idp_expect not in response.text:
            msg = "FAILURE code={} text={}".format(response, response.text)
            # Raise a custom exception.
            raise FailedToReachIDP(msg)

        # Validate that we were redirected to the proper IdP
        assert response.url.startswith(idp_url)
        assert idp_url in response.text

    def test_run_get_sp_metadata_action(self):
        """Validate the get-sp-metadata action."""
        unit = zaza.model.get_units(self.application_name)[0]
        action = zaza.model.run_action(unit.entity_id, self.action)
        self.assertNotIn(
            "failed",
            action.data["status"],
            msg="The action failed: {}".format(action.data["message"]))

        output = action.data["results"]["output"]
        root = etree.fromstring(output)
        for item in root.items():
            if "entityID" in item[0]:
                self.assertIn(self.keystone_ip, item[1])

        for appt in root.getchildren():
            for elem in appt.getchildren():
                for item in elem.items():
                    if "Location" in item[0]:
                        self.assertIn(self.keystone_ip, item[1])

        logging.info("Successul get-sp-metadata action")

    def test_saml_mellon_redirects(self):
        """Validate the horizon -> keystone -> IDP redirects."""
        horizon = "openstack-dashboard"
        horizon_config = zaza.model.get_application_config(horizon)
        horizon_vip = horizon_config.get("vip").get("value")
        unit = zaza.model.get_units("openstack-dashboard")[0]

        horizon_ip = horizon_vip if horizon_vip else (
            zaza.model.get_unit_public_address(unit))
        proto = "https" if self.tls_rid else "http"

        # Use Keystone URL for < Focal
        if self.current_release < self.FOCAL_USSURI:
            region = "{}://{}:5000/v3".format(proto, self.keystone_ip)
        else:
            region = "default"

        idp_address = zaza.model.get_unit_public_address(
            zaza.model.get_units(self.test_saml_idp_app_name)[0])

        horizon_url = "{}://{}/horizon/auth/login/".format(proto, horizon_ip)
        horizon_expect = '<option value="{0}">{1}</option>'.format(
            self.horizon_idp_option_name, self.horizon_idp_display_name)
        idp_url = ("http://{0}/simplesaml/"
                   "module.php/core/loginuserpass.php").format(idp_address)
        # This is the message the local test-saml-idp displays after you are
        # redirected. It shows we have been directed to:
        # horizon -> keystone -> test-saml-idp
        idp_expect = (
            "A service has requested you to authenticate yourself. Please "
            "enter your username and password in the form below.")

        # Execute the check
        BaseCharmKeystoneSAMLMellonTest.check_horizon_redirect(
            horizon_url=horizon_url,
            horizon_expect=horizon_expect,
            horizon_idp_option_name=self.horizon_idp_option_name,
            horizon_region=region,
            idp_url=idp_url,
            idp_expect=idp_expect)
        logging.info("SUCCESS")


class CharmKeystoneSAMLMellonIDP1Test(BaseCharmKeystoneSAMLMellonTest):
    """Charm Keystone SAML Mellon tests class for the local IDP #1."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone SAML Mellon charm tests.

        It does the necessary setup for the local IDP #1.
        """
        super(CharmKeystoneSAMLMellonIDP1Test, cls).setUpClass(
            application_name="keystone-saml-mellon1",
            test_saml_idp_app_name="test-saml-idp1",
            horizon_idp_option_name="test-saml-idp1_mapped",
            horizon_idp_display_name="Test SAML IDP #1")


class CharmKeystoneSAMLMellonIDP2Test(BaseCharmKeystoneSAMLMellonTest):
    """Charm Keystone SAML Mellon tests class for the local IDP #2."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone SAML Mellon charm tests.

        It does the necessary setup for the local IDP #2.
        """
        super(CharmKeystoneSAMLMellonIDP2Test, cls).setUpClass(
            application_name="keystone-saml-mellon2",
            test_saml_idp_app_name="test-saml-idp2",
            horizon_idp_option_name="test-saml-idp2_mapped",
            horizon_idp_display_name="Test SAML IDP #2")
