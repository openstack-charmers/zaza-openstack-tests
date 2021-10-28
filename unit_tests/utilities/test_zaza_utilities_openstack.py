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

import copy
import datetime
import io
import mock
import subprocess
import sys
import unittest
import tenacity

import unit_tests.utils as ut_utils
from zaza.openstack.utilities import openstack as openstack_utils
from zaza.openstack.utilities import exceptions
from zaza.utilities.maas import LinkMode, MachineInterfaceMac


class TestOpenStackUtils(ut_utils.BaseTestCase):

    def setUp(self):
        super(TestOpenStackUtils, self).setUp()
        self.port_name = "port_name"
        self.net_uuid = "net_uuid"
        self.project_id = "project_uuid"
        self.ext_net = "ext_net"
        self.private_net = "private_net"
        self.port = {
            "port": {"id": "port_id",
                     "name": self.port_name,
                     "network_id": self.net_uuid}}
        self.ports = {"ports": [self.port["port"]]}
        self.floatingip = {
            "floatingip": {"id": "floatingip_id",
                           "floating_network_id": self.net_uuid,
                           "port_id": "port_id"}}
        self.floatingips = {"floatingips": [self.floatingip["floatingip"]]}
        self.address_scope_name = "address_scope_name"
        self.address_scope = {
            "address_scope": {"id": "address_scope_id",
                              "name": self.address_scope_name,
                              "shared": True,
                              "ip_version": 4,
                              "tenant_id": self.project_id}}
        self.address_scopes = {
            "address_scopes": [self.address_scope["address_scope"]]}

        self.network = {
            "network": {"id": "network_id",
                        "name": self.ext_net,
                        "router:external": True,
                        "shared": False,
                        "tenant_id": self.project_id,
                        "provider:physical_network": "physnet1",
                        "provider:network_type": "flat"}}

        self.networks = {
            "networks": [self.network["network"]]}

        self.agents = {
            "agents": [
                {
                    'id': '7f3afd5b-ff6d-4df3-be0e-3d9651e71873',
                    'binary': 'neutron-bgp-dragent',
                }]}

        self.bgp_speakers = {
            "bgp_speakers": [
                {
                    'id': '07a0798d-c29c-4a92-8fcb-c1ec56934729',
                }]}

        self.neutronclient = mock.MagicMock()
        self.neutronclient.list_ports.return_value = self.ports
        self.neutronclient.create_port.return_value = self.port

        self.neutronclient.list_floatingips.return_value = self.floatingips
        self.neutronclient.create_floatingip.return_value = self.floatingip

        self.neutronclient.list_address_scopes.return_value = (
            self.address_scopes)
        self.neutronclient.create_address_scope.return_value = (
            self.address_scope)

        self.neutronclient.list_networks.return_value = self.networks
        self.neutronclient.create_network.return_value = self.network

        self.neutronclient.list_agents.return_value = self.agents
        self.neutronclient.list_bgp_speaker_on_dragent.return_value = \
            self.bgp_speakers

    def test_create_port(self):
        self.patch_object(openstack_utils, "get_net_uuid")
        self.get_net_uuid.return_value = self.net_uuid

        # Already exists
        port = openstack_utils.create_port(
            self.neutronclient, self.port_name, self.private_net)
        self.assertEqual(port, self.port["port"])
        self.neutronclient.create_port.assert_not_called()

        # Does not yet exist
        self.neutronclient.list_ports.return_value = {"ports": []}
        self.port["port"].pop("id")
        port = openstack_utils.create_port(
            self.neutronclient, self.port_name, self.private_net)
        self.assertEqual(port, self.port["port"])
        self.neutronclient.create_port.assert_called_once_with(self.port)

    def test_create_floating_ip(self):
        self.patch_object(openstack_utils, "get_net_uuid")
        self.get_net_uuid.return_value = self.net_uuid

        # Already exists
        floatingip = openstack_utils.create_floating_ip(
            self.neutronclient, self.ext_net, port=self.port["port"])
        self.assertEqual(floatingip, self.floatingip["floatingip"])
        self.neutronclient.create_floatingip.assert_not_called()

        # Does not yet exist
        self.neutronclient.list_floatingips.return_value = {"floatingips": []}
        self.floatingip["floatingip"].pop("id")
        floatingip = openstack_utils.create_floating_ip(
            self.neutronclient, self.private_net, port=self.port["port"])
        self.assertEqual(floatingip, self.floatingip["floatingip"])
        self.neutronclient.create_floatingip.assert_called_once_with(
            self.floatingip)

    def test_create_address_scope(self):
        self.patch_object(openstack_utils, "get_net_uuid")
        self.get_net_uuid.return_value = self.net_uuid

        # Already exists
        address_scope = openstack_utils.create_address_scope(
            self.neutronclient, self.project_id, self.address_scope_name)
        self.assertEqual(address_scope, self.address_scope["address_scope"])
        self.neutronclient.create_address_scope.assert_not_called()

        # Does not yet exist
        self.neutronclient.list_address_scopes.return_value = {
            "address_scopes": []}
        address_scope_msg = copy.deepcopy(self.address_scope)
        address_scope_msg["address_scope"].pop("id")
        address_scope = openstack_utils.create_address_scope(
            self.neutronclient, self.project_id, self.address_scope_name)
        self.assertEqual(address_scope, self.address_scope["address_scope"])
        self.neutronclient.create_address_scope.assert_called_once_with(
            address_scope_msg)

    def test_create_provider_network(self):
        self.patch_object(openstack_utils, "get_net_uuid")
        self.get_net_uuid.return_value = self.net_uuid

        # Already exists
        network = openstack_utils.create_provider_network(
            self.neutronclient, self.project_id)
        self.assertEqual(network, self.network["network"])
        self.neutronclient.create_network.assert_not_called()

        # Does not yet exist
        self.neutronclient.list_networks.return_value = {
            "networks": []}
        network_msg = copy.deepcopy(self.network)
        network_msg["network"].pop("id")
        network = openstack_utils.create_provider_network(
            self.neutronclient, self.project_id)
        self.assertEqual(network, self.network["network"])
        self.neutronclient.create_network.assert_called_once_with(
            network_msg)

    def test_get_keystone_scope(self):
        self.patch_object(openstack_utils, "get_current_os_versions")

        # <= Liberty
        self.get_current_os_versions.return_value = {"keystone": "liberty"}
        self.assertEqual(openstack_utils.get_keystone_scope(), "DOMAIN")
        # > Liberty
        self.get_current_os_versions.return_value = {"keystone": "mitaka"}
        self.assertEqual(openstack_utils.get_keystone_scope(), "PROJECT")

    def _test_get_overcloud_auth(self, tls_relation=False, ssl_cert=False,
                                 v2_api=False):
        self.patch_object(openstack_utils.model, 'get_relation_id')
        self.patch_object(openstack_utils, 'get_application_config_option')
        self.patch_object(openstack_utils, 'get_keystone_ip')
        self.patch_object(openstack_utils, "get_current_os_versions")
        self.patch_object(openstack_utils, "get_remote_ca_cert_file")
        self.patch_object(openstack_utils.juju_utils, 'leader_get')
        if tls_relation:
            self.patch_object(openstack_utils.model, "scp_from_unit")
            self.patch_object(openstack_utils.model, "get_first_unit_name")
            self.get_first_unit_name.return_value = "keystone/4"
            self.patch_object(openstack_utils.os, "chmod")
            self.patch_object(openstack_utils.os, "path")
            self.path.return_value = True

        self.get_keystone_ip.return_value = '127.0.0.1'
        self.get_relation_id.return_value = None
        self.get_application_config_option.return_value = None
        self.leader_get.return_value = 'openstack'
        self.get_remote_ca_cert_file.return_value = None
        if tls_relation or ssl_cert:
            port = 35357
            transport = 'https'
            if tls_relation:
                self.get_relation_id.return_value = 'tls-certificates:1'
            if ssl_cert:
                self.get_application_config_option.side_effect = [
                    'FAKECRTDATA',
                    None,
                ]
        else:
            port = 5000
            transport = 'http'
        if v2_api:
            str_api = 'v2.0'
            self.get_current_os_versions.return_value = {"keystone": "mitaka"}
            expect = {
                'OS_AUTH_URL': '{}://127.0.0.1:{}/{}'
                               .format(transport, port, str_api),
                'OS_TENANT_NAME': 'admin',
                'OS_USERNAME': 'admin',
                'OS_PASSWORD': 'openstack',
                'OS_REGION_NAME': 'RegionOne',
                'API_VERSION': 2,
            }
        else:
            str_api = 'v3'
            self.get_current_os_versions.return_value = {"keystone": "queens"}
            expect = {
                'OS_AUTH_URL': '{}://127.0.0.1:{}/{}'
                               .format(transport, port, str_api),
                'OS_USERNAME': 'admin',
                'OS_PASSWORD': 'openstack',
                'OS_REGION_NAME': 'RegionOne',
                'OS_DOMAIN_NAME': 'admin_domain',
                'OS_USER_DOMAIN_NAME': 'admin_domain',
                'OS_PROJECT_NAME': 'admin',
                'OS_PROJECT_DOMAIN_NAME': 'admin_domain',
                'API_VERSION': 3,
            }
        if tls_relation:
            self.get_remote_ca_cert_file.return_value = '/tmp/a.cert'
            expect['OS_CACERT'] = '/tmp/a.cert'
        self.assertEqual(openstack_utils.get_overcloud_auth(),
                         expect)

    def test_get_overcloud_auth(self):
        self._test_get_overcloud_auth()

    def test_get_overcloud_auth_v2(self):
        self._test_get_overcloud_auth(v2_api=True)

    def test_get_overcloud_auth_tls_relation(self):
        self._test_get_overcloud_auth(tls_relation=True)

    def test_get_overcloud_auth_tls_relation_v2(self):
        self._test_get_overcloud_auth(v2_api=True, tls_relation=True)

    def test_get_overcloud_auth_ssl_cert(self):
        self._test_get_overcloud_auth(ssl_cert=True)

    def test_get_overcloud_auth_ssl_cert_v2(self):
        self._test_get_overcloud_auth(v2_api=True, ssl_cert=True)

    def test_get_overcloud_keystone_session(self):
        self.patch_object(openstack_utils, "get_keystone_session")
        self.patch_object(openstack_utils, "get_keystone_scope")
        self.patch_object(openstack_utils, "get_overcloud_auth")
        _auth = "FAKE_AUTH"
        _scope = "PROJECT"
        self.get_keystone_scope.return_value = _scope
        self.get_overcloud_auth.return_value = _auth

        openstack_utils.get_overcloud_keystone_session()
        self.get_keystone_session.assert_called_once_with(_auth, scope=_scope,
                                                          verify=None)

    def test_get_undercloud_keystone_session(self):
        self.patch_object(openstack_utils, "get_keystone_session")
        self.patch_object(openstack_utils, "get_undercloud_auth")
        _auth = "FAKE_AUTH"
        self.get_undercloud_auth.return_value = _auth

        openstack_utils.get_undercloud_keystone_session()
        self.get_keystone_session.assert_called_once_with(_auth, verify=None)

    def test_get_nova_session_client(self):
        session_mock = mock.MagicMock()
        self.patch_object(openstack_utils.novaclient_client, "Client")
        openstack_utils.get_nova_session_client(session_mock)
        self.Client.assert_called_once_with(2, session=session_mock)
        self.Client.reset_mock()
        openstack_utils.get_nova_session_client(session_mock, version=2.56)
        self.Client.assert_called_once_with(2.56, session=session_mock)

    def test_get_urllib_opener(self):
        self.patch_object(openstack_utils.urllib.request, "ProxyHandler")
        self.patch_object(openstack_utils.urllib.request, "HTTPHandler")
        self.patch_object(openstack_utils.urllib.request, "build_opener")
        self.patch_object(openstack_utils.deployment_env,
                          "get_deployment_context",
                          return_value=dict(TEST_HTTP_PROXY=None))
        HTTPHandler_mock = mock.MagicMock()
        self.HTTPHandler.return_value = HTTPHandler_mock
        openstack_utils.get_urllib_opener()
        self.build_opener.assert_called_once_with(HTTPHandler_mock)
        self.HTTPHandler.assert_called_once_with()

    def test_get_urllib_opener_proxy(self):
        self.patch_object(openstack_utils.urllib.request, "ProxyHandler")
        self.patch_object(openstack_utils.urllib.request, "HTTPHandler")
        self.patch_object(openstack_utils.urllib.request, "build_opener")
        self.patch_object(openstack_utils.deployment_env,
                          "get_deployment_context",
                          return_value=dict(TEST_HTTP_PROXY='http://squidy'))
        ProxyHandler_mock = mock.MagicMock()
        self.ProxyHandler.return_value = ProxyHandler_mock
        openstack_utils.get_urllib_opener()
        self.build_opener.assert_called_once_with(ProxyHandler_mock)
        self.ProxyHandler.assert_called_once_with({'http': 'http://squidy'})

    def test_get_images_by_name(self):
        image_mock1 = mock.MagicMock()
        image_mock1.name = 'bob'
        image_mock2 = mock.MagicMock()
        image_mock2.name = 'bill'
        glance_client = mock.MagicMock()
        glance_client.images.list.return_value = [image_mock1, image_mock2]
        self.assertEqual(
            openstack_utils.get_images_by_name(glance_client, 'bob'),
            [image_mock1])
        self.assertEqual(
            openstack_utils.get_images_by_name(glance_client, 'frank'),
            [])

    def test_find_cirros_image(self):
        urllib_opener_mock = mock.MagicMock()
        self.patch_object(openstack_utils, "get_urllib_opener")
        self.get_urllib_opener.return_value = urllib_opener_mock
        urllib_opener_mock.open().read.return_value = b'12'
        self.assertEqual(
            openstack_utils.find_cirros_image('aarch64'),
            'http://download.cirros-cloud.net/12/cirros-12-aarch64-disk.img')

    def test_find_ubuntu_image(self):
        self.assertEqual(
            openstack_utils.find_ubuntu_image('bionic', 'aarch64'),
            ('http://cloud-images.ubuntu.com/bionic/current/'
             'bionic-server-cloudimg-aarch64.img'))

    def test_download_image(self):
        urllib_opener_mock = mock.MagicMock()
        self.patch_object(openstack_utils, "get_urllib_opener")
        self.get_urllib_opener.return_value = urllib_opener_mock
        self.patch_object(openstack_utils.urllib.request, "install_opener")
        self.patch_object(openstack_utils.urllib.request, "urlretrieve")
        openstack_utils.download_image('http://cirros/c.img', '/tmp/c1.img')
        self.install_opener.assert_called_once_with(urllib_opener_mock)
        self.urlretrieve.assert_called_once_with(
            'http://cirros/c.img', '/tmp/c1.img')

    def test__resource_reaches_status(self):
        resource_mock = mock.MagicMock()
        resource_mock.get.return_value = mock.MagicMock(status='available')
        openstack_utils._resource_reaches_status(resource_mock, 'e01df65a')

    def test__resource_reaches_status_fail(self):
        resource_mock = mock.MagicMock()
        resource_mock.get.return_value = mock.MagicMock(status='unavailable')
        with self.assertRaises(AssertionError):
            openstack_utils._resource_reaches_status(
                resource_mock,
                'e01df65a')

    def test__resource_reaches_status_bespoke(self):
        client_mock = mock.MagicMock()
        resource_mock = mock.MagicMock()
        resource_mock.special_status = 'readyish'
        client_mock.get.return_value = resource_mock
        openstack_utils._resource_reaches_status(
            client_mock,
            'e01df65a',
            'readyish',
            resource_attribute='special_status')

    def test__resource_reaches_status_bespoke_fail(self):
        resource_mock = mock.MagicMock()
        resource_mock.get.return_value = mock.MagicMock(status='available')
        with self.assertRaises(AssertionError):
            openstack_utils._resource_reaches_status(
                resource_mock,
                'e01df65a',
                'readyish')

    def test_resource_reaches_status(self):
        self.patch_object(openstack_utils, "_resource_reaches_status")
        self._resource_reaches_status.return_value = True
        openstack_utils._resource_reaches_status('resource', 'e01df65a')
        self._resource_reaches_status.assert_called_once_with(
            'resource',
            'e01df65a')

    def test_resource_reaches_status_custom_retry(self):
        self.patch_object(openstack_utils, "_resource_reaches_status")
        self._resource_reaches_status.return_value = True
        openstack_utils._resource_reaches_status(
            'resource',
            'e01df65a',
            wait_exponential_multiplier=2,
            wait_iteration_max_time=20,
            stop_after_attempt=2)
        self._resource_reaches_status.assert_called_once_with(
            'resource',
            'e01df65a',
            stop_after_attempt=2,
            wait_exponential_multiplier=2,
            wait_iteration_max_time=20)

    def test__resource_removed(self):
        resource_mock = mock.MagicMock()
        resource_mock.list.return_value = [mock.MagicMock(id='ba8204b0')]
        openstack_utils._resource_removed(resource_mock, 'e01df65a')

    def test__resource_removed_fail(self):
        resource_mock = mock.MagicMock()
        resource_mock.list.return_value = [mock.MagicMock(id='e01df65a')]
        with self.assertRaises(AssertionError):
            openstack_utils._resource_removed(resource_mock, 'e01df65a')

    def test_resource_removed(self):
        self.patch_object(openstack_utils, "_resource_removed")
        self._resource_removed.return_value = True
        openstack_utils.resource_removed('resource', 'e01df65a')
        self._resource_removed.assert_called_once_with(
            'resource',
            'e01df65a',
            'resource')

    def test_resource_removed_custom_retry(self):
        self.patch_object(openstack_utils, "_resource_removed")

        def _retryer(f, arg1, arg2, arg3):
            f(arg1, arg2, arg3)
        self.patch_object(
            openstack_utils.tenacity,
            "Retrying",
            return_value=_retryer)
        saa_mock = mock.MagicMock()
        self.patch_object(
            openstack_utils.tenacity,
            "stop_after_attempt",
            return_value=saa_mock)
        we_mock = mock.MagicMock()
        self.patch_object(
            openstack_utils.tenacity,
            "wait_exponential",
            return_value=we_mock)
        self._resource_removed.return_value = True
        openstack_utils.resource_removed(
            'resource',
            'e01df65a',
            wait_exponential_multiplier=2,
            wait_iteration_max_time=20,
            stop_after_attempt=2)
        self._resource_removed.assert_called_once_with(
            'resource',
            'e01df65a',
            'resource')
        self.Retrying.assert_called_once_with(
            wait=we_mock,
            reraise=True,
            stop=saa_mock)

    def test_delete_resource(self):
        resource_mock = mock.MagicMock()
        self.patch_object(openstack_utils, "resource_removed")
        openstack_utils.delete_resource(resource_mock, 'e01df65a')
        resource_mock.delete.assert_called_once_with('e01df65a')
        self.resource_removed.assert_called_once_with(
            resource_mock,
            'e01df65a',
            'resource')

    def test_delete_image(self):
        self.patch_object(openstack_utils, "delete_resource")
        glance_mock = mock.MagicMock()
        openstack_utils.delete_image(glance_mock, 'b46c2d83')
        self.delete_resource.assert_called_once_with(
            glance_mock.images,
            'b46c2d83',
            msg="glance image")

    def test_upload_image_to_glance(self):
        self.patch_object(openstack_utils, "resource_reaches_status")
        glance_mock = mock.MagicMock()
        image_mock = mock.MagicMock(id='9d1125af')
        glance_mock.images.create.return_value = image_mock
        m = mock.mock_open()
        with mock.patch(
            'zaza.openstack.utilities.openstack.open', m, create=False
        ) as f:
            openstack_utils.upload_image_to_glance(
                glance_mock,
                '/tmp/im1.img',
                'bob')
            glance_mock.images.create.assert_called_once_with(
                name='bob',
                disk_format='qcow2',
                visibility='public',
                container_format='bare')
            glance_mock.images.upload.assert_called_once_with(
                '9d1125af',
                f(),
                backend=None)
            self.resource_reaches_status.assert_called_once_with(
                glance_mock.images,
                '9d1125af',
                expected_status='active',
                msg='Image status wait')

    def test_create_image_use_tempdir(self):
        glance_mock = mock.MagicMock()
        self.patch_object(openstack_utils.os.path, "exists")
        self.patch_object(openstack_utils, "download_image")
        self.patch_object(openstack_utils, "upload_image_to_glance")
        self.patch_object(openstack_utils.tempfile, "gettempdir")
        self.gettempdir.return_value = "wibbly"
        openstack_utils.create_image(
            glance_mock,
            'http://cirros/c.img',
            'bob')
        self.exists.return_value = False
        self.download_image.assert_called_once_with(
            'http://cirros/c.img',
            'wibbly/c.img')
        self.upload_image_to_glance.assert_called_once_with(
            glance_mock,
            'wibbly/c.img',
            'bob',
            backend=None,
            disk_format='qcow2',
            visibility='public',
            container_format='bare',
            force_import=False)

    def test_create_image_pass_directory(self):
        glance_mock = mock.MagicMock()
        self.patch_object(openstack_utils.os.path, "exists")
        self.patch_object(openstack_utils, "download_image")
        self.patch_object(openstack_utils, "upload_image_to_glance")
        self.patch_object(openstack_utils.tempfile, "gettempdir")
        openstack_utils.create_image(
            glance_mock,
            'http://cirros/c.img',
            'bob',
            'tests')
        self.exists.return_value = False
        self.download_image.assert_called_once_with(
            'http://cirros/c.img',
            'tests/c.img')
        self.upload_image_to_glance.assert_called_once_with(
            glance_mock,
            'tests/c.img',
            'bob',
            backend=None,
            disk_format='qcow2',
            visibility='public',
            container_format='bare',
            force_import=False)
        self.gettempdir.assert_not_called()

    def test_create_ssh_key(self):
        nova_mock = mock.MagicMock()
        nova_mock.keypairs.findall.return_value = []
        openstack_utils.create_ssh_key(
            nova_mock,
            'mykeys')
        nova_mock.keypairs.create.assert_called_once_with(name='mykeys')

    def test_create_ssh_key_existing(self):
        nova_mock = mock.MagicMock()
        nova_mock.keypairs.findall.return_value = ['akey']
        self.assertEqual(
            openstack_utils.create_ssh_key(
                nova_mock,
                'mykeys'),
            'akey')
        self.assertFalse(nova_mock.keypairs.create.called)

    def test_create_ssh_key_existing_replace(self):
        nova_mock = mock.MagicMock()
        nova_mock.keypairs.findall.return_value = ['key1']
        openstack_utils.create_ssh_key(
            nova_mock,
            'mykeys',
            replace=True),
        nova_mock.keypairs.delete.assert_called_once_with('key1')
        nova_mock.keypairs.create.assert_called_once_with(name='mykeys')

    def test_get_private_key_file(self):
        self.patch_object(openstack_utils.deployment_env, 'get_tmpdir',
                          return_value='/tmp/zaza-model1')
        self.assertEqual(
            openstack_utils.get_private_key_file('mykeys'),
            '/tmp/zaza-model1/id_rsa_mykeys')

    def test_write_private_key(self):
        self.patch_object(openstack_utils.deployment_env, 'get_tmpdir',
                          return_value='/tmp/zaza-model1')
        m = mock.mock_open()
        with mock.patch(
            'zaza.openstack.utilities.openstack.open', m, create=False
        ):
            openstack_utils.write_private_key('mykeys', 'keycontents')
        m.assert_called_once_with('/tmp/zaza-model1/id_rsa_mykeys', 'w')
        handle = m()
        handle.write.assert_called_once_with('keycontents')

    def test_get_private_key(self):
        self.patch_object(openstack_utils.deployment_env, 'get_tmpdir',
                          return_value='/tmp/zaza-model1')
        self.patch_object(openstack_utils.os.path, "isfile",
                          return_value=True)
        m = mock.mock_open(read_data='myprivkey')
        with mock.patch(
            'zaza.openstack.utilities.openstack.open', m, create=True
        ):
            self.assertEqual(
                openstack_utils.get_private_key('mykeys'),
                'myprivkey')

    def test_get_private_key_file_missing(self):
        self.patch_object(openstack_utils.deployment_env, 'get_tmpdir',
                          return_value='/tmp/zaza-model1')
        self.patch_object(openstack_utils.os.path, "isfile",
                          return_value=False)
        self.assertIsNone(openstack_utils.get_private_key('mykeys'))

    def test_get_public_key(self):
        key_mock = mock.MagicMock(public_key='mypubkey')
        nova_mock = mock.MagicMock()
        nova_mock.keypairs.findall.return_value = [key_mock]
        self.assertEqual(
            openstack_utils.get_public_key(nova_mock, 'mykeys'),
            'mypubkey')

    def test_valid_key_exists(self):
        nova_mock = mock.MagicMock()
        self.patch_object(openstack_utils, 'get_public_key',
                          return_value='pubkey')
        self.patch_object(openstack_utils, 'get_private_key',
                          return_value='privkey')
        self.patch_object(openstack_utils.cert, 'is_keys_valid',
                          return_value=True)
        self.assertTrue(openstack_utils.valid_key_exists(nova_mock, 'mykeys'))
        self.get_public_key.assert_called_once_with(nova_mock, 'mykeys')
        self.get_private_key.assert_called_once_with('mykeys')
        self.is_keys_valid.assert_called_once_with('pubkey', 'privkey')

    def test_valid_key_exists_missing(self):
        nova_mock = mock.MagicMock()
        self.patch_object(openstack_utils, 'get_public_key',
                          return_value='pubkey')
        self.patch_object(openstack_utils, 'get_private_key',
                          return_value=None)
        self.patch_object(openstack_utils.cert, 'is_keys_valid',
                          return_value=True)
        self.assertFalse(openstack_utils.valid_key_exists(nova_mock, 'mykeys'))
        self.get_public_key.assert_called_once_with(nova_mock, 'mykeys')
        self.get_private_key.assert_called_once_with('mykeys')

    def test_get_ports_from_device_id(self):
        port_mock = {'device_id': 'dev1'}
        neutron_mock = mock.MagicMock()
        neutron_mock.list_ports.return_value = {
            'ports': [port_mock]}
        self.assertEqual(
            openstack_utils.get_ports_from_device_id(
                neutron_mock,
                'dev1'),
            [port_mock])

    def test_get_ports_from_device_id_no_match(self):
        port_mock = {'device_id': 'dev2'}
        neutron_mock = mock.MagicMock()
        neutron_mock.list_ports.return_value = {
            'ports': [port_mock]}
        self.assertEqual(
            openstack_utils.get_ports_from_device_id(
                neutron_mock,
                'dev1'),
            [])

    def test_ping_response(self):
        self.patch_object(openstack_utils.subprocess, 'run')
        openstack_utils.ping_response('10.0.0.10')
        self.run.assert_called_once_with(
            ['ping', '-c', '1', '-W', '1', '10.0.0.10'], check=True,
            stdout=mock.ANY, stderr=mock.ANY)

    def test_ping_response_fail(self):
        openstack_utils.ping_response.retry.wait = \
            tenacity.wait_none()
        self.patch_object(openstack_utils.subprocess, 'run')
        self.run.side_effect = subprocess.CalledProcessError(returncode=42,
                                                             cmd='mycmd')
        with self.assertRaises(subprocess.CalledProcessError):
            openstack_utils.ping_response('10.0.0.10')

    def test_ssh_test(self):
        paramiko_mock = mock.MagicMock()
        self.patch_object(openstack_utils.paramiko, 'SSHClient',
                          return_value=paramiko_mock)
        self.patch_object(openstack_utils.paramiko, 'AutoAddPolicy',
                          return_value='some_policy')
        stdout = io.StringIO("myvm")

        paramiko_mock.exec_command.return_value = ('stdin', stdout, 'stderr')
        openstack_utils.ssh_test(
            'bob',
            '10.0.0.10',
            'myvm',
            password='reallyhardpassord')
        paramiko_mock.connect.assert_called_once_with(
            '10.0.0.10',
            password='reallyhardpassord',
            username='bob')

    def test_ssh_command(self):
        paramiko_mock = mock.MagicMock()
        self.patch_object(openstack_utils.paramiko, 'SSHClient',
                          return_value=paramiko_mock)
        self.patch_object(openstack_utils.paramiko, 'AutoAddPolicy',
                          return_value='some_policy')
        stdout = io.StringIO("myvm")

        paramiko_mock.exec_command.return_value = ('stdin', stdout, 'stderr')

        def verifier(_stdin, stdout, _stderr):
            self.assertEqual('myvm', stdout.readlines()[0].strip())

        openstack_utils.ssh_command(
            'bob',
            '10.0.0.10',
            'myvm',
            'uname -n',
            password='reallyhardpassord',
            verify=verifier)
        paramiko_mock.connect.assert_called_once_with(
            '10.0.0.10',
            password='reallyhardpassord',
            username='bob')

    def test_ssh_test_wrong_server(self):
        paramiko_mock = mock.MagicMock()
        self.patch_object(openstack_utils.paramiko, 'SSHClient',
                          return_value=paramiko_mock)
        self.patch_object(openstack_utils.paramiko, 'AutoAddPolicy',
                          return_value='some_policy')
        stdout = io.StringIO("anothervm")

        paramiko_mock.exec_command.return_value = ('stdin', stdout, 'stderr')
        with self.assertRaises(exceptions.SSHFailed):
            openstack_utils.ssh_test(
                'bob',
                '10.0.0.10',
                'myvm',
                password='reallyhardpassord',
                retry=False)
        paramiko_mock.connect.assert_called_once_with(
            '10.0.0.10',
            password='reallyhardpassord',
            username='bob')

    def test_ssh_test_key_auth(self):
        paramiko_mock = mock.MagicMock()
        self.patch_object(openstack_utils.paramiko, 'SSHClient',
                          return_value=paramiko_mock)
        self.patch_object(openstack_utils.paramiko, 'AutoAddPolicy',
                          return_value='some_policy')
        self.patch_object(openstack_utils.paramiko.RSAKey, 'from_private_key',
                          return_value='akey')
        stdout = io.StringIO("myvm")

        paramiko_mock.exec_command.return_value = ('stdin', stdout, 'stderr')
        openstack_utils.ssh_test(
            'bob',
            '10.0.0.10',
            'myvm',
            privkey='myprivkey')
        paramiko_mock.connect.assert_called_once_with(
            '10.0.0.10',
            password=None,
            pkey='akey',
            username='bob')

    def test_neutron_agent_appears(self):
        self.assertEqual(
            openstack_utils.neutron_agent_appears(self.neutronclient,
                                                  'neutron-bgp-dragent'),
            self.agents)

    def test_neutron_agent_appears_not(self):
        _neutronclient = copy.deepcopy(self.neutronclient)
        _neutronclient.list_agents.return_value = {'agents': []}
        openstack_utils.neutron_agent_appears.retry.stop = \
            tenacity.stop_after_attempt(1)
        with self.assertRaises(exceptions.NeutronAgentMissing):
            openstack_utils.neutron_agent_appears(_neutronclient,
                                                  'non-existent')

    def test_neutron_bgp_speaker_appears_on_agent(self):
        openstack_utils.neutron_bgp_speaker_appears_on_agent.retry.stop = \
            tenacity.stop_after_attempt(1)
        self.assertEqual(
            openstack_utils.neutron_bgp_speaker_appears_on_agent(
                self.neutronclient, 'FAKE_AGENT_ID'),
            self.bgp_speakers)

    def test_neutron_bgp_speaker_appears_not_on_agent(self):
        _neutronclient = copy.deepcopy(self.neutronclient)
        _neutronclient.list_bgp_speaker_on_dragent.return_value = {
            'bgp_speakers': []}
        openstack_utils.neutron_bgp_speaker_appears_on_agent.retry.stop = \
            tenacity.stop_after_attempt(1)
        with self.assertRaises(exceptions.NeutronBGPSpeakerMissing):
            openstack_utils.neutron_bgp_speaker_appears_on_agent(
                _neutronclient, 'FAKE_AGENT_ID')

    def test_get_current_openstack_release_pair(self):
        self.patch(
            'zaza.openstack.utilities.openstack.get_current_os_versions',
            new_callable=mock.MagicMock(),
            name='_get_os_version'
        )
        self.patch(
            'zaza.utilities.juju.get_machines_for_application',
            new_callable=mock.MagicMock(),
            name='_get_machines'
        )
        self.patch(
            'zaza.utilities.juju.get_machine_series',
            new_callable=mock.MagicMock(),
            name='_get_machine_series'
        )

        _machine = mock.MagicMock()

        # No machine returned
        self._get_machines.return_value = []
        with self.assertRaises(exceptions.ApplicationNotFound):
            openstack_utils.get_current_os_release_pair()
        self._get_machines.side_effect = None

        # No series returned
        self._get_machines.return_value = [_machine]
        self._get_machine_series.return_value = None
        with self.assertRaises(exceptions.SeriesNotFound):
            openstack_utils.get_current_os_release_pair()

        # No OS Version returned
        self._get_machine_series.return_value = 'xenial'
        self._get_os_version.return_value = {}
        with self.assertRaises(exceptions.OSVersionNotFound):
            openstack_utils.get_current_os_release_pair()

        # Normal scenario, argument passed
        self._get_os_version.return_value = {'keystone': 'mitaka'}
        expected = 'xenial_mitaka'
        result = openstack_utils.get_current_os_release_pair('keystone')
        self.assertEqual(expected, result)

        # Normal scenario, default value used
        self._get_os_version.return_value = {'keystone': 'mitaka'}
        expected = 'xenial_mitaka'
        result = openstack_utils.get_current_os_release_pair()
        self.assertEqual(expected, result)

    def test_get_current_os_versions(self):
        self.patch_object(openstack_utils, "get_openstack_release")
        self.patch_object(openstack_utils.generic_utils, "get_pkg_version")

        # Pre-Wallaby scenario where openstack-release package isn't installed
        self.get_openstack_release.return_value = None
        self.get_pkg_version.return_value = '18.0.0'
        expected = {'keystone': 'victoria'}
        result = openstack_utils.get_current_os_versions('keystone')
        self.assertEqual(expected, result)

        # Wallaby+ scenario where openstack-release package is installed
        self.get_openstack_release.return_value = 'wallaby'
        expected = {'keystone': 'wallaby'}
        result = openstack_utils.get_current_os_versions('keystone')
        self.assertEqual(expected, result)

    def test_get_os_release(self):
        self.patch(
            'zaza.openstack.utilities.openstack.get_current_os_release_pair',
            new_callable=mock.MagicMock(),
            name='_get_os_rel_pair'
        )

        # Bad release pair
        release_pair = 'bad'
        with self.assertRaises(exceptions.ReleasePairNotFound):
            openstack_utils.get_os_release(release_pair)

        # Normal scenario
        expected = 4
        result = openstack_utils.get_os_release('xenial_mitaka')
        self.assertEqual(expected, result)

        # Normal scenario with current release pair
        self._get_os_rel_pair.return_value = 'xenial_mitaka'
        expected = 4
        result = openstack_utils.get_os_release()
        self.assertEqual(expected, result)

        # We can compare releases xenial_queens > xenial_mitaka
        xenial_queens = openstack_utils.get_os_release('xenial_queens')
        xenial_mitaka = openstack_utils.get_os_release('xenial_mitaka')
        release_comp = xenial_queens > xenial_mitaka
        self.assertTrue(release_comp)

        # Check specifying an application
        self._get_os_rel_pair.reset_mock()
        self._get_os_rel_pair.return_value = 'xenial_mitaka'
        expected = 4
        result = openstack_utils.get_os_release(application='myapp')
        self.assertEqual(expected, result)
        self._get_os_rel_pair.assert_called_once_with(application='myapp')

    def test_get_keystone_api_version(self):
        self.patch_object(openstack_utils, "get_current_os_versions")
        self.patch_object(openstack_utils, "get_application_config_option")

        self.get_current_os_versions.return_value = {"keystone": "liberty"}
        self.get_application_config_option.return_value = None
        self.assertEqual(openstack_utils.get_keystone_api_version(), 2)

        self.get_application_config_option.return_value = "3"
        self.assertEqual(openstack_utils.get_keystone_api_version(), 3)

        self.get_current_os_versions.return_value = {"keystone": "queens"}
        self.get_application_config_option.return_value = None
        self.assertEqual(openstack_utils.get_keystone_api_version(), 3)

    def test_get_openstack_release(self):
        self.patch_object(openstack_utils.model, "get_units")
        self.patch_object(openstack_utils.juju_utils, "remote_run")

        # Test pre-Wallaby behavior where openstack-release pkg isn't installed
        self.get_units.return_value = []
        self.remote_run.return_value = "OPENSTACK_CODENAME=wallaby "

        # Test Wallaby+ behavior where openstack-release package is installed
        unit1 = mock.MagicMock()
        unit1.entity_id = 1
        self.get_units.return_value = [unit1]
        self.remote_run.return_value = "OPENSTACK_CODENAME=wallaby "

        result = openstack_utils.get_openstack_release("application", "model")
        self.assertEqual(result, "wallaby")

    def test_get_project_id(self):
        # No domain
        self.patch_object(openstack_utils, "get_keystone_api_version")
        self.get_keystone_api_version.return_value = 2
        ksclient = mock.MagicMock()
        project_id = "project-uuid"
        project_name = "myproject"
        project = mock.MagicMock()
        project._info = {"name": project_name, "id": project_id}
        ksclient.projects.list.return_value = [project]
        self.assertEqual(
            openstack_utils.get_project_id(ksclient, project_name),
            project_id)
        ksclient.projects.list.assert_called_once_with(domain=None)
        ksclient.domains.list.assert_not_called()

        # With domain
        ksclient.reset_mock()
        domain_name = "mydomain"
        domain_id = "domain-uuid"
        domain = mock.MagicMock()
        domain.id = domain_id
        ksclient.domains.list.return_value = [domain]
        self.assertEqual(
            openstack_utils.get_project_id(
                ksclient, project_name, domain_name=domain_name), project_id)
        ksclient.domains.list.assert_called_once_with(name=domain_name)
        ksclient.projects.list.assert_called_once_with(domain=domain_id)

    def test_wait_for_server_migration(self):
        openstack_utils.wait_for_server_migration.retry.stop = \
            tenacity.stop_after_attempt(1)
        novaclient = mock.MagicMock()
        servermock = mock.MagicMock()
        setattr(servermock, 'OS-EXT-SRV-ATTR:host', 'newhypervisor')
        servermock.status = 'ACTIVE'
        novaclient.servers.find.return_value = servermock
        # Implicit assertion that exception is not raised.
        openstack_utils.wait_for_server_migration(
            novaclient,
            'myvm',
            'org-hypervisor')

    def test_wait_for_server_migration_fail_no_host_change(self):
        openstack_utils.wait_for_server_migration.retry.stop = \
            tenacity.stop_after_attempt(1)
        novaclient = mock.MagicMock()
        servermock = mock.MagicMock()
        setattr(servermock, 'OS-EXT-SRV-ATTR:host', 'org-hypervisor')
        servermock.status = 'ACTIVE'
        novaclient.servers.find.return_value = servermock
        with self.assertRaises(exceptions.NovaGuestMigrationFailed):
            openstack_utils.wait_for_server_migration(
                novaclient,
                'myvm',
                'org-hypervisor')

    def test_wait_for_server_migration_fail_not_active(self):
        openstack_utils.wait_for_server_migration.retry.stop = \
            tenacity.stop_after_attempt(1)
        novaclient = mock.MagicMock()
        servermock = mock.MagicMock()
        setattr(servermock, 'OS-EXT-SRV-ATTR:host', 'newhypervisor')
        servermock.status = 'NOTACTIVE'
        novaclient.servers.find.return_value = servermock
        with self.assertRaises(exceptions.NovaGuestMigrationFailed):
            openstack_utils.wait_for_server_migration(
                novaclient,
                'myvm',
                'org-hypervisor')

    def test_wait_for_server_update_and_active(self):
        openstack_utils.wait_for_server_migration.retry.stop = \
            tenacity.stop_after_attempt(1)
        novaclient = mock.MagicMock()
        servermock = mock.MagicMock()
        servermock.updated = '2019-03-07T13:41:58Z'
        servermock.status = 'ACTIVE'
        novaclient.servers.find.return_value = servermock
        # Implicit assertion that exception is not raised.
        openstack_utils.wait_for_server_update_and_active(
            novaclient,
            'myvm',
            datetime.datetime.strptime(
                '2019-03-07T13:40:58Z',
                '%Y-%m-%dT%H:%M:%SZ'))

    def test_wait_for_server_update_and_active_fail_no_meeta_update(self):
        openstack_utils.wait_for_server_update_and_active.retry.stop = \
            tenacity.stop_after_attempt(1)
        novaclient = mock.MagicMock()
        servermock = mock.MagicMock()
        servermock.updated = '2019-03-07T13:41:58Z'
        servermock.status = 'ACTIVE'
        novaclient.servers.find.return_value = servermock
        with self.assertRaises(exceptions.NovaGuestRestartFailed):
            openstack_utils.wait_for_server_update_and_active(
                novaclient,
                'myvm',
                datetime.datetime.strptime(
                    '2019-03-07T13:41:58Z',
                    '%Y-%m-%dT%H:%M:%SZ'))

    def test_wait_for_server_update_and_active_fail_not_active(self):
        openstack_utils.wait_for_server_update_and_active.retry.stop = \
            tenacity.stop_after_attempt(1)
        novaclient = mock.MagicMock()
        servermock = mock.MagicMock()
        servermock.updated = '2019-03-07T13:41:58Z'
        servermock.status = 'NOTACTIVE'
        novaclient.servers.find.return_value = servermock
        with self.assertRaises(exceptions.NovaGuestRestartFailed):
            openstack_utils.wait_for_server_update_and_active(
                novaclient,
                'myvm',
                datetime.datetime.strptime(
                    '2019-03-07T13:40:58Z',
                    '%Y-%m-%dT%H:%M:%SZ'))

    def test_enable_all_nova_services(self):
        novaclient = mock.MagicMock()
        svc_mock1 = mock.MagicMock()
        svc_mock1.status = 'disabled'
        svc_mock1.binary = 'nova-compute'
        svc_mock1.host = 'juju-bb659c-zaza-ad7c662d7f1d-13'
        svc_mock2 = mock.MagicMock()
        svc_mock2.status = 'enabled'
        svc_mock2.binary = 'nova-compute'
        svc_mock2.host = 'juju-bb659c-zaza-ad7c662d7f1d-14'
        svc_mock3 = mock.MagicMock()
        svc_mock3.status = 'disabled'
        svc_mock3.binary = 'nova-compute'
        svc_mock3.host = 'juju-bb659c-zaza-ad7c662d7f1d-15'
        novaclient.services.list.return_value = [
            svc_mock1,
            svc_mock2,
            svc_mock3]
        openstack_utils.enable_all_nova_services(novaclient)
        expected_calls = [
            mock.call('juju-bb659c-zaza-ad7c662d7f1d-13', 'nova-compute'),
            mock.call('juju-bb659c-zaza-ad7c662d7f1d-15', 'nova-compute')]
        novaclient.services.enable.assert_has_calls(expected_calls)

    def test_get_hypervisor_for_guest(self):
        novaclient = mock.MagicMock()
        servermock = mock.MagicMock()
        setattr(servermock, 'OS-EXT-SRV-ATTR:host', 'newhypervisor')
        novaclient.servers.find.return_value = servermock
        self.assertEqual(
            openstack_utils.get_hypervisor_for_guest(novaclient, 'vmname'),
            'newhypervisor')

    def test_get_keystone_session(self):
        self.patch_object(openstack_utils, "session")
        self.patch_object(openstack_utils, "v2")
        _auth = mock.MagicMock()
        self.v2.Password.return_value = _auth
        _openrc = {
            "OS_AUTH_URL": "https://keystone:5000",
            "OS_USERNAME": "myuser",
            "OS_PASSWORD": "pass",
            "OS_TENANT_NAME": "tenant",
        }
        openstack_utils.get_keystone_session(_openrc)
        self.session.Session.assert_called_once_with(auth=_auth, verify=None)

    def test_get_keystone_session_tls(self):
        self.patch_object(openstack_utils, "session")
        self.patch_object(openstack_utils, "v2")
        _auth = mock.MagicMock()
        self.v2.Password.return_value = _auth
        _cacert = "/tmp/cacert"
        _openrc = {
            "OS_AUTH_URL": "https://keystone:5000",
            "OS_USERNAME": "myuser",
            "OS_PASSWORD": "pass",
            "OS_TENANT_NAME": "tenant",
            "OS_CACERT": _cacert,
        }
        openstack_utils.get_keystone_session(_openrc)
        self.session.Session.assert_called_once_with(
            auth=_auth, verify=_cacert)

    def test_get_keystone_session_from_relation(self):
        self.patch_object(openstack_utils.juju_utils, "get_relation_from_unit")
        self.patch_object(openstack_utils, "get_overcloud_auth")
        self.patch_object(openstack_utils, "get_keystone_session")
        self.get_relation_from_unit.return_value = {
            'admin_domain_id': '49f9d68db8e843ffa81d0909707ce26a',
            'admin_token': 'MZB6y8zY',
            'api_version': '3',
            'auth_host': '10.5.0.61',
            'auth_port': '35357',
            'auth_protocol': 'http',
            'egress-subnets': '10.5.0.61/32',
            'ingress-address': '10.5.0.61',
            'private-address': '10.5.0.61',
            'service_domain': 'service_domain',
            'service_domain_id': '63dbff248e144c9db7d062d69b659eb7',
            'service_host': '10.5.0.61',
            'service_password': 'gkKr6G7M',
            'service_port': '5000',
            'service_protocol': 'http',
            'service_tenant': 'services',
            'service_tenant_id': 'd3cade6a28ed45438640164fc69f262c',
            'service_username': 's3_swift'}
        self.get_overcloud_auth.return_value = {
            'OS_AUTH_URL': 'http://10.5.0.61:5000/v3',
            'OS_USERNAME': 'admin',
            'OS_PASSWORD': 'cheeW4eing5foovu',
            'OS_REGION_NAME': 'RegionOne',
            'OS_DOMAIN_NAME': 'admin_domain',
            'OS_USER_DOMAIN_NAME': 'admin_domain',
            'OS_PROJECT_NAME': 'admin',
            'OS_PROJECT_DOMAIN_NAME': 'admin_domain',
            'API_VERSION': 3}
        openstack_utils.get_keystone_session_from_relation('swift-proxy')
        self.get_relation_from_unit.assert_called_once_with(
            'swift-proxy',
            'keystone',
            'identity-service',
            model_name=None)
        self.get_keystone_session.assert_called_once_with(
            {
                'OS_AUTH_URL': 'http://10.5.0.61:5000/v3',
                'OS_USERNAME': 's3_swift',
                'OS_PASSWORD': 'gkKr6G7M',
                'OS_REGION_NAME': 'RegionOne',
                'OS_DOMAIN_NAME': 'service_domain',
                'OS_USER_DOMAIN_NAME': 'service_domain',
                'OS_PROJECT_NAME': 'services',
                'OS_TENANT_NAME': 'services',
                'OS_PROJECT_DOMAIN_NAME': 'service_domain',
                'API_VERSION': 3},
            scope='PROJECT',
            verify=None)

    def test_get_keystone_session_from_relation_v2(self):
        self.patch_object(openstack_utils.juju_utils, "get_relation_from_unit")
        self.patch_object(openstack_utils, "get_overcloud_auth")
        self.patch_object(openstack_utils, "get_keystone_session")
        self.get_relation_from_unit.return_value = {
            'admin_token': 'Ry8mN6',
            'api_version': '2',
            'auth_host': '10.5.0.36',
            'auth_port': '35357',
            'auth_protocol': 'http',
            'egress-subnets': '10.5.0.36/32',
            'ingress-address': '10.5.0.36',
            'private-address': '10.5.0.36',
            'service_host': '10.5.0.36',
            'service_password': 'CKGsVg2p',
            'service_port': '5000',
            'service_protocol': 'http',
            'service_tenant': 'services',
            'service_tenant_id': '78b6f62c2aa2',
            'service_username': 's3_swift'}
        self.get_overcloud_auth.return_value = {
            'OS_AUTH_URL': 'http://10.5.0.36:5000/v2.0',
            'OS_TENANT_NAME': 'admin',
            'OS_USERNAME': 'admin',
            'OS_PASSWORD': 'Eirioxohphahliza',
            'OS_REGION_NAME': 'RegionOne',
            'API_VERSION': 2}
        openstack_utils.get_keystone_session_from_relation('swift-proxy')
        self.get_relation_from_unit.assert_called_once_with(
            'swift-proxy',
            'keystone',
            'identity-service',
            model_name=None)
        self.get_keystone_session.assert_called_once_with(
            {
                'OS_AUTH_URL': 'http://10.5.0.36:5000/v2.0',
                'OS_TENANT_NAME': 'services',
                'OS_USERNAME': 's3_swift',
                'OS_PASSWORD': 'CKGsVg2p',
                'OS_REGION_NAME': 'RegionOne',
                'API_VERSION': 2,
                'OS_PROJECT_NAME': 'services'},
            scope='PROJECT',
            verify=None)

    def test_get_gateway_uuids(self):
        self.patch_object(openstack_utils.juju_utils,
                          'get_machine_uuids_for_application')
        self.get_machine_uuids_for_application.return_value = 'ret'
        self.assertEquals(openstack_utils.get_gateway_uuids(), 'ret')
        self.get_machine_uuids_for_application.assert_called_once_with(
            'neutron-gateway')

    def test_get_ovs_uuids(self):
        self.patch_object(openstack_utils.juju_utils,
                          'get_machine_uuids_for_application')
        self.get_machine_uuids_for_application.return_value = 'ret'
        self.assertEquals(openstack_utils.get_ovs_uuids(), 'ret')
        self.get_machine_uuids_for_application.assert_called_once_with(
            'neutron-openvswitch')

    def test_get_ovn_uuids(self):
        self.patch_object(openstack_utils.juju_utils,
                          'get_machine_uuids_for_application')
        self.get_machine_uuids_for_application.return_value = ['ret']
        self.assertEquals(list(openstack_utils.get_ovn_uuids()),
                          ['ret', 'ret'])
        self.get_machine_uuids_for_application.assert_has_calls([
            mock.call('ovn-chassis'),
            mock.call('ovn-dedicated-chassis'),
        ])

    def test_dvr_enabled(self):
        self.patch_object(openstack_utils, 'get_application_config_option')
        openstack_utils.dvr_enabled()
        self.get_application_config_option.assert_called_once_with(
            'neutron-api', 'enable-dvr')

    def test_ovn_present(self):
        self.patch_object(openstack_utils.model, 'get_application')
        self.get_application.side_effect = [None, KeyError]
        self.assertTrue(openstack_utils.ovn_present())
        self.get_application.side_effect = [KeyError, None]
        self.assertTrue(openstack_utils.ovn_present())
        self.get_application.side_effect = [KeyError, KeyError]
        self.assertFalse(openstack_utils.ovn_present())

    def test_ngw_present(self):
        self.patch_object(openstack_utils.model, 'get_application')
        self.get_application.side_effect = None
        self.assertTrue(openstack_utils.ngw_present())
        self.get_application.side_effect = KeyError
        self.assertFalse(openstack_utils.ngw_present())

    def test_get_charm_networking_data(self):
        self.patch_object(openstack_utils, 'deprecated_external_networking')
        self.patch_object(openstack_utils, 'dvr_enabled')
        self.patch_object(openstack_utils, 'ovn_present')
        self.patch_object(openstack_utils, 'ngw_present')
        self.patch_object(openstack_utils, 'get_ovs_uuids')
        self.patch_object(openstack_utils, 'get_gateway_uuids')
        self.patch_object(openstack_utils, 'get_ovn_uuids')
        self.patch_object(openstack_utils.model, 'get_application')
        self.dvr_enabled.return_value = False
        self.ovn_present.return_value = False
        self.ngw_present.return_value = False
        self.get_ovs_uuids.return_value = []
        self.get_gateway_uuids.return_value = []
        self.get_ovn_uuids.return_value = []
        self.get_application.side_effect = KeyError

        with self.assertRaises(RuntimeError):
            openstack_utils.get_charm_networking_data()
        self.ngw_present.return_value = True
        self.assertEquals(
            openstack_utils.get_charm_networking_data(),
            openstack_utils.CharmedOpenStackNetworkingData(
                openstack_utils.OpenStackNetworkingTopology.ML2_OVS,
                ['neutron-gateway'],
                mock.ANY,
                'data-port',
                {}))
        self.dvr_enabled.return_value = True
        self.assertEquals(
            openstack_utils.get_charm_networking_data(),
            openstack_utils.CharmedOpenStackNetworkingData(
                openstack_utils.OpenStackNetworkingTopology.ML2_OVS_DVR,
                ['neutron-gateway', 'neutron-openvswitch'],
                mock.ANY,
                'data-port',
                {}))
        self.ngw_present.return_value = False
        self.assertEquals(
            openstack_utils.get_charm_networking_data(),
            openstack_utils.CharmedOpenStackNetworkingData(
                openstack_utils.OpenStackNetworkingTopology.ML2_OVS_DVR_SNAT,
                ['neutron-openvswitch'],
                mock.ANY,
                'data-port',
                {}))
        self.dvr_enabled.return_value = False
        self.ovn_present.return_value = True
        self.assertEquals(
            openstack_utils.get_charm_networking_data(),
            openstack_utils.CharmedOpenStackNetworkingData(
                openstack_utils.OpenStackNetworkingTopology.ML2_OVN,
                ['ovn-chassis'],
                mock.ANY,
                'bridge-interface-mappings',
                {'ovn-bridge-mappings': 'physnet1:br-ex'}))
        self.get_application.side_effect = None
        self.assertEquals(
            openstack_utils.get_charm_networking_data(),
            openstack_utils.CharmedOpenStackNetworkingData(
                openstack_utils.OpenStackNetworkingTopology.ML2_OVN,
                ['ovn-chassis', 'ovn-dedicated-chassis'],
                mock.ANY,
                'bridge-interface-mappings',
                {'ovn-bridge-mappings': 'physnet1:br-ex'}))

    def test_get_cacert_absolute_path(self):
        self.patch_object(openstack_utils.deployment_env, 'get_tmpdir')
        self.get_tmpdir.return_value = '/tmp/default'
        self.assertEqual(
            openstack_utils.get_cacert_absolute_path('filename'),
            '/tmp/default/filename')

    def test_get_cacert(self):
        self.patch_object(openstack_utils.deployment_env, 'get_tmpdir')
        self.get_tmpdir.return_value = '/tmp/default'
        self.patch_object(openstack_utils.os.path, 'exists')
        results = {
            '/tmp/default/vault_juju_ca_cert.crt': True}
        self.exists.side_effect = lambda x: results[x]
        self.assertEqual(
            openstack_utils.get_cacert(),
            '/tmp/default/vault_juju_ca_cert.crt')

        results = {
            '/tmp/default/vault_juju_ca_cert.crt': False,
            '/tmp/default/keystone_juju_ca_cert.crt': True}
        self.assertEqual(
            openstack_utils.get_cacert(),
            '/tmp/default/keystone_juju_ca_cert.crt')

        results = {
            '/tmp/default/vault_juju_ca_cert.crt': False,
            '/tmp/default/keystone_juju_ca_cert.crt': False}
        self.assertIsNone(openstack_utils.get_cacert())

    def test_get_remote_ca_cert_file(self):
        self.patch_object(openstack_utils.model, 'get_first_unit_name')
        self.patch_object(
            openstack_utils,
            '_get_remote_ca_cert_file_candidates')
        self.patch_object(openstack_utils.model, 'scp_from_unit')
        self.patch_object(openstack_utils.os.path, 'exists')
        self.patch_object(openstack_utils.shutil, 'move')
        self.patch_object(openstack_utils.os, 'chmod')
        self.patch_object(openstack_utils.tempfile, 'NamedTemporaryFile')
        self.patch_object(openstack_utils.deployment_env, 'get_tmpdir')
        self.get_tmpdir.return_value = '/tmp/default'
        enter_mock = mock.MagicMock()
        enter_mock.__enter__.return_value.name = 'tempfilename'
        self.NamedTemporaryFile.return_value = enter_mock
        self.get_first_unit_name.return_value = 'neutron-api/0'
        self._get_remote_ca_cert_file_candidates.return_value = [
            '/tmp/ca1.cert']
        self.exists.return_value = True

        openstack_utils.get_remote_ca_cert_file('neutron-api')
        self.scp_from_unit.assert_called_once_with(
            'neutron-api/0',
            '/tmp/ca1.cert',
            'tempfilename')
        self.chmod.assert_called_once_with('/tmp/default/ca1.cert', 0o644)
        self.move.assert_called_once_with(
            'tempfilename', '/tmp/default/ca1.cert')

    def test_configure_charmed_openstack_on_maas(self):
        self.patch_object(openstack_utils, 'get_charm_networking_data')
        self.patch_object(openstack_utils.zaza.utilities.maas,
                          'get_macs_from_cidr')
        self.patch_object(openstack_utils.zaza.utilities.maas,
                          'get_maas_client_from_juju_cloud_data')
        self.patch_object(openstack_utils.zaza.model, 'get_cloud_data')
        self.patch_object(openstack_utils, 'configure_networking_charms')
        self.get_charm_networking_data.return_value = 'fakenetworkingdata'
        self.get_macs_from_cidr.return_value = [
            MachineInterfaceMac('id_a', 'ens6', '00:53:00:00:00:01',
                                '192.0.2.0/24', LinkMode.LINK_UP),
            MachineInterfaceMac('id_a', 'ens7', '00:53:00:00:00:02',
                                '192.0.2.0/24', LinkMode.LINK_UP),
            MachineInterfaceMac('id_b', 'ens6', '00:53:00:00:01:01',
                                '192.0.2.0/24', LinkMode.LINK_UP),

        ]
        network_config = {'external_net_cidr': '192.0.2.0/24'}
        expect = [
            '00:53:00:00:00:01',
            '00:53:00:00:01:01',
        ]
        openstack_utils.configure_charmed_openstack_on_maas(
            network_config)
        self.configure_networking_charms.assert_called_once_with(
            'fakenetworkingdata', expect, use_juju_wait=False)


class TestAsyncOpenstackUtils(ut_utils.AioTestCase):

    def setUp(self):
        super(TestAsyncOpenstackUtils, self).setUp()
        if sys.version_info < (3, 6, 0):
            raise unittest.SkipTest("Can't AsyncMock in py35")
        model_mock = mock.MagicMock()
        test_mock = mock.MagicMock()

        class AsyncContextManagerMock(test_mock):
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        self.model_mock = model_mock
        self.patch_object(openstack_utils.zaza.model, "async_block_until")

        async def _block_until(f, timeout):
            # Store the result of the call to _check_ca_present to validate
            # tests
            self.result = await f()
        self.async_block_until.side_effect = _block_until
        self.patch('zaza.model.run_in_model', name='_run_in_model')
        self._run_in_model.return_value = AsyncContextManagerMock
        self._run_in_model().__aenter__.return_value = self.model_mock

    async def test_async_block_until_ca_exists(self):
        def _get_action_output(stdout, code, stderr=None):
            stderr = stderr or ''
            action = mock.MagicMock()
            action.data = {
                'results': {
                    'Code': code,
                    'Stderr': stderr,
                    'Stdout': stdout}}
            return action
        results = {
            '/tmp/missing.cert': _get_action_output(
                '',
                '1',
                'cat: /tmp/missing.cert: No such file or directory'),
            '/tmp/good.cert': _get_action_output('CERTIFICATE', '0')}

        async def _run(command, timeout=None):
            return results[command.split()[-1]]
        self.unit1 = mock.MagicMock()
        self.unit2 = mock.MagicMock()
        self.unit2.run.side_effect = _run
        self.unit1.run.side_effect = _run
        self.units = [self.unit1, self.unit2]
        _units = mock.MagicMock()
        _units.units = self.units
        self.model_mock.applications = {
            'keystone': _units
        }
        self.patch_object(
            openstack_utils,
            "_async_get_remote_ca_cert_file_candidates")

        # Test a missing cert then a good cert.
        self._async_get_remote_ca_cert_file_candidates.return_value = [
            '/tmp/missing.cert',
            '/tmp/good.cert']
        await openstack_utils.async_block_until_ca_exists(
            'keystone',
            'CERTIFICATE')
        self.assertTrue(self.result)

        # Test a single missing
        self._async_get_remote_ca_cert_file_candidates.return_value = [
            '/tmp/missing.cert']
        await openstack_utils.async_block_until_ca_exists(
            'keystone',
            'CERTIFICATE')
        self.assertFalse(self.result)

    async def test__async_get_remote_ca_cert_file_candidates(self):
        self.patch_object(openstack_utils.zaza.model, "async_get_relation_id")
        rel_id_out = {
        }

        def _get_relation_id(app, cert_app, model_name, remote_interface_name):
            return rel_id_out[cert_app]
        self.async_get_relation_id.side_effect = _get_relation_id

        rel_id_out['vault'] = 'certs:1'
        r = await openstack_utils._async_get_remote_ca_cert_file_candidates(
            'neutron-api', 'mymodel')
        self.assertEqual(
            r,
            ['/usr/local/share/ca-certificates/vault_juju_ca_cert.crt',
             '/usr/local/share/ca-certificates/keystone_juju_ca_cert.crt'])

        rel_id_out['vault'] = None
        r = await openstack_utils._async_get_remote_ca_cert_file_candidates(
            'neutron-api', 'mymodel')
        self.assertEqual(
            r,
            ['/usr/local/share/ca-certificates/keystone_juju_ca_cert.crt'])
