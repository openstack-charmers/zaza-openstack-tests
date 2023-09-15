# Copyright 2021 Canonical Ltd.
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

"""Encapsulating `ceph-dashboard` testing."""

import json
import uuid
import logging
import collections
from base64 import b64encode
import requests
import tenacity
import trustme

import zaza
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


X509_CERT = '''
MIICZDCCAg6gAwIBAgICBr8wDQYJKoZIhvcNAQEEBQAwgZIxCzAJBgNVBAYTAlVTMRMwEQYDVQQI
EwpDYWxpZm9ybmlhMRQwEgYDVQQHEwtTYW50YSBDbGFyYTEeMBwGA1UEChMVU3VuIE1pY3Jvc3lz
dGVtcyBJbmMuMRowGAYDVQQLExFJZGVudGl0eSBTZXJ2aWNlczEcMBoGA1UEAxMTQ2VydGlmaWNh
dGUgTWFuYWdlcjAeFw0wNzAzMDcyMTUwMDVaFw0xMDEyMDEyMTUwMDVaMDsxFDASBgNVBAoTC2V4
YW1wbGUuY29tMSMwIQYDVQQDExpMb2FkQmFsYW5jZXItMy5leGFtcGxlLmNvbTCBnzANBgkqhkiG
9w0BAQEFAAOBjQAwgYkCgYEAlOhN9HddLMpE3kCjkPSOFpCkDxTNuhMhcgBkYmSEF/iJcQsLX/ga
pO+W1SIpwqfsjzR5ZvEdtc/8hGumRHqcX3r6XrU0dESM6MW5AbNNJsBnwIV6xZ5QozB4wL4zREhw
zwwYejDVQ/x+8NRESI3ym17tDLEuAKyQBueubgjfic0CAwEAAaNgMF4wEQYJYIZIAYb4QgEBBAQD
AgZAMA4GA1UdDwEB/wQEAwIE8DAfBgNVHSMEGDAWgBQ7oCE35Uwn7FsjS01w5e3DA1CrrjAYBgNV
HREEETAPgQ1tYWxsYUBzdW4uY29tMA0GCSqGSIb3DQEBBAUAA0EAGhJhep7X2hqWJWQoXFcdU7eQ
'''

X509_DATA = '''
EwpDYWxpZm9ybmlhMRQwEgYDVQQHEwtTYW50YSBDbGFyYTEeMBwGA1UEChMVU3VuIE1pY3Jvc3lz
dGVtcyBJbmMuMRowGAYDVQQLExFJZGVudGl0eSBTZXJ2aWNlczEcMBoGA1UEAxMTQ2VydGlmaWNh
dGUgTWFuYWdlcjAeFw0wNzAzMDcyMjAxMTVaFw0xMDEyMDEyMjAxMTVaMDsxFDASBgNVBAoTC2V4
YW1wbGUuY29tMSMwIQYDVQQDExpMb2FkQmFsYW5jZXItMy5leGFtcGxlLmNvbTCBnzANBgkqhkiG
HREEETAPgQ1tYWxsYUBzdW4uY29tMA0GCSqGSIb3DQEBBAUAA0EAEgbmnOz2Rvpj9bludb9lEeVa
OA46zRiyt4BPlbgIaFyG6P7GWSddMi/14EimQjjDbr4ZfvlEdPJmimHExZY3KQ==
'''

SAML_IDP_METADATA = '''
<EntityDescriptor
  xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
  entityID="ceph-dashboard">
  <IDPSSODescriptor
   WantAuthnRequestsSigned="false"
   protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <KeyDescriptor use="signing">
      <KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">
        <X509Data>
          <X509Certificate>
            {cert}
          </X509Certificate>
        </X509Data>
      </KeyInfo>
    </KeyDescriptor>
    <KeyDescriptor use="encryption">
      <KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">
        <X509Data>
          {data}
        </X509Data>
      </KeyInfo>
    </KeyDescriptor>
    <ArtifactResolutionService index="0" isDefault="1"/>
      <NameIDFormat>
        urn:oasis:names:tc:SAML:2.0:nameid-format:persistent
      </NameIDFormat>
    <NameIDFormat>
      urn:oasis:names:tc:SAML:2.0:nameid-format:transient
    </NameIDFormat>
    <SingleSignOnService
     Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
     Location="{host}"/>
  </IDPSSODescriptor>
</EntityDescriptor>
'''


class CephDashboardTest(test_utils.BaseCharmTest):
    """Class for `ceph-dashboard` tests."""

    REMOTE_CERT_FILE = ('/usr/local/share/ca-certificates/'
                        'vault_ca_cert_dashboard.crt')

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph dashboard tests."""
        super().setUpClass()
        cls.application_name = 'ceph-dashboard'
        cls.local_ca_cert = openstack_utils.get_remote_ca_cert_file(
            cls.application_name)

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1,
                                                   min=5, max=10),
                    retry=tenacity.retry_if_exception_type(
                        requests.exceptions.ConnectionError),
                    reraise=True)
    def _run_request_get(self, url, verify, allow_redirects):
        """Run a GET request against `url` with tenacity retries.

        :param url: url to access
        :type url: str
        :param verify: Path to a CA_BUNDLE file or directory with certificates
                       of trusted CAs or False to ignore verifying the SSL
                       certificate.
        :type verify: Union[str, bool]
        :param allow_redirects: Set to True if redirect following is allowed.
        :type allow_redirects: bool
        :returns: Request response
        :rtype: requests.models.Response
        """
        return requests.get(
            url,
            verify=verify,
            allow_redirects=allow_redirects,
            timeout=120)

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1,
                                                   min=5, max=10),
                    retry=tenacity.retry_if_exception_type(
                        requests.exceptions.ConnectionError),
                    reraise=True)
    def _run_request_post(self, url, verify, data, headers):
        """Run a POST request against `url` with tenacity retries.

        :param url: url to access
        :type url: str
        :param verify: Path to a CA_BUNDLE file or directory with certificates
                       of trusted CAs or False to ignore verifying the SSL
                       certificate.
        :type verify: Union[str, bool]
        :param data: Data to post to url
        :type data: str
        :param headers: Headers to set when posting
        :type headers: dict
        :returns: Request response
        :rtype: requests.models.Response
        """
        return requests.post(
            url,
            data=data,
            headers=headers,
            verify=verify,
            timeout=120)

    @tenacity.retry(wait=tenacity.wait_fixed(2), reraise=True,
                    stop=tenacity.stop_after_attempt(90))
    def get_master_dashboard_url(self):
        """Get the url of the dashboard servicing requests.

        Only one unit serves requests at any one time, the other units
        redirect to that unit.

        :returns: URL of dashboard on unit
        :rtype: Union[str, None]
        """
        output = zaza.model.run_on_leader(
            'ceph-mon',
            'ceph mgr services')['Stdout']
        url = json.loads(output).get('dashboard')
        if url is None:
            raise tenacity.RetryError(None)
        return url.strip('/')

    def test_001_dashboard_units(self):
        """Check dashboard units are configured correctly."""
        self.verify_ssl_config(self.local_ca_cert)

    def create_user(self, username, role='administrator'):
        """Create a dashboard user.

        :param username: Username to create.
        :type username: str
        :param role: Role to grant to user.
        :type role: str
        :returns: Results from action.
        :rtype: juju.action.Action
        """
        action = zaza.model.run_action_on_leader(
            'ceph-dashboard',
            'add-user',
            action_params={
                'username': username,
                'role': role})
        return action

    def get_random_username(self):
        """Generate a username to use in tests.

        :returns: Username
        :rtype: str
        """
        return "zazauser-{}".format(uuid.uuid1())

    def test_002_create_user(self):
        """Test create user action."""
        test_user = self.get_random_username()
        action = self.create_user(test_user)
        self.assertEqual(action.status, "completed")
        self.assertTrue(action.data['results']['password'])
        action = self.create_user(test_user)
        # Action should fail as the user already exists
        self.assertEqual(action.status, "failed")

    def access_dashboard(self, dashboard_url):
        """Test logging via a dashboard url.

        :param dashboard_url: Base url to use to login to
        :type dashboard_url: str
        """
        user = self.get_random_username()
        action = self.create_user(username=user)
        self.assertEqual(action.status, "completed")
        password = action.data['results']['password']
        path = "api/auth"
        headers = {
            'Content-type': 'application/json',
            'Accept': 'application/vnd.ceph.api.v1.0+json'}
        payload = {"username": user, "password": password}
        verify = self.local_ca_cert
        r = self._run_request_post(
            "{}/{}".format(dashboard_url, path),
            verify=verify,
            data=json.dumps(payload),
            headers=headers)
        self.assertEqual(r.status_code, requests.codes.created)

    def test_003_access_dashboard(self):
        """Test logging in to the dashboard."""
        self.access_dashboard(self.get_master_dashboard_url())

    def test_004_ceph_keys(self):
        """Check that ceph services are properly registered."""
        status = zaza.model.get_status()
        applications = status.applications.keys()
        dashboard_keys = []
        ceph_keys = []
        if 'ceph-radosgw' in applications:
            dashboard_keys.extend(['RGW_API_ACCESS_KEY', 'RGW_API_SECRET_KEY'])
        if 'grafana' in applications:
            dashboard_keys.append('GRAFANA_API_URL')
        if 'prometheus' in applications:
            dashboard_keys.append('PROMETHEUS_API_HOST')
        ceph_keys.extend(
            ['config/mgr/mgr/dashboard/{}'.format(k) for k in dashboard_keys])
        if 'ceph-iscsi' in applications:
            ceph_keys.append('mgr/dashboard/_iscsi_config')
        for key in ceph_keys:
            logging.info("Checking key {} exists".format(key))
            check_out = zaza.model.run_on_leader(
                'ceph-dashboard',
                'ceph config-key exists {}'.format(key))
            self.assertEqual(check_out['Code'], '0')

    @tenacity.retry(wait=tenacity.wait_fixed(2), reraise=True,
                    stop=tenacity.stop_after_attempt(20))
    def wait_for_saml_dashboard(self):
        """Wait until the Ceph dashboard is enabled."""
        output = zaza.model.run_on_leader(
            'ceph-mon',
            'ceph dashboard sso status')['Stdout']
        if 'enabled' in output:
            return
        raise tenacity.RetryError(None)

    def test_005_saml(self):
        """Check that the dashboard is accessible with SAML enabled."""
        url = self.get_master_dashboard_url()
        idp_meta = SAML_IDP_METADATA.format(
            cert=X509_CERT,
            data=X509_DATA,
            host=url)

        zaza.model.set_application_config(
            'ceph-dashboard',
            {'saml-base-url': url, 'saml-idp-metadata': idp_meta}
        )

        self.wait_for_saml_dashboard()

        # Check that both login and metadata are accesible.
        resp = self._run_request_get(
            url + '/auth/saml2/login',
            verify=self.local_ca_cert,
            allow_redirects=False)
        self.assertTrue(resp.status_code, requests.codes.ok)

        resp = self._run_request_get(
            url + '/auth/saml2/metadata',
            verify=self.local_ca_cert,
            allow_redirects=False)
        self.assertEqual(resp.status_code, requests.codes.ok)

    def is_app_deployed(self, app_name) -> bool:
        """Check if the provided app is deployed in the zaza model."""
        try:
            zaza.model.get_application(app_name)
            return True
        except KeyError:
            return False

    def _get_wait_for_dashboard_assert_state(
            self, state, message_prefix) -> dict:
        """Generate a assert state for ceph-dashboard charm blocked state."""
        assert_state = {
            'ceph-dashboard': {
                "workload-status": state,
                "workload-status-message-prefix": message_prefix
            }
        }
        # Telegraf has a non-standard active state message.
        if self.is_app_deployed('telegraf'):
            assert_state['telegraf'] = {
                "workload-status": "active",
                "workload-status-message-prefix": "Monitoring ceph"
            }

        return assert_state

    def verify_ssl_config(self, ca_file):
        """Check if request validates the configured SSL cert."""
        rcs = collections.defaultdict(list)
        units = zaza.model.get_units('ceph-mon')
        for unit in units:
            req = self._run_request_get(
                'https://{}:8443'.format(
                    zaza.model.get_unit_public_address(unit)),
                verify=ca_file,
                allow_redirects=False)
            rcs[req.status_code].append(
                zaza.model.get_unit_public_address(unit)
            )
        self.assertEqual(len(rcs[requests.codes.ok]), 1)
        self.assertEqual(len(rcs[requests.codes.see_other]), len(units) - 1)

    def _get_dashboard_hostnames_sans(self):
        """Get a generator for Dashboard unit public addresses."""
        yield 'ceph-dashboard'  # Include hostname in san as well.
        # Since Ceph-Dashboard is a subordinate application,
        # we use the principle application to get public addresses.
        for unit in zaza.model.get_units('ceph-mon'):
            addr = zaza.model.get_unit_public_address(unit)
            if addr:
                yield addr

    def test_006_charm_config_ssl(self):
        """Config charm SSL certs to test the Ceph dashboard application."""
        # Use RSA keys not ECSDA
        local_ca = trustme.CA(key_type=trustme.KeyType.RSA)
        server_cert = local_ca.issue_cert(
            *self._get_dashboard_hostnames_sans(),
            key_type=trustme.KeyType.RSA
        )

        ssl_cert = b64encode(server_cert.cert_chain_pems[0].bytes()).decode()
        ssl_key = b64encode(server_cert.private_key_pem.bytes()).decode()
        ssl_ca = b64encode(local_ca.cert_pem.bytes()).decode()

        # Configure local certs in charm config
        zaza.model.set_application_config(
            'ceph-dashboard',
            {
                'ssl_cert': ssl_cert, 'ssl_key': ssl_key,
                'ssl_ca': ssl_ca
            }
        )

        # Check application status message.
        assert_state = self._get_wait_for_dashboard_assert_state(
            "blocked", "Conflict: Active SSL from 'certificates' relation"
        )
        zaza.model.wait_for_application_states(
            states=assert_state, timeout=500
        )

        # Remove certificates relation to trigger configured certs.
        zaza.model.remove_relation(
            'ceph-dashboard', 'ceph-dashboard:certificates',
            'vault:certificates'
        )

        # Wait for status to clear
        assert_state = self._get_wait_for_dashboard_assert_state(
            "active", "Unit is ready"
        )
        zaza.model.wait_for_application_states(
            states=assert_state, timeout=500
        )

        # Verify Certificates.
        with local_ca.cert_pem.tempfile() as ca_temp_file:
            self.verify_ssl_config(ca_temp_file)

        # Re-add certificates relation
        zaza.model.add_relation(
            'ceph-dashboard', 'ceph-dashboard:certificates',
            'vault:certificates'
        )

        # Check blocked status message
        assert_state = self._get_wait_for_dashboard_assert_state(
            "blocked", "Conflict: Active SSL from Charm config"
        )
        zaza.model.wait_for_application_states(
            states=assert_state, timeout=500
        )

        # Remove SSL config
        zaza.model.set_application_config(
            'ceph-dashboard',
            {'ssl_cert': "", 'ssl_key': "", 'ssl_ca': ""}
        )

        # Wait for status to clear
        assert_state = self._get_wait_for_dashboard_assert_state(
            "active", "Unit is ready"
        )
        zaza.model.wait_for_application_states(
            states=assert_state, timeout=500
        )

        # Verify Relation SSL certs.
        self.verify_ssl_config(self.local_ca_cert)
