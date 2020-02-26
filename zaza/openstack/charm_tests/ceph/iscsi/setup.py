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

"""Setup for ceph iscsi gateway deployments."""

import zaza.model


def basic_guest_setup():
    """Run basic setup for iscsi guest."""
    unit = zaza.model.get_units('ubuntu')[0]
    setup_cmds = [
        "apt install --yes open-iscsi multipath-tools",
        "systemctl start iscsi",
        "systemctl start iscsid"]
    for cmd in setup_cmds:
        zaza.model.run_on_unit(
            unit.entity_id,
            cmd)
