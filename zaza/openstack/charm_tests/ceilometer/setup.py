#!/usr/bin/env python3

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

"""Code for configuring Ceilometer."""

import logging
import zaza.model as zaza_model
import zaza.openstack.utilities.openstack as openstack_utils


def basic_setup():
    """Run setup for testing Ceilometer.

    Setup for testing Ceilometer is currently part of functional
    tests.
    """
    current_release = openstack_utils.get_os_release()
    xenial_ocata = openstack_utils.get_os_release('xenial_ocata')

    if current_release < xenial_ocata:
        logging.info(
            'Skipping ceilometer-upgrade as it is not supported before ocata')
        return

    logging.debug('Checking ceilometer-upgrade')

    action = zaza_model.run_action_on_leader(
        'ceilometer',
        'ceilometer-upgrade',
        raise_on_failure=True)

    return action
