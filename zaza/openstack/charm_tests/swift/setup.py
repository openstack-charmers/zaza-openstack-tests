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

"""Code for configuring swift."""

import logging
import tenacity

import zaza.openstack.utilities.openstack as openstack


@tenacity.retry(wait=tenacity.wait_exponential(multiplier=10, max=300),
                reraise=True, stop=tenacity.stop_after_attempt(10),
                retry=tenacity.retry_if_exception_type(AssertionError))
def wait_for_region2():
    """Ensure two regions are present."""
    keystone_session = openstack.get_overcloud_keystone_session()
    keystone_client = (
        openstack.get_keystone_session_client(
            keystone_session,
            client_api_version='3'))
    swift_svc_id = keystone_client.services.find(name='swift').id
    regions = set([ep.region
                   for ep in keystone_client.endpoints.list(swift_svc_id)])
    logging.info('Checking there are 2 regions. Current count is {}'.format(
        len(regions)))
    assert len(set(regions)) == 2, "Incorrect number of regions"
