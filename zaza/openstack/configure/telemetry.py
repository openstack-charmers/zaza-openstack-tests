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

import logging

import zaza.model

def ceilometer_upgrade(application_name=None, model_name=None):
    zaza.model.run_action_on_leader(
        application_name or self.application_name,
        'ceilometer-upgrade',
        model_name=model_name,
        action_params={})

