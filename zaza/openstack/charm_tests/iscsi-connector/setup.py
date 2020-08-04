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

"""Code for setting up iscsi-connector tests."""

import logging

import zaza.model


def basic_target_setup():
    """Run basic setup for iscsi guest."""
    logging.info('Installing package tgt on ubuntu-target')
    unit = zaza.model.get_units('ubuntu-target')[0]
    setup_cmds = [
        "apt install --yes tgt",
        "systemctl start tgt",
        "open-port 3260"]
    for cmd in setup_cmds:
        zaza.model.run_on_unit(
            unit.entity_id,
            cmd)


def configure_iscsi_target():
    """Configure the iscsi target."""
    lun = 'iqn.2020-07.canonical.com:lun1'
    backing_store = 'dev/vdb'
    initiator_address = zaza.model.get_app_ips('ubuntu')[0]
    username = 'iscsi-user'
    password = 'password123'
    username_in = 'iscsi-target'
    password_in = 'secretpass'
    write_file = (
        """echo -e '<target {}>\n\tbacking-store {}\n\tinitiator-address """
        """{}\n\tincominguser {} {}\n\toutgoinguser {} {}\n</target>' """
        """ | sudo tee /etc/tgt/conf.d/iscsi.conf""".format(lun,
                                                            backing_store,
                                                            initiator_address,
                                                            username,
                                                            password,
                                                            username_in,
                                                            password_in)
    )
    logging.info('Writing target iscsi.conf')
    zaza.model.run_on_unit('ubuntu-target/0', write_file)
    # Restart tgt to load new config
    restart_tgt = "systemctl restart tgt"
    zaza.model.run_on_unit('ubuntu-target/0', restart_tgt)
