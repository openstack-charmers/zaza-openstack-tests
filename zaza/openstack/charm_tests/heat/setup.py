#!/usr/bin/env python3
#
# Copyright 2021 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Code for configuring heat."""

import logging
import zaza.model


def domain_setup(application_name='heat'):
    """Run required action for a working Heat application."""
    # Action is REQUIRED to run for a functioning heat deployment
    logging.info('Running domain-setup action on heat unit...')
    zaza.model.block_until_wl_status_info_starts_with(application_name,
                                                      "Unit is ready")
    zaza.model.run_action_on_leader(application_name, "domain-setup")
    zaza.model.block_until_wl_status_info_starts_with(application_name,
                                                      "Unit is ready")
