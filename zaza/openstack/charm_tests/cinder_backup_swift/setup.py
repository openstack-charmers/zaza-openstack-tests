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

"""Code for configuring cinder-backup-swift."""

import zaza.model as zaza_model
import time


def basic_setup():
    """Run setup for testing cinder-backup-swift.

    Cinder backup setup for testing cinder-backup is currently part of
    cinder-backup functional tests.
    Volume backup setup for other tests to use should go here.
    """


def configure_cinder_backup():
    """Configure cinder-backup-swift."""
    keystone_ip = zaza_model.get_app_ips(
        'swift-keystone')[0]
    swift_ip = zaza_model.get_app_ips(
        'swift-proxy')[0]
    auth_ver = (zaza_model.get_application_config('swift-keystone')
                .get('preferred-api-version').get('value'))
    if auth_ver == 2:
        auth_url = 'http://{}:5000/v2.0'.format(keystone_ip)
        endpoint_url = 'http://{}:8080/v1/AUTH_'.format(swift_ip)
    else:
        auth_url = 'http://{}:5000/v3'.format(keystone_ip)
        endpoint_url = 'http://{}:8080/v1/AUTH'.format(swift_ip)
    cinder_backup_swift_conf = {
        'endpoint-url': endpoint_url,
        'auth-url': auth_url
    }
    juju_service = 'cinder-backup-swift'
    zaza_model.set_application_config(juju_service, cinder_backup_swift_conf)
    zaza_model.wait_for_application_states()
    time.sleep(300)
