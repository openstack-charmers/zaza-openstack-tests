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

"""Code for configuring Trilio."""

import logging
import os

import zaza.model as zaza_model
import zaza.openstack.utilities.juju as juju_utils
import zaza.openstack.utilities.generic as generic_utils


def basic_setup():
    """Run setup for testing Trilio.

    Setup for testing Trilio is currently part of functional
    tests.
    """
    logging.info("Configuring NFS Server")
    nfs_server_ip = zaza_model.get_app_ips("nfs-server-test-fixture")[0]
    trilio_wlm_unit = zaza_model.get_first_unit_name("trilio-wlm")

    nfs_shares_conf = {"nfs-shares": "{}:/srv/testing".format(nfs_server_ip)}
    _trilio_services = ["trilio-wlm", "trilio-data-mover"]

    conf_changed = False
    for juju_service in _trilio_services:
        app_config = zaza_model.get_application_config(juju_service)
        if app_config["nfs-shares"] != nfs_shares_conf["nfs-shares"]:
            zaza_model.set_application_config(juju_service, nfs_shares_conf)
            conf_changed = True

    if conf_changed:
        zaza_model.wait_for_agent_status()
        # NOTE(jamespage): wlm-api service must be running in order
        #                  to execute the setup actions
        zaza_model.block_until_service_status(
            unit_name=trilio_wlm_unit,
            services=["wlm-api"],
            target_status="active",
        )

    logging.info("Executing create-cloud-admin-trust")
    password = juju_utils.leader_get("keystone", "admin_passwd")

    generic_utils.assertActionRanOK(
        zaza_model.run_action_on_leader(
            "trilio-wlm",
            "create-cloud-admin-trust",
            raise_on_failure=True,
            action_params={"password": password},
        )
    )

    logging.info("Executing create-license")
    test_license = os.environ.get("TEST_TRILIO_LICENSE")
    if test_license and os.path.exists(test_license):
        zaza_model.attach_resource("trilio-wlm",
                                   resource_name='license',
                                   resource_path=test_license)
        generic_utils.assertActionRanOK(
            zaza_model.run_action_on_leader(
                "trilio-wlm", "create-license",
                raise_on_failure=True
            )
        )

    else:
        logging.error("Unable to find Trilio License file")


def python2_workaround():
    """Workaround for Bug #1915914.

    Trilio code currently has a bug which assumes an executable called 'python'
    will be on the path. To workaround this install a package which adds a
    symlink to python
    """
    for unit in zaza_model.get_units('trilio-wlm'):
        zaza_model.run_on_unit(
            unit.entity_id,
            ("apt install --yes python-is-python3; "
             "systemctl restart wlm\\*.service"))
