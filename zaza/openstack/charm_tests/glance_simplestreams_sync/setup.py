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
import pprint

import zaza.model as zaza_model
import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.utilities.openstack as openstack_utils


def _get_catalog():
    """Retrieve the Keystone service catalog.

    :returns: The raw Keystone service catalog.
    :rtype: List[Dict]
    """
    keystone_session = openstack_utils.get_overcloud_keystone_session()
    keystone_client = openstack_utils.get_keystone_session_client(
        keystone_session)

    token = keystone_session.get_token()
    token_data = keystone_client.tokens.get_token_data(token)

    if 'catalog' not in token_data['token']:
        raise ValueError('catalog not in token data: "{}"'
                         .format(pprint.pformat(token_data)))

    return token_data['token']['catalog']


def sync_images():
    """Run image sync using an action.

    Execute an initial image sync using an action to ensure that the
    cloud is populated with images at the right point in time during
    deployment.
    """
    logging.info("Synchronising images using glance-simplestreams-sync")

    catalog = None
    try:
        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_attempt(3),
                wait=tenacity.wait_exponential(
                    multiplier=1, min=2, max=10),
                reraise=True):
            with attempt:
                # Proactively retrieve the Keystone service catalog so that we
                # can log it in the event of a failure.
                catalog = _get_catalog()
                generic_utils.assertActionRanOK(
                    zaza_model.run_action_on_leader(
                        "glance-simplestreams-sync",
                        "sync-images",
                        raise_on_failure=True,
                        action_params={},
                    )
                )
    except Exception:
        logging.info('Contents of Keystone service catalog: "{}"'
                     .format(pprint.pformat(catalog)))
        raise


def set_latest_property_config():
    """Enable set_latest_property config.

    This config adds `latest=true` to new synced images.
    """
    logging.info("Change config `set_latest_property=true`")
    zaza_model.set_application_config('glance-simplestreams-sync',
                                      {'set_latest_property': 'true',
                                       'snap-channel': 'edge'})
    test_config = lifecycle_utils.get_charm_config(fatal=False)
    zaza_model.wait_for_application_states(
        states=test_config.get('target_deploy_status', {}))
