# Copyright 2020 Canonical Ltd.
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

"""Collection of functions to support upgrade testing."""


SERVICE_GROUPS = {
    'Core Identity': ['keystone'],
    'Storage': [
        'ceph-mon', 'ceph-osd', 'ceph-fs', 'ceph-radosgw', 'swift-proxy',
        'swift-storage'],
    'Control Plane': [
        'aodh', 'barbican', 'ceilometer', 'cinder', 'designate',
        'designate-bind', 'glance', 'gnocchi', 'heat', 'manila',
        'manila-generic', 'neutron-api', 'neutron-gateway', 'placement',
        'nova-cloud-controller', 'openstack-dashboard'],
    'Compute': ['nova-compute']}

UPGRADE_EXCLUDE_LIST = ['rabbitmq-server', 'percona-cluster']
