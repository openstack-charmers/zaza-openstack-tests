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

import collections
import json
import logging
import requests
import tenacity
import uuid

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
            allow_redirects=allow_redirects)

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
            verify=verify)

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
        return url

    def test_dashboard_units(self):
        """Check dashboard units are configured correctly."""
        verify = self.local_ca_cert
        units = zaza.model.get_units(self.application_name)
        rcs = collections.defaultdict(list)
        for unit in units:
            r = self._run_request_get(
                'https://{}:8443'.format(
                    zaza.model.get_unit_public_address(unit)),
                verify=verify,
                allow_redirects=False)
            rcs[r.status_code].append(zaza.model.get_unit_public_address(unit))
        self.assertEqual(len(rcs[requests.codes.ok]), 1)
        self.assertEqual(len(rcs[requests.codes.see_other]), len(units) - 1)

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

    def test_create_user(self):
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

    def test_access_dashboard(self):
        """Test logging in to the dashboard."""
        self.access_dashboard(self.get_master_dashboard_url())

    def test_ceph_keys(self):
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
        output = zaza.model.run_on_leader(
            'ceph-mon',
            'ceph dashboard sso status')['Stdout']
        if 'enabled' in output:
            return
        raise tenacity.RetryError(None)

    def test_saml(self):
        """Check that the dashboard is accessible with SAML enabled."""
        get_os_release = openstack_utils.get_os_release
        if (get_os_release(application='ceph-mon') <
                get_os_release('focal_yoga')):
            return

        url = self.get_master_dashboard_url()
        idp_meta = SAML_IDP_METADATA.format(
            cert=X509_CERT,
            data=X509_DATA,
            host=url)

        zaza.model.set_application_config(
            'ceph-dashboard',
            {'saml-base-url': url, 'saml-idp-metadata': idp_meta}
        )

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
