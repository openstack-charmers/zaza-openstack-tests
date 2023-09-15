import copy
import mock
import unit_tests.utils as ut_utils
import uuid

import zaza.model
import zaza.openstack.utilities.swift as swift_utils
import zaza.openstack.utilities.juju as juju_utils

import unit_tests.utilities.swift_test_data as swift_test_data


class TestSwiftUtils(ut_utils.BaseTestCase):

    def setUp(self):
        super(TestSwiftUtils, self).setUp()

    def test_ObjectReplica_init(self):
        obj_rep = swift_utils.ObjectReplica(
            "Server:Port Device      10.5.0.38:6000 loop0")
        self.assertEqual(
            obj_rep.server,
            "10.5.0.38")
        self.assertEqual(
            obj_rep.port,
            "6000")
        self.assertEqual(
            obj_rep.device,
            "loop0")
        self.assertFalse(obj_rep.handoff_device)
        obj_rep = swift_utils.ObjectReplica(
            "Server:Port Device      10.5.0.9:6000 loop0      [Handoff]")
        self.assertTrue(obj_rep.handoff_device)

    def test_ObjectReplicas(self):
        self.patch_object(zaza.model, 'run_on_leader')
        self.run_on_leader.return_value = {
            'Stdout': swift_test_data.SWIFT_GET_NODES_STDOUT}
        obj_replicas = swift_utils.ObjectReplicas(
            'swift-proxy-region1',
            'account123',
            'my-container',
            'my-object',
            swift_test_data.STORAGE_TOPOLOGY,
            'my-model')
        self.assertEqual(
            sorted(obj_replicas.hand_off_ips),
            ['10.5.0.15', '10.5.0.18', '10.5.0.34', '10.5.0.9'])
        self.assertEqual(
            sorted(obj_replicas.storage_ips),
            ['10.5.0.38', '10.5.0.4'])
        self.assertEqual(
            obj_replicas.placements,
            [
                {
                    'app_name': 'swift-storage-region2-zone3',
                    'region': 2,
                    'unit': 'swift-storage-region2-zone3/0',
                    'zone': 3},
                {
                    'app_name': 'swift-storage-region1-zone3',
                    'region': 1,
                    'unit': 'swift-storage-region1-zone3/0',
                    'zone': 3}])
        self.assertEqual(
            obj_replicas.distinct_regions,
            [1, 2])
        self.assertEqual(
            sorted(obj_replicas.all_zones),
            [(1, 3), (2, 3)])
        self.assertEqual(
            sorted(obj_replicas.distinct_zones),
            [(1, 3), (2, 3)])

    def test_get_swift_storage_topology(self):
        unit_r1z1_mock = mock.MagicMock(public_address='10.5.0.18')
        unit_r1z2_mock = mock.MagicMock(public_address='10.5.0.34')
        unit_r1z3_mock = mock.MagicMock(public_address='10.5.0.4')
        unit_r2z1_mock = mock.MagicMock(public_address='10.5.0.9')
        unit_r2z2_mock = mock.MagicMock(public_address='10.5.0.15')
        unit_r2z3_mock = mock.MagicMock(public_address='10.5.0.38')
        app_units = {
            'swift-storage-region1-zone1': [unit_r1z1_mock],
            'swift-storage-region1-zone2': [unit_r1z2_mock],
            'swift-storage-region1-zone3': [unit_r1z3_mock],
            'swift-storage-region2-zone1': [unit_r2z1_mock],
            'swift-storage-region2-zone2': [unit_r2z2_mock],
            'swift-storage-region2-zone3': [unit_r2z3_mock]}

        expected_topology = copy.deepcopy(swift_test_data.STORAGE_TOPOLOGY)
        self.patch_object(juju_utils, 'get_full_juju_status')
        self.patch_object(zaza.model, 'get_application_config')
        self.patch_object(zaza.model, 'get_units')
        self.patch_object(zaza.model, 'get_unit_public_address')

        def _get_unit_public_address(u, model_name=None):
            return u.public_address

        self.get_unit_public_address.side_effect = _get_unit_public_address

        juju_status = mock.MagicMock()
        juju_status.applications = {}
        self.get_full_juju_status.return_value = juju_status

        for app_name, units in app_units.items():
            ip = units[0].public_address
            expected_topology[ip]['unit'] = units[0]

        app_config = {}
        for app_name in app_units.keys():
            juju_status.applications[app_name] = {'charm': 'cs:swift-storage'}
            region = int(app_name.split('-')[2].replace('region', ''))
            zone = int(app_name.split('-')[3].replace('zone', ''))
            app_config[app_name] = {
                'storage-region': {'value': region},
                'zone': {'value': zone}}

        self.get_application_config.side_effect = \
            lambda x, model_name: app_config[x]
        self.get_units.side_effect = lambda x, model_name: app_units[x]
        self.assertEqual(
            swift_utils.get_swift_storage_topology(),
            expected_topology)

    def test_setup_test_container(self):
        swift_client = mock.MagicMock()
        self.patch_object(uuid, 'uuid1', return_value='auuid')
        swift_client.get_account.return_value = (
            {'x-account-project-domain-id': 'domain-id'},
            'bob-auuid-container')
        self.assertEqual(
            swift_utils.setup_test_container(swift_client, 'bob'),
            ('bob-auuid-container', 'domain-id'))
        swift_client.put_container.assert_called_once_with(
            'bob-auuid-container')

    def test_apply_proxy_config(self):
        self.patch_object(zaza.model, 'block_until_all_units_idle')
        self.patch_object(
            zaza.model,
            'get_application_config',
            return_value={
                'go-faster': {
                    'value': False}})
        self.patch_object(zaza.model, 'set_application_config')
        swift_utils.apply_proxy_config(
            'proxy-app',
            {'go-faster': True})
        self.set_application_config.assert_called_once_with(
            'proxy-app', {'go-faster': True}, model_name=None)

    def test_apply_proxy_config_noop(self):
        self.patch_object(zaza.model, 'block_until_all_units_idle')
        self.patch_object(
            zaza.model,
            'get_application_config',
            return_value={
                'go-faster': {
                    'value': True}})
        self.patch_object(zaza.model, 'set_application_config')
        swift_utils.apply_proxy_config(
            'proxy-app',
            {'go-faster': True})
        self.assertFalse(self.set_application_config.called)

    def test_create_object(self):
        self.patch_object(swift_utils, 'setup_test_container')
        self.setup_test_container.return_value = ('new-container', 'domain-id')
        self.patch_object(
            swift_utils,
            'ObjectReplicas',
            return_value='obj_replicas')
        swift_client = mock.MagicMock()
        self.assertEqual(
            swift_utils.create_object(
                swift_client,
                'proxy-app',
                swift_test_data.STORAGE_TOPOLOGY,
                'my-prefix'),
            ('new-container', 'zaza_test_object.txt', 'obj_replicas'))
        self.setup_test_container.assert_called_once_with(
            swift_client,
            'my-prefix')
        swift_client.put_object.assert_called_once_with(
            'new-container',
            'zaza_test_object.txt',
            content_type='text/plain',
            contents='File contents')
        self.ObjectReplicas.assert_called_once_with(
            'proxy-app',
            'domain-id',
            'new-container',
            'zaza_test_object.txt',
            swift_test_data.STORAGE_TOPOLOGY,
            model_name=None)
