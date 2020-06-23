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

"""Common Arista-related utils."""

import json
import requests
import urllib3
import zaza

FIXTURE_APP_NAME = 'arista-virt-test-fixture'


def fixture_ip_addr():
    """Return the public IP address of the Arista test fixture."""
    return zaza.model.get_units(FIXTURE_APP_NAME)[0].public_address


_FIXTURE_LOGIN = 'admin'
_FIXTURE_PASSWORD = 'password123'


def query_fixture_networks(ip_addr):
    """Query the Arista test fixture's list of networks."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
    session.headers['Content-Type'] = 'application/json'
    session.headers['Accept'] = 'application/json'
    session.verify = False
    session.auth = (_FIXTURE_LOGIN, _FIXTURE_PASSWORD)

    data = {
        'id': 'Zaza neutron-arista tests',
        'method': 'runCmds',
        'jsonrpc': '2.0',
        'params': {
            'timestamps': False,
            'format': 'json',
            'version': 1,
            'cmds': ['show openstack networks']
        }
    }

    response = session.post(
        'https://{}/command-api/'.format(ip_addr),
        data=json.dumps(data),
        timeout=10  # seconds
    )

    result = []
    for region in response.json()['result'][0]['regions'].values():
        for tenant in region['tenants'].values():
            for network in tenant['tenantNetworks'].values():
                result.append(network['networkName'])
    return result
