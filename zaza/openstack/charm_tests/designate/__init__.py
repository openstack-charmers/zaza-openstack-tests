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

"""Collection of code for setting up and testing designate."""
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.utilities.openstack as openstack_utils


class BaseDesignateTest(test_utils.OpenStackBaseTest):
    """Base for Designate charm tests."""

    @classmethod
    def setUpClass(cls, application_name=None, model_alias=None):
        """Run class setup for running Designate charm operation tests."""
        application_name = application_name or "designate"
        model_alias = model_alias or ""
        super(BaseDesignateTest, cls).setUpClass(application_name, model_alias)
        os_release = openstack_utils.get_os_release

        if os_release() >= os_release('bionic_rocky'):
            cls.designate_svcs = [
                'designate-agent', 'designate-api', 'designate-central',
                'designate-mdns', 'designate-worker', 'designate-sink',
                'designate-producer',
            ]
        else:
            cls.designate_svcs = [
                'designate-agent', 'designate-api', 'designate-central',
                'designate-mdns', 'designate-pool-manager', 'designate-sink',
                'designate-zone-manager',
            ]

        # Get keystone session
        keystone_api = 3 if os_release() >= os_release('xenial_queens') else 2
        cls.keystone_session = openstack_utils.get_overcloud_keystone_session()
        cls.keystone = openstack_utils.get_keystone_session_client(
            cls.keystone_session, keystone_api
        )

        if os_release() >= os_release('xenial_queens'):
            cls.designate = openstack_utils.get_designate_session_client(
                session=cls.keystone_session
            )
            cls.zones_list = cls.designate.zones.list
            cls.zones_delete = cls.designate.zones.delete
        else:
            # Authenticate admin with designate endpoint
            designate_ep = cls.keystone.service_catalog.url_for(
                service_type='dns',
                interface='publicURL')
            keystone_ep = cls.keystone.service_catalog.url_for(
                service_type='identity',
                interface='publicURL')
            cls.designate = openstack_utils.get_designate_session_client(
                version=1,
                auth_url=keystone_ep,
                username="admin",
                password="openstack",
                tenant_name="admin",
                endpoint=designate_ep)
            cls.zones_list = cls.designate.domains.list
            cls.zones_delete = cls.designate.domains.delete
