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

"""Code for configuring and initializing tempest."""

import logging

import zaza.openstack.charm_tests.tempest.utils as tempest_utils


def render_tempest_config_keystone_v2():
    """Render tempest config for Keystone V2 API.

    :returns: None
    :rtype: None
    """
    logging.warning(
        'The render_tempest_config_keystone_v2 config step is deprecated. '
        'This is now directly done by the TempestTestWithKeystoneV2 test '
        'class.')
    tempest_utils.render_tempest_config_keystone_v2()


def render_tempest_config_keystone_v3():
    """Render tempest config for Keystone V3 API.

    :returns: None
    :rtype: None
    """
    logging.warning(
        'The render_tempest_config_keystone_v3 config step is deprecated. '
        'This is now directly done by the TempestTestWithKeystoneV3 test '
        'class.')
    tempest_utils.render_tempest_config_keystone_v3()
