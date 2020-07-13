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

"""Setup for ceph-osd deployments."""

import logging
import zaza.model


def basic_setup():
    """Run basic setup for ceph-osd."""
    pass


def ceph_ready():
    """Wait for ceph to be ready.

    Wait for ceph to be ready. This is useful if the target_deploy_status in
    the tests.yaml is expecting ceph to be in a blocked state. After ceph
    has been unblocked the deploy may need to wait to be ceph to be ready.
    """
    logging.info("Waiting for ceph units to settle")
    zaza.model.wait_for_application_states()
    zaza.model.block_until_all_units_idle()
    logging.info("Ceph units settled")
