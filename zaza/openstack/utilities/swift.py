# Copyright 2019 Canonical Ltd.
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

"""Swift utilities."""

import logging
import uuid
import zaza.model
import zaza.openstack.utilities.juju as juju_utils


class ObjectReplica:
    """A replica of an object.

    The replica attributes show the location of an object replica.

    server: IP address or hostname of machine hosting replica
    port: Port of swift object server running on machine hosting replica
    device: Path to device hosting replica
    handoff_device: Whether this is a handoff devices. Handoff devices pass
                    the replica on to a remote storage node.
    """

    def __init__(self, raw_line):
        """Extract storage info from text."""
        rl = raw_line.split()
        self.server, self.port = rl[2].split(':')
        self.device = rl[3]
        self.handoff_device = rl[-1] == '[Handoff]'


class ObjectReplicas:
    """Replicas of an object."""

    def __init__(self, proxy_app, account, container_name, object_name,
                 storage_topology, model_name=None):
        """Find all replicas of given object.

        :param proxy_app: Name of proxy application
        :type proxy_app: str
        :param account: Account that owns the container.
        :type account: str
        :param container_name: Name of container that contains the object.
        :type container_name: str
        :param object_name: Name of object.
        :type object_name: str
        :param storage_topology: Dictionary keyed on IP of storage node info.
        :type storage_topology: {}
        :param model_name: Model to point environment at
        :type model_name: str
        """
        self.replicas = []
        self.replica_placements = {}
        self.storage_topology = storage_topology
        raw_output = self.run_get_nodes(
            proxy_app,
            account,
            container_name,
            object_name,
            model_name=model_name)
        for line in self.extract_storage_lines(raw_output):
            self.add_replica(line)

    def add_replica(self, storage_line):
        """Add a replica to the replica set."""
        self.replicas.append(ObjectReplica(storage_line))

    def extract_storage_lines(self, raw_output):
        """Extract replica list from output of swift-get-nodes.

        :param storage_line: Output of swift-get-nodes
        :type storage_line: str
        :returns: List of lines relating to replicas.
        :rtype: [str, ...]
        """
        storage_lines = []
        for line in raw_output.split('\n'):
            if line.startswith('Server:Port '):
                storage_lines.append(line)
        return storage_lines

    def run_get_nodes(self, proxy_app, account, container_name, object_name,
                      model_name=None):
        """Run swift-get-nodes for an object on a proxy unit.

        :param proxy_app: Name of proxy application
        :type proxy_app: str
        :param account: Account that owns the container.
        :type account: str
        :param container_name: Name of container that contains the object.
        :type container_name: str
        :param object_name: Name of object.
        :type object_name: str
        :param model_name: Model to point environment at
        :type model_name: str
        :returns: Stdout of command
        :rtype: str
        """
        ring_file = '/etc/swift/object.ring.gz'
        obj_cmd = "swift-get-nodes  -a {} {} {} {}".format(
            ring_file,
            account,
            container_name,
            object_name)
        cmd_result = zaza.model.run_on_leader(
            proxy_app,
            obj_cmd,
            model_name=model_name)
        return cmd_result['Stdout']

    @property
    def hand_off_ips(self):
        """Replicas which are marked as handoff devices.

        These are not real replicas. They hand off the replica to other node.

        :returns: List of IPS of handoff nodes for object.
        :rtype: List[str]
        """
        return [r.server for r in self.replicas if r.handoff_device]

    @property
    def storage_ips(self):
        """Ip addresses of nodes that are housing a replica.

        :returns: List of IPS of storage nodes holding a replica of the object.
        :rtype: [str, ...]
        """
        return [r.server for r in self.replicas if not r.handoff_device]

    @property
    def placements(self):
        """Region an zone information for each replica.

        Zone info is in the form:
            [{
                'app_name': str,
                'unit': juju.Unit,
                'region': int,
                'zone': int}, ...]

        :returns: List of dicts with region and zone information.
        :rtype: List[Dict[str, Union[str,int]]]
        """
        return [self.storage_topology[ip] for ip in self.storage_ips]

    @property
    def distinct_regions(self):
        """List of distinct regions that have a replica.

        :returns: List of regions that have a replica
        :rtype: [int, ...]
        """
        return list(set([p['region'] for p in self.placements]))

    @property
    def all_zones(self):
        """List of all zones that have a replica.

        :returns: List of tuples (region, zone) that have a replica.
        :rtype: List[Tuple[str, str]]
        """
        return [(p['region'], p['zone']) for p in self.placements]

    @property
    def distinct_zones(self):
        """List of distinct region + zones that have a replica.

        :returns: List of tuples (region, zone) that have a replica.
        :rtype: [(r1, z1), ...]
        """
        return list(set(self.all_zones))


def get_swift_storage_topology(model_name=None):
    """Get details of storage nodes and which region and zones they belong in.

    :param model_name: Model to point environment at
    :type model_name: str
    :returns: Dictionary of storage nodes and their region/zone information.
    :rtype: {
        'ip (str)': {
            'app_name': str,
            'unit': juju.Unit
            'region': int,
            'zone': int},
        ...}
    """
    topology = {}
    status = juju_utils.get_full_juju_status(model_name=model_name)
    for app_name, app_dep_config in status.applications.items():
        if 'swift-storage' in app_dep_config['charm']:
            app_config = zaza.model.get_application_config(
                app_name,
                model_name=model_name)
            region = app_config['storage-region']['value']
            zone = app_config['zone']['value']
            for unit in zaza.model.get_units(app_name, model_name=model_name):
                unit_ip = zaza.model.get_unit_public_address(
                    unit,
                    model_name=model_name)
                topology[unit_ip] = {
                    'app_name': app_name,
                    'unit': unit,
                    'region': region,
                    'zone': zone}
    return topology


def setup_test_container(swift_client, resource_prefix):
    """Create a swift container for use be tests.

    :param swift_client: Swift client to use for object creation
    :type swift_client: swiftclient.Client
    :returns: (container_name, account_name) Container name and account
              name for new container
    :rtype: Tuple[str, str]
    """
    run_id = str(uuid.uuid1()).split('-')[0]
    container_name = '{}-{}-container'.format(resource_prefix, run_id)
    swift_client.put_container(container_name)
    resp_headers, containers = swift_client.get_account()
    account = resp_headers['x-account-project-domain-id']
    return container_name, account


def apply_proxy_config(proxy_app, config, model_name=None):
    """Update the give proxy_app with new charm config.

    :param proxy_app: Name of proxy application
    :type proxy_app: str
    :param config: Dictionary of configuration setting(s) to apply
    :type config: dict
    :param model_name: Name of model to query.
    :type model_name: str
    """
    current_config = zaza.model.get_application_config(
        proxy_app,
        model_name=model_name)
    # Although there is no harm in applying config that is a noop it
    # does affect the expected behaviour afterwards. So, only apply
    # genuine changes so we can safely expect the charm to fire a hook.
    for key, value in config.items():
        if str(config[key]) != str(current_config[key]['value']):
            break
    else:
        logging.info(
            'Config update for {} not required.'.format(proxy_app))
        return
    logging.info('Updating {} charm settings'.format(proxy_app))
    zaza.model.set_application_config(
        proxy_app,
        config,
        model_name=model_name)
    zaza.model.block_until_all_units_idle()


def create_object(swift_client, proxy_app, storage_topology, resource_prefix,
                  model_name=None):
    """Create a test object in a new container.

    :param swift_client: Swift client to use for object creation
    :type swift_client: swiftclient.Client
    :param proxy_app: Name of proxy application
    :type proxy_app: str
    :param storage_topology: Dictionary keyed on IP of storage node info.
    :type storage_topology: {}
    :param resource_prefix: Prefix to use when naming new resources
    :type resource_prefix: str
    :param model_name: Model to point environment at
    :type model_name: str
    :returns: (container_name, object_name, object replicas)
    :rtype: (str, str, ObjectReplicas)
    """
    container_name, account = setup_test_container(
        swift_client,
        resource_prefix)
    object_name = 'zaza_test_object.txt'
    swift_client.put_object(
        container_name,
        object_name,
        contents='File contents',
        content_type='text/plain'
    )
    obj_replicas = ObjectReplicas(
        proxy_app,
        account,
        container_name,
        object_name,
        storage_topology,
        model_name=model_name)
    return container_name, object_name, obj_replicas


def search_builder(proxy_app, ring, search_target, model_name=None):
    """Run a swift-ring-builder search.

    :param proxy_app: Name of proxy application
    :type proxy_app: str
    :param ring: Name of ring (one of: object, account, container)
    :type ring: str
    :param search_target: device search string (see: man swift-ring-builder)
    :type search_target: str
    :param model_name: Model to point environment at
    :type model_name: str
    :returns: stdout - full stdout output from swift-ring-builder cmd
    :rtype: str
    """
    cmd = ('swift-ring-builder /etc/swift/{}.builder search {}'
           ''.format(ring, search_target))
    result = zaza.model.run_on_leader(proxy_app, cmd,
                                      model_name=model_name)
    return result['Stdout']


def is_proxy_ring_up_to_date(proxy_app, ring, model_name=None):
    """Check if the ring file is up-to-date with changes of the builder.

    :param proxy_app: Name of proxy application
    :type proxy_app: str
    :param ring: Name of ring (one of: object, account, container)
    :type ring: str
    :param model_name: Model to point environment at
    :type model_name: str
    :returns: True if swift-ring-builder denotes ring.gz file is up-to-date
    :rtype: str
    """
    logging.info('Checking ring file matches builder file')
    cmd = ('swift-ring-builder /etc/swift/{}.builder | '
           'grep "Ring file .* is"'.format(ring))
    result = zaza.model.run_on_leader(proxy_app, cmd, model_name=model_name)
    expected = ('Ring file /etc/swift/{}.ring.gz is up-to-date'
                ''.format(ring))
    return bool(result['Stdout'].strip('\n') == expected)


def is_ring_synced(proxy_app, ring, expected_hosts, model_name=None):
    """Check if md5sums of rings on swift-storage are synced to this proxy.

    :param proxy_app: Name of proxy application
    :type proxy_app: str
    :param ring: Name of ring (one of: object, account, container)
    :type ring: str
    :param expoected_hosts: Number of swift-storage hosts in test environment
    :type search_target: int
    :param model_name: Model to point environment at
    :type model_name: str
    :returns: True if all expected_hosts matched md5sum of proxy ring file
    :rtype: bool
    """
    logging.info('Checking ring md5sums on storage unit(s) against proxy')
    zaza.model.block_until_all_units_idle()
    cmd = ('swift-recon {} --md5 | '
           'grep -A1 "ring md5" | tail -1'.format(ring))
    result = zaza.model.run_on_leader(proxy_app, cmd, model_name=model_name)
    expected = ('{num}/{num} hosts matched, 0 error[s] while checking hosts.'
                ''.format(num=expected_hosts))
    return bool(result['Stdout'].strip('\n') == expected)
