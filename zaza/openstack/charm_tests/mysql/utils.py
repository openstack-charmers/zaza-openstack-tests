# Copyright 2020 Canonical Ltd.
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

"""Module of functions for interfacing with the percona-cluster charm."""

import zaza.model as model


def complete_cluster_series_upgrade():
    """Run the complete-cluster-series-upgrade action on the lead unit."""
    # TODO: Make this work across either mysql or percona-cluster names
    model.run_action_on_leader(
        'mysql',
        'complete-cluster-series-upgrade',
        action_params={})
