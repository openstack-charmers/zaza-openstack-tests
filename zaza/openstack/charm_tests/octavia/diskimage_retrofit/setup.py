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

"""Code for configuring octavia-diskimage-retrofit."""

import logging

import zaza.model


def retrofit_amphora_image(unit='octavia-diskimage-retrofit/0',
                           force=False, image_id=None):
    """Run action to retrofit Ubuntu Cloud image into Octavia ``amphora``.

    :param image_id: Glance image ID used as source for retrofitting.
                     (Default is to find it based on image properties.)
    :type image_id: str
    :raises:Exception if action does not complete successfully.
    """
    logging.info('Running `retrofit-image` action on {}'.format(unit))
    params = {}
    if force:
        params.update({'force': force})
    if image_id:
        params.update({'source-image': image_id})

    # NOTE(fnordahl) ``zaza.model.run_action_on_leader`` fails here,
    # apparently has to do with handling of subordinates in ``libjuju`` or
    # ``juju`` itself.
    action = zaza.model.run_action(
        unit,
        'retrofit-image',
        action_params=params)
    if not action or action.status != 'completed':
        raise Exception('run-action failed: "{}"'.format(action))
    return action
