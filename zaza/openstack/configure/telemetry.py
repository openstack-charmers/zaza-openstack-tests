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

"""Configure and manage masakari.

Functions for managing masakari resources and simulating compute node loss
and recovery.
"""

import time

import zaza.model


def ceilometer_upgrade(application_name=None, model_name=None):
    """Run ceilometer upgrade action.

    :param application_name: Name of application to run action against.
    :type application_name: str
    :param model_name: Name of model application_name resides in.
    :type model_name: str
    """
    zaza.model.run_action_on_leader(
        application_name,
        'ceilometer-upgrade',
        model_name=model_name,
        action_params={})


def get_alarm(aodh_client, alarm_name):
    """Return the alarm with the given name.

    :param aodh_client: Authenticated aodh v2 client
    :type aodh_client: aodhclient.v2.client.Client
    :param alarm_name: Name of alarm to search for
    :type alarm_name: str
    :returns: Returns a dict of alarm data.
    :rtype: {} or None
    """
    for alarm in aodh_client.alarm.list():
        if alarm['name'] == alarm_name:
            return alarm
    return None


def alarm_cache_wait():
    """Wait for alarm cache to clear."""
    # AODH has an alarm cache (see event_alarm_cache_ttl in aodh.conf). This
    # means deleted alarms can persist and fire. The default is 60s and is
    # currently not configrable via the charm so 61s is a safe assumption.
    time.sleep(61)


def delete_alarm(aodh_client, alarm_name, cache_wait=False):
    """Delete alarm with given name.

    :param aodh_client: Authenticated aodh v2 client
    :type aodh_client: aodhclient.v2.client.Client
    :param alarm_name: Name of alarm to delete
    :type alarm_name: str
    :param cache_wait: Whether to wait for cache to clear after deletion.
    :type cache_wait: bool
    """
    alarm = get_alarm(aodh_client, alarm_name)
    if alarm:
        aodh_client.alarm.delete(alarm['alarm_id'])
    if cache_wait:
        alarm_cache_wait()


def get_alarm_state(aodh_client, alarm_id):
    """Return the state of the alarm with the given name.

    :param aodh_client: Authenticated aodh v2 client
    :type aodh_client: aodhclient.v2.client.Client
    :param alarm_id: ID of provided alarm
    :param alarm_id: str
    :returns: State of given alarm
    :rtype: str
    """
    alarm = aodh_client.alarm.get(alarm_id)
    return alarm['state']


def create_server_power_off_alarm(aodh_client, alarm_name, server_uuid):
    """Create an alarm which triggers when an instance powers off.

    :param aodh_client: Authenticated aodh v2 client
    :type aodh_client: aodhclient.v2.client.Client
    :param alarm_name: Name of alarm to delete
    :type alarm_name: str
    :param server_uuid: UUID of server to monitor
    :type server_uuid: str
    :returns: Dict of alarm data
    :rtype: {}
    """
    alarm_def = {
        'type': 'event',
        'name': alarm_name,
        'description': 'Instance powered OFF',
        'alarm_actions': ['log://'],
        'ok_actions': ['log://'],
        'insufficient_data_actions': ['log://'],
        'event_rule': {
            'event_type': 'compute.instance.power_off.*',
            'query': [{'field': 'traits.instance_id',
                       'op': 'eq',
                       'type': 'string',
                       'value': server_uuid}]}}
    return aodh_client.alarm.create(alarm_def)
