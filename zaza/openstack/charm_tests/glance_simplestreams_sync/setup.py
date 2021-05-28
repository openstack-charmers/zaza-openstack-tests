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

"""Code for configuring glance-simplestreams-sync."""

import logging
import tenacity

import zaza.model as zaza_model
import zaza.openstack.utilities.generic as generic_utils


def sync_images():
    """Run image sync using an action.

    Execute an initial image sync using an action to ensure that the
    cloud is populated with images at the right point in time during
    deployment.
    """
    logging.info("Synchronising images using glance-simplestreams-sync")
    for attempt in tenacity.Retrying(
            stop=tenacity.stop_after_attempt(3),
            wait=tenacity.wait_exponential(
                multiplier=1, min=2, max=10),
            reraise=True):
        with attempt:
            generic_utils.assertActionRanOK(
                zaza_model.run_action_on_leader(
                    "glance-simplestreams-sync",
                    "sync-images",
                    raise_on_failure=True,
                    action_params={},
                )
            )
