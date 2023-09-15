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

"""Encapsulate keystone testing."""
import collections
import configparser
import json
import logging
import pprint
import tenacity
import keystoneauth1
from keystoneauth1.exceptions.connection import ConnectFailure

import zaza.model
import zaza.openstack.utilities.exceptions as zaza_exceptions
import zaza.utilities.juju as juju_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.charm_tests.tempest.tests as tempest_tests

from zaza.openstack.charm_tests.keystone import (
    BaseKeystoneTest,
    DEMO_DOMAIN,
    DEMO_TENANT,
    DEMO_USER,
    DEMO_PASSWORD,
    DEMO_PROJECT,
    DEMO_ADMIN_USER,
    DEMO_ADMIN_USER_PASSWORD,
)


class CharmOperationTest(BaseKeystoneTest):
    """Charm operation tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone charm operation tests."""
        super(CharmOperationTest, cls).setUpClass()

    def test_001_vip_in_catalog(self):
        """Verify the VIP is in the identity catalog entry.

        This test should run early. It validates that if a VIP is set it is in
        the catalog entry for keystone.
        """
        if not self.vip:
            # If the vip is not set skip this test.
            return
        endpoint_filter = {'service_type': 'identity',
                           'interface': 'public',
                           'region_name': 'RegionOne'}
        ep = self.admin_keystone_client.session.get_endpoint(**endpoint_filter)
        assert self.vip in ep, (
            "VIP: {} not found in catalog entry: {}".format(self.vip, ep))

    def test_pause_resume(self):
        """Run pause and resume tests.

        Pause service and check services are stopped, then resume and check
        they are started.
        """
        self.pause_resume(['apache2'])

    def test_key_distribution_and_rotation(self):
        """Verify key rotation.

        Note that we make the assumption that test bundle configure
        `token-expiration` to 60 and that it takes > 60s from deployment
        completes until we get to this test.
        """
        if (openstack_utils.get_os_release() <
                openstack_utils.get_os_release('xenial_ocata')):
            logging.info('skipping test < xenial_ocata')
            return

        with self.pause_resume(['apache2']):
            KEY_KEY_REPOSITORY = 'key_repository'
            CREDENTIAL_KEY_REPOSITORY = '/etc/keystone/credential-keys/'
            FERNET_KEY_REPOSITORY = '/etc/keystone/fernet-keys/'

            # get key repostiroy from leader storage
            key_repository = json.loads(juju_utils.leader_get(
                self.application_name, KEY_KEY_REPOSITORY))
            # sort keys so we can compare it to on-disk repositories
            key_repository = json.loads(json.dumps(
                key_repository, sort_keys=True),
                object_pairs_hook=collections.OrderedDict)
            logging.info('key_repository: "{}"'
                         .format(pprint.pformat(key_repository)))
            for repo in [CREDENTIAL_KEY_REPOSITORY, FERNET_KEY_REPOSITORY]:
                try:
                    for key_name, key in key_repository[repo].items():
                        if int(key_name) > 1:
                            # after initialization the repository contains the
                            # staging key (0) and the primary key (1).  After
                            # rotation the repository contains at least one key
                            # with higher index.
                            break
                    else:
                        # NOTE the charm should only rotate the fernet key
                        # repostiory and not rotate the credential key
                        # repository.
                        if repo == FERNET_KEY_REPOSITORY:
                            raise zaza_exceptions.KeystoneKeyRepositoryError(
                                'Keys in Fernet key repository has not been '
                                'rotated.')
                except KeyError:
                    raise zaza_exceptions.KeystoneKeyRepositoryError(
                        'Dict in leader setting "{}" does not contain key '
                        'repository "{}"'.format(KEY_KEY_REPOSITORY, repo))

            # get on-disk key repository from all units
            on_disk = {}
            units = zaza.model.get_units(self.application_name)
            for unit in units:
                on_disk[unit.entity_id] = {}
                for repo in [CREDENTIAL_KEY_REPOSITORY, FERNET_KEY_REPOSITORY]:
                    on_disk[unit.entity_id][repo] = {}
                    result = zaza.model.run_on_unit(
                        unit.entity_id, 'sudo ls -1 {}'.format(repo))
                    for key_name in result.get('Stdout').split():
                        result = zaza.model.run_on_unit(
                            unit.entity_id,
                            'sudo cat {}/{}'.format(repo, key_name))
                        on_disk[unit.entity_id][repo][key_name] = result.get(
                            'Stdout')
            # sort keys so we can compare it to leader storage repositories
            on_disk = json.loads(
                json.dumps(on_disk, sort_keys=True),
                object_pairs_hook=collections.OrderedDict)
            logging.info('on_disk: "{}"'.format(pprint.pformat(on_disk)))

            for unit in units:
                unit_repo = on_disk[unit.entity_id]
                lead_repo = key_repository
                if unit_repo != lead_repo:
                    raise zaza_exceptions.KeystoneKeyRepositoryError(
                        'expect: "{}" actual({}): "{}"'
                        .format(pprint.pformat(lead_repo), unit.entity_id,
                                pprint.pformat(unit_repo)))
                logging.info('"{}" == "{}"'
                             .format(pprint.pformat(unit_repo),
                                     pprint.pformat(lead_repo)))

    def test_rotate_admin_password(self):
        """Verify action used to rotate admin user's password."""
        ADMIN_PASSWD = 'admin_passwd'
        old_passwd = juju_utils.leader_get(self.application_name, ADMIN_PASSWD)

        # test access using the old password
        with self.v3_keystone_preferred():
            for ip in self.keystone_ips:
                try:
                    ks_session = openstack_utils.get_keystone_session(
                        openstack_utils.get_overcloud_auth(address=ip))
                    ks_client = openstack_utils.get_keystone_session_client(
                        ks_session)
                    ks_client.users.list()
                except keystoneauth1.exceptions.http.Forbidden:
                    raise zaza_exceptions.KeystoneAuthorizationStrict(
                        'Keystone auth with old password FAILED.')

        # run the action to rotate the password
        zaza.model.run_action_on_leader(
            self.application_name,
            'rotate-admin-password',
        )

        # test access using the new password
        with self.v3_keystone_preferred():
            for ip in self.keystone_ips:
                try:
                    ks_session = openstack_utils.get_keystone_session(
                        openstack_utils.get_overcloud_auth(address=ip))
                    ks_client = openstack_utils.get_keystone_session_client(
                        ks_session)
                    ks_client.users.list()
                except keystoneauth1.exceptions.http.Forbidden:
                    raise zaza_exceptions.KeystoneAuthorizationStrict(
                        'Keystone auth with new password FAILED.')

        # make sure the password was actually changed
        new_passwd = juju_utils.leader_get(self.application_name, ADMIN_PASSWD)
        assert old_passwd != new_passwd

    def test_rotate_service_user_password(self):
        """Verify action used to rotate a service user (glance) password."""
        GLANCE_PASSWD_KEY = "glance_passwd"
        GLANCE_APP = "glance"
        GLANCE_CONF_FILE = '/etc/glance/glance-api.conf'

        def _get_password_from_leader():
            conf = zaza.model.file_contents('glance/leader', GLANCE_CONF_FILE)
            config = configparser.ConfigParser()
            config.read_string(conf)
            return config['keystone_authtoken']['password'].strip()

        # Only do the test if glance is in the model.
        applications = zaza.model.sync_deployed(self.model_name)
        if GLANCE_APP not in applications:
            self.skipTest(
                '{} is not deployed, so not doing password change'
                .format(GLANCE_APP))
        # keep the old password to verify it is changed.
        old_passwd_leader_storage = juju_utils.leader_get(
            self.application_name, GLANCE_PASSWD_KEY)
        old_passwd_conf = _get_password_from_leader()

        # verify that images can be listed.
        glance_client = openstack_utils.get_glance_session_client(
            self.admin_keystone_session)
        glance_client.images.list()

        # run the action to rotate the password.
        zaza.model.run_action_on_leader(
            self.application_name,
            'rotate-service-user-password',
            action_params={'service-user': 'glance'},
        )

        # verify that the password has changed
        new_passwd_leader_storage = juju_utils.leader_get(
            self.application_name, GLANCE_PASSWD_KEY)
        new_passwd_conf = _get_password_from_leader()
        self.assertNotEqual(old_passwd_leader_storage,
                            new_passwd_leader_storage)
        self.assertNotEqual(old_passwd_conf,
                            new_passwd_conf)
        self.assertEqual(new_passwd_leader_storage, new_passwd_conf)

        # verify that the images can still be listed.
        glance_client = openstack_utils.get_glance_session_client(
            self.admin_keystone_session)
        glance_client.images.list()


class AuthenticationAuthorizationTest(BaseKeystoneTest):
    """Keystone authentication and authorization tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone aa-tests."""
        super(AuthenticationAuthorizationTest, cls).setUpClass()

    def test_admin_project_scoped_access(self):
        """Verify cloud admin access using project scoped token.

        `admin` user in `admin_domain` should be able to access API methods
        guarded by `rule:cloud_admin` policy using a token scoped to `admin`
        project in `admin_domain`.

        We implement a policy that enables domain segregation and
        administration delegation [0].  It is important to understand that this
        differs from the default policy.

        In the initial implementation it was necessary to switch between using
        a `domain` scoped and `project` scoped token to successfully manage a
        cloud, but since the introduction of `is_admin` functionality in
        Keystone [1][2][3] and our subsequent adoption of it in Keystone charm
        [4], this is no longer necessary.

        This test here to validate this behaviour.

        0: https://github.com/openstack/keystone/commit/c7a5c6c
        1: https://github.com/openstack/keystone/commit/e702369
        2: https://github.com/openstack/keystone/commit/e923a14
        3: https://github.com/openstack/keystone/commit/9804081
        4: https://github.com/openstack/charm-keystone/commit/10e3d84
        """
        if (openstack_utils.get_os_release() <
                openstack_utils.get_os_release('trusty_mitaka')):
            logging.info('skipping test < trusty_mitaka')
            return
        with self.v3_keystone_preferred():
            for ip in self.keystone_ips:
                try:
                    logging.info('keystone IP {}'.format(ip))
                    ks_session = openstack_utils.get_keystone_session(
                        openstack_utils.get_overcloud_auth(address=ip))
                    ks_client = openstack_utils.get_keystone_session_client(
                        ks_session)
                    result = ks_client.domains.list()
                    logging.info('.domains.list: "{}"'
                                 .format(pprint.pformat(result)))
                except keystoneauth1.exceptions.http.Forbidden as e:
                    raise zaza_exceptions.KeystoneAuthorizationStrict(
                        'Retrieve domain list as admin with project scoped '
                        'token FAILED. ({})'.format(e))
            logging.info('OK')

    def test_end_user_domain_admin_access(self):
        """Verify that end-user domain admin does not have elevated privileges.

        In addition to validating that the `policy.json` is written and the
        service is restarted on config-changed, the test validates that our
        `policy.json` is correct.

        Catch regressions like LP: #1651989
        """
        if (openstack_utils.get_os_release() <
                openstack_utils.get_os_release('xenial_ocata')):
            logging.info('skipping test < xenial_ocata')
            return
        with self.v3_keystone_preferred():
            for ip in self.keystone_ips:
                openrc = {
                    'API_VERSION': 3,
                    'OS_USERNAME': DEMO_ADMIN_USER,
                    'OS_PASSWORD': DEMO_ADMIN_USER_PASSWORD,
                    'OS_AUTH_URL': 'http://{}:5000/v3'.format(ip),
                    'OS_USER_DOMAIN_NAME': DEMO_DOMAIN,
                    'OS_DOMAIN_NAME': DEMO_DOMAIN,
                }
                if self.tls_rid:
                    openrc['OS_CACERT'] = openstack_utils.get_cacert()
                    openrc['OS_AUTH_URL'] = (
                        openrc['OS_AUTH_URL'].replace('http', 'https'))
                logging.info('keystone IP {}'.format(ip))
                keystone_session = openstack_utils.get_keystone_session(
                    openrc, scope='DOMAIN')
                keystone_client = openstack_utils.get_keystone_session_client(
                    keystone_session)
                try:
                    # expect failure
                    keystone_client.domains.list()
                except keystoneauth1.exceptions.http.Forbidden as e:
                    logging.debug('Retrieve domain list as end-user domain '
                                  'admin NOT allowed...OK ({})'.format(e))
                    pass
                else:
                    raise zaza_exceptions.KeystoneAuthorizationPermissive(
                        'Retrieve domain list as end-user domain admin '
                        'allowed when it should not be.')
        logging.info('OK')

    def test_end_user_access_and_token(self):
        """Verify regular end-user access resources and validate token data.

        In effect this also validates user creation, presence of standard
        roles (`_member_`, `Member`), effect of policy and configuration
        of `token-provider`.
        """
        def _validate_token_data(openrc):
            if self.tls_rid:
                openrc['OS_CACERT'] = openstack_utils.get_cacert()
                openrc['OS_AUTH_URL'] = (
                    openrc['OS_AUTH_URL'].replace('http', 'https'))
            logging.info('keystone IP {}'.format(ip))
            keystone_session = openstack_utils.get_keystone_session(
                openrc)
            keystone_client = openstack_utils.get_keystone_session_client(
                keystone_session)
            token = keystone_session.get_token()
            if (openstack_utils.get_os_release() <
                    openstack_utils.get_os_release('xenial_ocata')):
                if len(token) != 32:
                    raise zaza_exceptions.KeystoneWrongTokenProvider(
                        'We expected a UUID token and got this: "{}"'
                        .format(token))
            else:
                if len(token) < 180:
                    raise zaza_exceptions.KeystoneWrongTokenProvider(
                        'We expected a Fernet token and got this: "{}"'
                        .format(token))
            logging.info('token: "{}"'.format(pprint.pformat(token)))

            if (openstack_utils.get_os_release() <
                    openstack_utils.get_os_release('trusty_mitaka')):
                logging.info('skip: tokens.get_token_data() not allowed prior '
                             'to trusty_mitaka')
                return
            # get_token_data call also gets the service catalog
            token_data = keystone_client.tokens.get_token_data(token)
            if token_data.get('token', {}).get('catalog', None) is None:
                raise zaza_exceptions.KeystoneAuthorizationStrict(
                    # NOTE(fnordahl) the above call will probably throw a
                    # http.Forbidden exception, but just in case
                    'Regular end user not allowed to retrieve the service '
                    'catalog. ("{}")'.format(pprint.pformat(token_data)))
            logging.info('token_data: "{}"'.format(pprint.pformat(token_data)))

        if (openstack_utils.get_os_release() <
                openstack_utils.get_os_release('xenial_queens')):
            openrc = {
                'API_VERSION': 2,
                'OS_USERNAME': DEMO_USER,
                'OS_PASSWORD': DEMO_PASSWORD,
                'OS_TENANT_NAME': DEMO_TENANT,
            }
            for ip in self.keystone_ips:
                openrc.update(
                    {'OS_AUTH_URL': 'http://{}:5000/v2.0'.format(ip)})
                _validate_token_data(openrc)

        if (openstack_utils.get_os_release() >=
                openstack_utils.get_os_release('trusty_mitaka')):
            openrc = {
                'API_VERSION': 3,
                'OS_REGION_NAME': 'RegionOne',
                'OS_USER_DOMAIN_NAME': DEMO_DOMAIN,
                'OS_USERNAME': DEMO_USER,
                'OS_PASSWORD': DEMO_PASSWORD,
                'OS_PROJECT_DOMAIN_NAME': DEMO_DOMAIN,
                'OS_PROJECT_NAME': DEMO_PROJECT,
            }
            with self.v3_keystone_preferred():
                for ip in self.keystone_ips:
                    openrc.update(
                        {'OS_AUTH_URL': 'http://{}:5000/v3'.format(ip)})
                    _validate_token_data(openrc)

    def test_backward_compatible_uuid_for_default_domain(self):
        """Check domain named ``default`` literally has ``default`` as ID.

        Some third party software chooses to hard code this value for some
        inexplicable reason.
        """
        with self.v3_keystone_preferred():
            ks_session = openstack_utils.get_keystone_session(
                openstack_utils.get_overcloud_auth())
            ks_client = openstack_utils.get_keystone_session_client(
                ks_session)
            domain = ks_client.domains.get('default')
            logging.info(pprint.pformat(domain))
            assert domain.id == 'default'


class SecurityTests(BaseKeystoneTest):
    """Keystone security tests tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone aa-tests."""
        super(SecurityTests, cls).setUpClass()

    def test_security_checklist(self):
        """Verify expected state with security-checklist."""
        # Changes fixing the below expected failures will be made following
        # this initial work to get validation in. There will be bugs targeted
        # to each one and resolved independently where possible.
        expected_failures = [
        ]
        expected_passes = [
            'check-max-request-body-size',
            'disable-admin-token',
            'insecure-debug-is-false',
            'uses-fernet-token-after-default',
            'uses-sha256-for-hashing-tokens',
            'validate-file-ownership',
            'validate-file-permissions',
        ]

        logging.info('Running `security-checklist` action'
                     ' on Keystone leader unit')
        test_utils.audit_assertions(
            zaza.model.run_action_on_leader(
                'keystone',
                'security-checklist',
                action_params={}),
            expected_passes,
            expected_failures,
            expected_to_pass=True)


class LdapTests(BaseKeystoneTest):
    """Keystone ldap tests."""

    non_string_type_keys = ('ldap-user-enabled-mask',
                            'ldap-user-enabled-invert',
                            'ldap-group-members-are-ids',
                            'ldap-use-pool')

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone ldap-tests."""
        super(LdapTests, cls).setUpClass()

    def _get_ldap_config(self):
        """Generate ldap config for current model.

        :return: tuple of whether ldap-server is running and if so, config
            for the keystone-ldap application.
        :rtype: Tuple[bool, Dict[str,str]]
        """
        ldap_ips = zaza.model.get_app_ips("ldap-server")
        self.assertTrue(ldap_ips, "Should be at least one ldap server")
        return {
            'ldap-server': "ldap://{}".format(ldap_ips[0]),
            'ldap-user': 'cn=admin,dc=test,dc=com',
            'ldap-password': 'crapper',
            'ldap-suffix': 'dc=test,dc=com',
            'domain-name': 'userdomain',
            'ldap-config-flags':
                {
                    'group_tree_dn': 'ou=groups,dc=test,dc=com',
                    'group_objectclass': 'posixGroup',
                    'group_name_attribute': 'cn',
                    'group_member_attribute': 'memberUid',
                    'group_members_are_ids': 'true',
            }
        }

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=2, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(5),
                    retry=tenacity.retry_if_exception_type(ConnectFailure))
    def _find_keystone_v3_user(self, username, domain, group=None):
        """Find a user within a specified keystone v3 domain.

        :param str username: Username to search for in keystone
        :param str domain: username selected from which domain
        :param str group: group to search for in keystone for group membership
        :return: return username if found
        :rtype: Optional[str]
        """
        for ip in self.keystone_ips:
            logging.info('Keystone IP {}'.format(ip))
            session = openstack_utils.get_keystone_session(
                openstack_utils.get_overcloud_auth(address=ip))
            client = openstack_utils.get_keystone_session_client(session)

            if group is None:
                domain_users = client.users.list(
                    domain=client.domains.find(name=domain).id,
                )
            else:
                domain_users = client.users.list(
                    domain=client.domains.find(name=domain).id,
                    group=self._find_keystone_v3_group(group, domain).id,
                )

            usernames = [u.name.lower() for u in domain_users]
            if username.lower() in usernames:
                return username

        logging.debug(
            "User {} was not found. Returning None.".format(username)
        )
        return None

    def _find_keystone_v3_group(self, group, domain):
        """Find a group within a specified keystone v3 domain.

        :param str group: Group to search for in keystone
        :param str domain: group selected from which domain
        :return: return group if found
        :rtype: Optional[str]
        """
        for ip in self.keystone_ips:
            logging.info('Keystone IP {}'.format(ip))
            session = openstack_utils.get_keystone_session(
                openstack_utils.get_overcloud_auth(address=ip))
            client = openstack_utils.get_keystone_session_client(session)

            domain_groups = client.groups.list(
                domain=client.domains.find(name=domain).id
            )

            for searched_group in domain_groups:
                if searched_group.name.lower() == group.lower():
                    return searched_group

        logging.debug(
            "Group {} was not found. Returning None.".format(group)
        )
        return None

    def test_100_keystone_ldap_users(self):
        """Validate basic functionality of keystone API with ldap."""
        application_name = 'keystone-ldap'
        intended_cfg = self._get_ldap_config()
        current_cfg, non_string_cfg = (
            self.config_current_separate_non_string_type_keys(
                self.non_string_type_keys, intended_cfg, application_name)
        )

        with self.config_change(
                {},
                non_string_cfg,
                application_name=application_name,
                reset_to_charm_default=True):
            with self.config_change(
                    current_cfg,
                    intended_cfg,
                    application_name=application_name):
                logging.info(
                    'Waiting for users to become available in keystone...'
                )
                test_config = lifecycle_utils.get_charm_config(fatal=False)
                zaza.model.wait_for_application_states(
                    states=test_config.get("target_deploy_status", {})
                )

                with self.v3_keystone_preferred():
                    # NOTE(jamespage): Test fixture should have
                    #                  johndoe and janedoe accounts
                    johndoe = self._find_keystone_v3_user(
                        'john doe', 'userdomain')
                    self.assertIsNotNone(
                        johndoe, "user 'john doe' was unknown")
                    janedoe = self._find_keystone_v3_user(
                        'jane doe', 'userdomain')
                    self.assertIsNotNone(
                        janedoe, "user 'jane doe' was unknown")

    def test_101_keystone_ldap_groups(self):
        """Validate basic functionality of keystone API with ldap."""
        application_name = 'keystone-ldap'
        intended_cfg = self._get_ldap_config()
        current_cfg, non_string_cfg = (
            self.config_current_separate_non_string_type_keys(
                self.non_string_type_keys, intended_cfg, application_name)
        )

        with self.config_change(
                {},
                non_string_cfg,
                application_name=application_name,
                reset_to_charm_default=True):
            with self.config_change(
                    current_cfg,
                    intended_cfg,
                    application_name=application_name):
                logging.info(
                    'Waiting for groups to become available in keystone...'
                )
                test_config = lifecycle_utils.get_charm_config(fatal=False)
                zaza.model.wait_for_application_states(
                    states=test_config.get("target_deploy_status", {})
                )

                with self.v3_keystone_preferred():
                    # NOTE(arif-ali): Test fixture should have openstack and
                    #                 admin groups
                    openstack_group = self._find_keystone_v3_group(
                        'openstack', 'userdomain')
                    self.assertIsNotNone(
                        openstack_group.name, "group 'openstack' was unknown")
                    admin_group = self._find_keystone_v3_group(
                        'admin', 'userdomain')
                    self.assertIsNotNone(
                        admin_group.name, "group 'admin' was unknown")

    def test_102_keystone_ldap_group_membership(self):
        """Validate basic functionality of keystone API with ldap."""
        application_name = 'keystone-ldap'
        intended_cfg = self._get_ldap_config()
        current_cfg, non_string_cfg = (
            self.config_current_separate_non_string_type_keys(
                self.non_string_type_keys, intended_cfg, application_name)
        )

        with self.config_change(
                {},
                non_string_cfg,
                application_name=application_name,
                reset_to_charm_default=True):
            with self.config_change(
                    current_cfg,
                    intended_cfg,
                    application_name=application_name):
                logging.info(
                    'Waiting for groups to become available in keystone...'
                )
                test_config = lifecycle_utils.get_charm_config(fatal=False)
                zaza.model.wait_for_application_states(
                    states=test_config.get("target_deploy_status", {})
                )

                with self.v3_keystone_preferred():
                    # NOTE(arif-ali): Test fixture should have openstack and
                    #                 admin groups
                    openstack_group = self._find_keystone_v3_user(
                        'john doe', 'userdomain', group='openstack')
                    self.assertIsNotNone(
                        openstack_group,
                        "john doe was not in group 'openstack'")
                    admin_group = self._find_keystone_v3_user(
                        'john doe', 'userdomain', group='admin')
                    self.assertIsNotNone(
                        admin_group, "'john doe' was not in group 'admin'")


class LdapExplicitCharmConfigTests(LdapTests):
    """Keystone ldap tests."""

    def _get_ldap_config(self):
        """Generate ldap config for current model.

        :return: tuple of whether ldap-server is running and if so, config
            for the keystone-ldap application.
        :rtype: Tuple[bool, Dict[str,str]]
        """
        ldap_ips = zaza.model.get_app_ips("ldap-server")
        self.assertTrue(ldap_ips, "Should be at least one ldap server")
        return {
            'ldap-server': "ldap://{}".format(ldap_ips[0]),
            'ldap-user': 'cn=admin,dc=test,dc=com',
            'ldap-password': 'crapper',
            'ldap-suffix': 'dc=test,dc=com',
            'domain-name': 'userdomain',
            'ldap-query-scope': 'one',
            'ldap-user-objectclass': 'inetOrgPerson',
            'ldap-user-id-attribute': 'cn',
            'ldap-user-name-attribute': 'sn',
            'ldap-user-enabled-attribute': 'enabled',
            'ldap-user-enabled-invert': False,
            'ldap-user-enabled-mask': 0,
            'ldap-user-enabled-default': 'True',
            'ldap-group-tree-dn': 'ou=groups,dc=test,dc=com',
            'ldap-group-objectclass': '',
            'ldap-group-id-attribute': 'cn',
            'ldap-group-name-attribute': 'cn',
            'ldap-group-member-attribute': 'memberUid',
            'ldap-group-members-are-ids': True,
            'ldap-config-flags': '{group_objectclass: "posixGroup",'
                                 ' use_pool: True,'
                                 ' group_tree_dn: "group_tree_dn_foobar"}',
        }

    def test_200_config_flags_precedence(self):
        """Validates precedence when the same config options are used."""
        application_name = 'keystone-ldap'
        intended_cfg = self._get_ldap_config()
        current_cfg, non_string_cfg = (
            self.config_current_separate_non_string_type_keys(
                self.non_string_type_keys, intended_cfg, application_name)
        )

        with self.config_change(
                {},
                non_string_cfg,
                application_name=application_name,
                reset_to_charm_default=True):
            with self.config_change(
                    current_cfg,
                    intended_cfg,
                    application_name=application_name):
                logging.info(
                    'Performing LDAP settings validation in keystone.conf...'
                )
                test_config = lifecycle_utils.get_charm_config(fatal=False)
                zaza.model.wait_for_application_states(
                    states=test_config.get("target_deploy_status", {})
                )
                units = zaza.model.get_units("keystone-ldap",
                                             model_name=self.model_name)
                result = zaza.model.run_on_unit(
                    units[0].name,
                    "cat /etc/keystone/domains/keystone.userdomain.conf")
                # not present in charm config, but present in config flags
                self.assertIn("use_pool = True", result['stdout'],
                              "use_pool value is expected to be present and "
                              "set to True in the config file")
                # ldap-config-flags overriding empty charm config value
                self.assertIn("group_objectclass = posixGroup",
                              result['stdout'],
                              "group_objectclass is expected to be present and"
                              " set to posixGroup in the config file")
                # overridden by charm config, not written to file
                self.assertNotIn(
                    "group_tree_dn_foobar",
                    result['stdout'],
                    "user_tree_dn ldap-config-flags value needs to be "
                    "overridden by ldap-user-tree-dn in config file")
                # complementing the above, value used is from charm setting
                self.assertIn("group_tree_dn = ou=groups", result['stdout'],
                              "user_tree_dn value is expected to be present "
                              "and set to dc=test,dc=com in the config file")


class KeystoneTempestTestK8S(tempest_tests.TempestTestScaleK8SBase):
    """Test keystone k8s scale out and scale back."""

    application_name = "keystone"
