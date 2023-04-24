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

"""Encapsulate horizon (openstack-dashboard) charm testing."""

import base64
import http.client
import logging
import requests
import tenacity
import urllib.request
import yaml

import zaza.model as zaza_model

import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.charm_tests.policyd.tests as policyd


class AuthExceptions(Exception):
    """Exception base class for the 401 test."""

    pass


class FailedAuth(AuthExceptions):
    """Failed exception for the 401 test."""

    pass


# NOTE: intermittent authentication fails. Wrap in a retry loop.
@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1,
                                               min=5, max=10),
                reraise=True)
def _login(dashboard_url, domain, username, password, cafile=None):
    """Login to the website to get a session.

    :param dashboard_url: The URL of the dashboard to log in to.
    :type dashboard_url: str
    :param domain: the domain to login into
    :type domain: str
    :param username: the username to login as
    :type username: str
    :param password: the password to use to login
    :type password: str
    :returns: tuple of (client, response) where response is the page after
              logging in.
    :rtype: (requests.sessions.Session, requests.models.Response)
    :raises: FailedAuth if the authorisation doesn't work
    """
    auth_url = '{}/auth/login/'.format(dashboard_url)

    # start session, get csrftoken
    client = requests.session()
    client.get(auth_url, verify=cafile, timeout=30)
    if 'csrftoken' in client.cookies:
        csrftoken = client.cookies['csrftoken']
    else:
        raise Exception("Missing csrftoken")

    # build and send post request
    overcloud_auth = openstack_utils.get_overcloud_auth()

    if overcloud_auth['OS_AUTH_URL'].endswith("v2.0"):
        api_version = 2
    else:
        api_version = 3
    keystone_client = openstack_utils.get_keystone_client(
        overcloud_auth)
    catalog = keystone_client.service_catalog.get_endpoints()
    logging.info(catalog)
    if api_version == 2:
        region = catalog['identity'][0]['publicURL']
    else:
        region = [i['url']
                  for i in catalog['identity']
                  if i['interface'] == 'public'][0]

    auth = {
        'domain': domain,
        'username': username,
        'password': password,
        'csrfmiddlewaretoken': csrftoken,
        'next': '/horizon/',
        'region': region,
    }

    # In the minimal test deployment /horizon/project/ is unauthorized,
    # this does not occur in a full deployment and is probably due to
    # services/information missing that horizon wants to display data
    # for.
    # Redirect to /horizon/identity/ instead.
    if (openstack_utils.get_os_release() >=
            openstack_utils.get_os_release('xenial_queens')):
        auth['next'] = '/horizon/identity/'

    if (openstack_utils.get_os_release() >=
            openstack_utils.get_os_release('bionic_stein')):
        auth['region'] = 'default'

    if api_version == 2:
        del auth['domain']

    logging.info('POST data: "{}"'.format(auth))
    response = client.post(
        auth_url,
        data=auth,
        headers={'Referer': auth_url},
        verify=cafile)

    # NOTE(ajkavanagh) there used to be a trusty/icehouse test in the
    # amulet test, but as the zaza tests only test from trusty/mitaka
    # onwards, the test has been dropped
    if (openstack_utils.get_os_release() >=
            openstack_utils.get_os_release('bionic_stein')):
        expect = "Sign Out"
        # update the in dashboard seems to require region to be default in
        # this test configuration
        region = 'default'
    else:
        expect = 'Projects - OpenStack Dashboard'

    if expect not in response.text:
        msg = 'FAILURE code={} text="{}"'.format(response,
                                                 response.text)
        logging.info("Yeah, wen't wrong: {}".format(msg))
        raise FailedAuth(msg)
    logging.info("Logged into okay")
    return client, response


# NOTE(ajkavanagh): it seems that apache2 doesn't start quickly enough
# for the test, and so it gets reset errors; repeat until either that
# stops or there is a failure
@tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, min=5, max=10),
                retry=tenacity.retry_if_exception_type(
                    http.client.RemoteDisconnected),
                reraise=True)
def _do_request(request, cafile=None):
    """Open a webpage via urlopen.

    :param request: A urllib request object.
    :type request: object
    :returns: HTTPResponse object
    :rtype: object
    :raises: URLError on protocol errors
    """
    return urllib.request.urlopen(request, cafile=cafile)


class OpenStackDashboardBase():
    """Mixin for interacting with Horizon."""

    def get_base_url(self):
        """Return the base url for http(s) requests.

        :returns: URL
        :rtype: str
        """
        vip = (zaza_model.get_application_config(self.application_name)
               .get("vip").get("value"))
        if vip:
            ip = vip
        else:
            unit = zaza_model.get_unit_from_name(
                zaza_model.get_lead_unit_name(self.application_name))
            ip = zaza_model.get_unit_public_address(unit)

        logging.debug("Dashboard ip is:{}".format(ip))
        scheme = 'http'
        if self.use_https:
            scheme = 'https'
        url = '{}://{}'.format(scheme, ip)
        return url

    def get_horizon_url(self):
        """Return the url for acccessing horizon.

        :returns: Horizon URL
        :rtype: str
        """
        url = '{}/horizon'.format(self.get_base_url())
        logging.info("Horizon URL is: {}".format(url))
        return url

    @property
    def use_https(self):
        """Whether dashboard is using https.

        :returns: Whether dashboard is using https
        :rtype: boolean
        """
        use_https = False
        vault_relation = zaza_model.get_relation_id(
            self.application,
            'vault',
            remote_interface_name='certificates')
        if vault_relation:
            use_https = True
        return use_https


class OpenStackDashboardTests(test_utils.OpenStackBaseTest,
                              OpenStackDashboardBase):
    """Encapsulate openstack dashboard charm tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running openstack dashboard charm tests."""
        super(OpenStackDashboardTests, cls).setUpClass()
        cls.application = 'openstack-dashboard'

    def test_050_local_settings_permissions_regression_check_lp1755027(self):
        """Assert regression check lp1755027.

        Assert the intended file permissions on openstack-dashboard's
        configuration file. Regression coverage for
        https://bugs.launchpad.net/bugs/1755027.

        Ported from amulet tests.
        """
        file_path = '/etc/openstack-dashboard/local_settings.py'
        expected_perms = '640'
        unit_name = zaza_model.get_lead_unit_name('openstack-dashboard')

        logging.info('Checking {} permissions...'.format(file_path))

        # NOTE(beisner): This could be a new test helper, but it needs
        # to be a clean backport to stable with high prio, so maybe later.
        cmd = 'stat -c %a {}'.format(file_path)
        output = zaza_model.run_on_unit(unit_name, cmd)
        perms = output['Stdout'].strip()
        assert perms == expected_perms, \
            ('{} perms of {} not expected ones of {}'
             .format(file_path, perms, expected_perms))

    def test_100_services(self):
        """Verify the expected services are running.

        Ported from amulet tests.
        """
        logging.info('Checking openstack-dashboard services...')

        unit_name = zaza_model.get_lead_unit_name('openstack-dashboard')
        openstack_services = ['apache2']
        services = {}
        services[unit_name] = openstack_services

        for unit_name, unit_services in services.items():
            zaza_model.block_until_service_status(
                unit_name=unit_name,
                services=unit_services,
                target_status='running'
            )

    def test_200_haproxy_stats_config(self):
        """Verify that the HAProxy stats are properly setup."""
        logging.info('Checking dashboard HAProxy settings...')
        unit = zaza_model.get_unit_from_name(
            zaza_model.get_lead_unit_name(self.application_name))
        logging.debug("... dashboard_ip is:{}".format(
            zaza_model.get_unit_public_address(unit)))
        conf = '/etc/haproxy/haproxy.cfg'
        port = '8888'
        set_alternate = {
            'haproxy-expose-stats': 'True',
        }

        request = urllib.request.Request(
            'http://{}:{}'.format(
                zaza_model.get_unit_public_address(unit), port))

        output = str(generic_utils.get_file_contents(unit, conf))

        password = None
        for line in output.split('\n'):
            if "stats auth" in line:
                password = line.split(':')[1]
                break
        else:
            raise ValueError("'stats auth' not found in output'")
        base64string = base64.b64encode(
            bytes('{}:{}'.format('admin', password), 'ascii'))
        request.add_header(
            "Authorization", "Basic {}".format(base64string.decode('utf-8')))

        # Expect default config to not be available externally.
        expected = 'bind 127.0.0.1:{}'.format(port)
        self.assertIn(expected, output)
        with self.assertRaises(urllib.error.URLError):
            _do_request(request)

        zaza_model.set_application_config(self.application_name, set_alternate)
        zaza_model.block_until_all_units_idle(model_name=self.model_name)

        # Once exposed, expect HAProxy stats to be available externally
        output = str(generic_utils.get_file_contents(unit, conf))
        expected = 'bind 0.0.0.0:{}'.format(port)
        html = _do_request(request).read().decode(encoding='utf-8')
        self.assertIn(expected, output)
        self.assertIn('Statistics Report for HAProxy', html,
                      "HAProxy stats check failed")

    def test_302_router_settings(self):
        """Verify that the horizon router settings are correct.

        Ported from amulet tests.
        """
        # note this test is only valid after trusty-icehouse; however, all of
        # the zaza tests are after trusty-icehouse
        logging.info('Checking dashboard router settings...')
        unit_name = zaza_model.get_lead_unit_name('openstack-dashboard')
        conf = ('/usr/share/openstack-dashboard/openstack_dashboard/'
                'enabled/_40_router.py')

        cmd = 'cat {}'.format(conf)
        output = zaza_model.run_on_unit(unit_name, cmd)

        expected = {
            'DISABLED': "True",
        }
        mismatches = self.crude_py_parse(output['Stdout'], expected)
        assert not mismatches, ("mismatched keys on {} were:\n{}"
                                .format(conf, ", ".join(mismatches)))

    def crude_py_parse(self, file_contents, expected):
        """Parse a python file looking for key = value assignements."""
        mismatches = []
        for line in file_contents.split('\n'):
            if '=' in line:
                args = line.split('=')
                if len(args) <= 1:
                    continue
                key = args[0].strip()
                value = args[1].strip()
                if key in expected.keys():
                    if expected[key] != value:
                        msg = "Mismatch %s != %s" % (expected[key], value)
                        mismatches.append(msg)
        return mismatches

    def test_400_connection(self):
        """Test that dashboard responds to http request.

        Ported from amulet tests.
        """
        logging.info('Checking dashboard http response...')
        request = urllib.request.Request(self.get_horizon_url())
        try:
            logging.info("... trying to fetch the page")
            html = _do_request(request, cafile=self.cacert)
            logging.info("... fetched page")
        except Exception as e:
            logging.info("... exception raised was {}".format(str(e)))
            raise
        return html.read().decode('utf-8')
        self.assertIn('OpenStack Dashboard', html,
                      "Dashboard frontpage check failed")

    def test_401_authenticate(self):
        """Validate that authentication succeeds for client log in."""
        logging.info('Checking authentication through dashboard...')

        overcloud_auth = openstack_utils.get_overcloud_auth()
        password = overcloud_auth['OS_PASSWORD'],
        logging.info("admin password is {}".format(password))
        # try to get the url which will either pass or fail with a 403
        overcloud_auth = openstack_utils.get_overcloud_auth()
        domain = 'admin_domain',
        username = 'admin',
        password = overcloud_auth['OS_PASSWORD'],
        _login(
            self.get_horizon_url(),
            domain,
            username,
            password,
            cafile=self.cacert)
        logging.info('OK')

    def test_404_connection(self):
        """Verify the apache status module gets disabled when hardening apache.

        Ported from amulet tests.
        """
        logging.info('Checking apache mod_status gets disabled.')
        logging.debug('Maybe enabling hardening for apache...')
        _app_config = zaza_model.get_application_config(self.application_name)
        logging.info(_app_config['harden'])

        request = urllib.request.Request(self.get_horizon_url())
        with self.config_change(
                {'harden': _app_config['harden'].get('value', '')},
                {'harden': 'apache'}):
            try:
                _do_request(request, cafile=self.cacert)
            except urllib.request.HTTPError as e:
                # test failed if it didn't return 404
                msg = "Apache mod_status check failed."
                self.assertEqual(e.code, 404, msg)
        logging.info('OK')

    def test_900_restart_on_config_change(self):
        """Verify that the specified services are restarted on config changed.

        Ported from amulet tests.
        """
        logging.info("Testing restart on config changed.")

        # Expected default and alternate values
        current_value = zaza_model.get_application_config(
            self.application_name)['use-syslog']['value']
        new_value = str(not bool(current_value)).title()
        current_value = str(current_value).title()

        # Expected default and alternate values
        set_default = {'use-syslog': current_value}
        set_alternate = {'use-syslog': new_value}

        # Services which are expected to restart upon config change,
        # and corresponding config files affected by the change
        services = ['apache2', 'memcached']
        conf_file = '/etc/openstack-dashboard/local_settings.py'

        # Make config change, check for service restarts
        logging.info('Setting use-syslog on openstack-dashboard {}'
                     .format(set_alternate))
        self.restart_on_changed(
            conf_file,
            set_default,
            set_alternate,
            None, None,
            services)

    def test_910_pause_and_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped then resume and check
        they are started

        Ported from amulet tests.
        """
        with self.pause_resume(['apache2']):
            logging.info("Testing pause resume")

    def test_920_get_noncacheable_content_and_check_cookie(self):
        """Login and check cache cookies.

        All non-cacheable content should have all the following headers:

        Cache-Control: no-store
        Pragma: no-cache
        """
        logging.info("Testing caching headers on non-cacheable content.")
        overcloud_auth = openstack_utils.get_overcloud_auth()
        password = overcloud_auth['OS_PASSWORD']

        domain = 'admin_domain'
        username = 'admin'
        client, response = _login(
            self.get_horizon_url(), domain, username, password,
            cafile=self.cacert)

        expected_headers = {
            "cache-control": "no-store",
            "pragma": "no-cache"
        }
        for header, value in expected_headers.items():
            self.assertIn(value, response.headers.get(header, "none").lower())

    def test_930_get_cacheable_content_and_check_cookie(self):
        """Get random static file and check cookies.

        Cachable files should not have any of the following headers:

        Cache-Control: no-store
        Pragma: no-cache
        """
        logging.info("Testing caching headers on cacheable content.")
        unit_name = zaza_model.get_lead_unit_name('openstack-dashboard')
        static_files_location = "/var/lib/openstack-dashboard/static/"
        cmd = 'find {} -iname ''*.css'' -type f | sort -R | ' \
              'sed "s#/var/lib/openstack-dashboard##" | head -1' \
            .format(static_files_location)
        output = zaza_model.run_on_unit(unit_name, cmd)
        url = "{}{}".format(self.get_horizon_url(), output['Stdout'].strip())

        unexpected_headers = {
            "cache-control": "no-store",
            "pragma": "no-cache"
        }

        client = requests.session()
        response = client.get(url, verify=self.cacert, timeout=30)

        for header, value in unexpected_headers.items():
            self.assertNotIn(value,
                             response.headers.get(header, "none").lower())


class OpenStackDashboardPolicydTests(policyd.BasePolicydSpecialization,
                                     OpenStackDashboardBase):
    """Test the policyd override using the dashboard."""

    good = {
        "identity/file1.yaml": "{'rule1': '!'}"
    }
    bad = {
        "identity/file2.yaml": "{'rule': '!}"
    }
    path_infix = "keystone_policy.d"
    _rule = {'identity/rule.yaml': yaml.dump({
        'identity:list_domains': '!',
        'identity:get_domain': '!',
        'identity:update_domain': '!',
        'identity:list_domains_for_user': '!',
    })}

    # url associated with rule above that will return HTTP 403
    url = "{}/identity/domains"

    @classmethod
    def setUpClass(cls, application_name=None):
        """Run class setup for running horizon charm operation tests."""
        super(OpenStackDashboardPolicydTests, cls).setUpClass(
            application_name="openstack-dashboard")
        cls.application_name = "openstack-dashboard"
        cls.application = cls.application_name

    def get_client_and_attempt_operation(self, ip):
        """Attempt to list users on the openstack-dashboard service.

        This is slightly complicated in that the client is actually a web-site.
        Thus, the test has to login first and then attempt the operation.  This
        makes the test a little more complicated.

        :param ip: the IP address to get the session against.
        :type ip: str
        :raises: PolicydOperationFailedException if operation fails.
        """
        unit = zaza_model.get_unit_from_name(
            zaza_model.get_lead_unit_name(self.application_name))
        logging.info("Dashboard is at {}".format(
            zaza_model.get_unit_public_address(unit)))
        overcloud_auth = openstack_utils.get_overcloud_auth()
        password = overcloud_auth['OS_PASSWORD']
        logging.info("admin password is {}".format(password))
        # try to get the url which will either pass or fail with a 403
        domain = 'admin_domain'
        username = 'admin'
        client, response = _login(
            self.get_horizon_url(), domain, username, password,
            cafile=self.cacert)
        # now attempt to get the domains page
        _url = self.url.format(self.get_horizon_url())
        logging.info("URL is {}".format(_url))
        result = client.get(_url)
        if result.status_code == 403:
            raise policyd.PolicydOperationFailedException("Not authenticated")


class SecurityTests(test_utils.OpenStackBaseTest,
                    OpenStackDashboardBase):
    """Openstack-dashboard security tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running openstack-dashboard SecurityTests."""
        super(SecurityTests, cls).setUpClass()

    def test_security_checklist(self):
        """Verify expected state with security checklist."""
        logging.info("Testing security checklist.")

        expected_failures = [
            'csrf_cookie_set',
            'disable_password_reveal',
            'disallow-iframe-embed',
            'password-validator-is-not-default',
            'securie_proxy_ssl_header_is_set',
            'session_cookie-httponly',
            'session-cookie-store',
        ]
        expected_passes = [
            'disable_password_autocomplete',
            'enforce-password-check',
            'validate-file-ownership',
            'validate-file-permissions'
        ]

        logging.info('Running `security-checklist` action'
                     ' on {} leader'.format(self.application_name))
        test_utils.audit_assertions(
            zaza_model.run_action_on_leader(
                self.application_name,
                'security-checklist',
                model_name=self.model_name,
                action_params={}),
            expected_passes,
            expected_failures,
            expected_to_pass=False)
