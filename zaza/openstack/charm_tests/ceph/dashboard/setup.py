# Copyright 2021 Canonical Ltd.
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

"""Code for setting up Ceph Dashboard."""

import logging

import zaza.model
import zaza.openstack.utilities.openstack


def check_dashboard_cert(model_name=None):
    """Wait for Dashboard to be ready.

    :param model_name: Name of model to query.
    :type model_name: str
    """
    logging.info("Check dashbaord Waiting for cacert")
    zaza.openstack.utilities.openstack.block_until_ca_exists(
        'ceph-dashboard',
        'CERTIFICATE',
        model_name=model_name)
    zaza.model.block_until_all_units_idle(model_name=model_name)
