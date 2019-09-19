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

import logging
import zaza.model


def wait_for_cluster(model_name=None, timeout=1200):
    """Wait for rmq units extended status to show cluster readiness,
    after an optional initial sleep period.  Initial sleep is likely
    necessary to be effective following a config change, as status
    message may not instantly update to non-ready."""
    states = {
        'rabbitmq-server': {
            'workload-status-messages': 'Unit is ready and clustered'
        }
    }

    zaza.model.wait_for_application_states(model_name=model_name,
                                           states=states,
                                           timeout=timeout)


def get_cluster_status(unit):
    """Execute rabbitmq cluster status command on a unit and return
    the full output.
    :param unit: unit
    :returns: String containing console output of cluster status command
    """
    cmd = 'rabbitmqctl cluster_status'
    output = zaza.model.run_on_unit(unit.entity_id, cmd)['Stdout'].strip()
    logging.debug('{} cluster_status:\n{}'.format(
        unit.entity_id, output))
    return str(output)


