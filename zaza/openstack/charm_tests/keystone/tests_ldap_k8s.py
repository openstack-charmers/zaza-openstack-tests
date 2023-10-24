# Copyright 2023 Canonical Ltd.
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
"""Keystone LDAP tests on k8s."""

import json
import tenacity
import contextlib
import keystoneauth1.exceptions.http.NotFound as http_NotFound
import zaza.openstack.charm_tests.keystone.tests as ks_tests
import zaza.openstack.charm_tests.tempest.tests as tempest_tests
import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.model
import subprocess


class LdapExplicitCharmConfigTestsK8S(ks_tests.LdapExplicitCharmConfigTests):
    """Keystone LDAP tests for K8s deployment."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running Keystone ldap-tests."""
        cls.model_name = zaza.model.get_juju_model()
        cls.test_config = lifecycle_utils.get_charm_config(fatal=False)
        cls.default_api_version = 3
        cls.api_v3 = 3
        cls.keystone_ips = cls.get_internal_ips("keystone", cls.model_name)

    @contextlib.contextmanager
    def v3_keystone_preferred(self):
        """Set the preferred keystone api to v3 within called context."""
        with contextlib.nullcontext():
            yield

    @staticmethod
    def get_internal_ips(application, model_name):
        """Return the internal ip addresses an application."""
        status = zaza.model.get_status(model_name=model_name)
        units = status['applications'][application]["units"]
        return [v.address for v in units.values()]

    def get_ldap_ips(self):
        """Return the ip addresses for the ldap servers."""
        return self.get_internal_ips("ldap-server", self.model_name)

    def get_domain_config(self):
        """Collect the rendered domain config file."""
        # libjuju does not support ssh to a payload container
        cmd = [
            "juju",
            "ssh",
            "-m",
            self.model_name,
            "--container",
            "keystone",
            zaza.model.get_lead_unit("keystone").entity_id,
            'cat /etc/keystone/domains/keystone.userdomain.conf']
        out = subprocess.check_output(cmd)
        return out.decode()

    def _get_ldap_config(self):
        """Generate ldap config for current model.

        :return: tuple of whether ldap-server is running and if so, config
            for the keystone-ldap application.
        :rtype: Tuple[bool, Dict[str,str]]
        """
        ldap_ips = self.get_ldap_ips()
        self.assertTrue(ldap_ips, "Should be at least one ldap server")
        config_flags = json.dumps({
            'url': "ldap://{}".format(ldap_ips[0]),
            'user': 'cn=admin,dc=test,dc=com',
            "use_pool": True,
            'password': 'crapper',
            'suffix': 'dc=test,dc=com',
            'query_scope': 'one',
            'user_objectclass': 'inetOrgPerson',
            'user_id_attribute': 'cn',
            'user_name_attribute': 'sn',
            'user_enabled_attribute': 'enabled',
            'user_enabled_invert': False,
            'user_enabled_mask': 0,
            'user_enabled_default': 'True',
            'group_tree_dn': 'ou=groups,dc=test,dc=com',
            'group_id_attribute': 'cn',
            'group_name_attribute': 'cn',
            'group_member_attribute': 'memberUid',
            'group_members_are_ids': True,
            "group_objectclass": "posixGroup",
        })
        return {
            "ldap-config-flags": config_flags,
            "domain-name": "userdomain"}

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=2, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(5),
                    retry=tenacity.retry_if_exception_type(http_NotFound))
    def _find_keystone_v3_group(self, group, domain):
        super()._find_keystone_v3_group(group, domain)

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=2, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(5),
                    retry=tenacity.retry_if_exception_type(http_NotFound))
    def _find_keystone_v3_user(username, domain, group=None):
        super()._find_keystone_v3_user(username, domain, group=group)


class KeystoneTempestTestK8S(tempest_tests.TempestTestScaleK8SBase):
    """Test keystone k8s scale out and scale back."""

    application_name = "keystone"
