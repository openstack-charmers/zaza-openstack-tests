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

import logging
import requests
import tenacity
import urllib.request

import zaza.model as zaza_model

import zaza.openstack.utilities.openstack as openstack_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.juju as openstack_juju


class OpenStackDashboardTests(test_utils.OpenStackBaseTest):
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

        unit_name = zaza_model.get_lead_unit_name('openstack-dashboard')
        keystone_unit = zaza_model.get_lead_unit_name('keystone')
        dashboard_relation = openstack_juju.get_relation_from_unit(
            keystone_unit, unit_name, 'identity-service')
        dashboard_ip = dashboard_relation['private-address']
        logging.debug("... dashboard_ip is:{}".format(dashboard_ip))

        # NOTE(fnordahl) there is a eluding issue that currently makes the
        #                first request to the OpenStack Dashboard error out
        #                with 500 Internal Server Error in CI.  Temporarilly
        #                add retry logic to unwedge the gate.  This issue
        #                should be revisited and root caused properly when time
        #                allows.
        @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1,
                                                       min=5, max=10),
                        reraise=True)
        def do_request():
            logging.info("... trying to fetch the page")
            try:
                response = urllib.request.urlopen('http://{}/horizon'
                                                  .format(dashboard_ip))
                logging.info("... fetched page")
            except Exception as e:
                logging.info("... exception raised was {}".format(str(e)))
                raise
            return response.read().decode('utf-8')
        html = do_request()
        self.assertIn('OpenStack Dashboard', html,
                      "Dashboard frontpage check failed")

    class AuthExceptions(Exception):
        """Exception base class for the 401 test."""

        pass

    class FailedAuth(AuthExceptions):
        """Failed exception for the 401 test."""

        pass

    class PassedAuth(AuthExceptions):
        """Passed exception for the 401 test."""

        pass

    def test_401_authenticate(self):
        """Validate that authentication succeeds for client log in.

        Ported from amulet tests.
        """
        logging.info('Checking authentication through dashboard...')

        unit_name = zaza_model.get_lead_unit_name('openstack-dashboard')
        keystone_unit = zaza_model.get_lead_unit_name('keystone')
        dashboard_relation = openstack_juju.get_relation_from_unit(
            keystone_unit, unit_name, 'identity-service')
        dashboard_ip = dashboard_relation['private-address']
        logging.debug("... dashboard_ip is:{}".format(dashboard_ip))

        url = 'http://{}/horizon/auth/login/'.format(dashboard_ip)

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

        # NOTE(thedac) Similar to the connection test above we get occasional
        # intermittent authentication fails. Wrap in a retry loop.
        @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1,
                                                       min=5, max=10),
                        retry=tenacity.retry_unless_exception_type(
                            self.AuthExceptions),
                        reraise=True)
        def _do_auth_check(expect):
            # start session, get csrftoken
            client = requests.session()
            client.get(url)

            if 'csrftoken' in client.cookies:
                csrftoken = client.cookies['csrftoken']
            else:
                raise Exception("Missing csrftoken")

            # build and send post request
            auth = {
                'domain': 'admin_domain',
                'username': 'admin',
                'password': overcloud_auth['OS_PASSWORD'],
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
            response = client.post(url, data=auth, headers={'Referer': url})

            if expect not in response.text:
                msg = 'FAILURE code={} text="{}"'.format(response,
                                                         response.text)
                # NOTE(thedac) amulet.raise_status exits on exception.
                # Raise a custom exception.
                logging.info("Yeah, wen't wrong: {}".format(msg))
                raise self.FailedAuth(msg)
            raise self.PassedAuth()

        try:
            _do_auth_check(expect)
        except self.FailedAuth as e:
            assert False, str(e)
        except self.PassedAuth:
            pass

    def test_404_connection(self):
        """Verify the apache status module gets disabled when hardening apache.

        Ported from amulet tests.
        """
        logging.info('Checking apache mod_status gets disabled.')

        unit_name = zaza_model.get_lead_unit_name('openstack-dashboard')
        keystone_unit = zaza_model.get_lead_unit_name('keystone')
        dashboard_relation = openstack_juju.get_relation_from_unit(
            keystone_unit, unit_name, 'identity-service')
        dashboard_ip = dashboard_relation['private-address']
        logging.debug("... dashboard_ip is:{}".format(dashboard_ip))

        logging.debug('Maybe enabling hardening for apache...')
        _app_config = zaza_model.get_application_config(self.application_name)
        logging.info(_app_config['harden'])
        with self.config_change(
                {'harden': _app_config['harden'].get('value', '')},
                {'harden': 'apache'}):
            try:
                urllib.request.urlopen('http://{}/server-status'
                                       .format(dashboard_ip))
            except urllib.request.HTTPError as e:
                if e.code == 404:
                    return
        # test failed if it didn't return 404
        msg = "Apache mod_status check failed."
        assert False, msg

    def test_501_security_checklist_action(self):
        """Verify expected result on a default install.

        Ported from amulet tests.
        """
        logging.info("Testing security-checklist")
        unit_name = zaza_model.get_lead_unit_name('openstack-dashboard')
        action = zaza_model.run_action(unit_name, 'security-checklist')
        assert action.data.get(u"status") == "failed", \
            "Security check is expected to not pass by default"

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
