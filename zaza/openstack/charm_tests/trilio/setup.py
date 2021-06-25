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

import boto3

import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.model as zaza_model
import zaza.openstack.utilities.juju as juju_utils
import zaza.openstack.utilities.generic as generic_utils
import zaza.openstack.utilities.openstack as openstack_utils


def nfs_setup():
    """Run setup for testing Trilio.

    Setup for testing Trilio is currently part of functional
    tests.
    """
    logging.info("Configuring NFS Server")
    nfs_server_ip = zaza_model.get_app_ips("nfs-server-test-fixture")[0]
    trilio_wlm_unit = zaza_model.get_first_unit_name("trilio-wlm")

    nfs_shares_conf = {"nfs-shares": "{}:/srv/testing".format(nfs_server_ip)}
    logging.info("NFS share config: {}".format(nfs_shares_conf))
    _trilio_services = ["trilio-wlm", "trilio-data-mover"]

    conf_changed = False
    for juju_service in _trilio_services:
        app_config = zaza_model.get_application_config(juju_service)
        if app_config["nfs-shares"] != nfs_shares_conf["nfs-shares"]:
            logging.info("Updating nfs-shares config option")
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


def trust_setup():
    """Run setup Trilio trust setup."""
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


def license_setup():
    """Run setup Trilio license setup."""
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


def s3_setup():
    """Run setup of s3 options for Trilio."""
    session = openstack_utils.get_overcloud_keystone_session()
    ks_client = openstack_utils.get_keystone_session_client(
        session)

    # Get token data so we can glean our user_id and project_id
    token_data = ks_client.tokens.get_token_data(session.get_token())
    project_id = token_data['token']['project']['id']
    user_id = token_data['token']['user']['id']

    # Store URL to service providing S3 compatible API
    for entry in token_data['token']['catalog']:
        if entry['type'] == 's3':
            for endpoint in entry['endpoints']:
                if endpoint['interface'] == 'public':
                    s3_region = endpoint['region']
                    s3_endpoint = endpoint['url']

    # Create AWS compatible application credentials in Keystone
    ec2_creds = ks_client.ec2.create(user_id, project_id)
    cacert = openstack_utils.get_cacert()
    kwargs = {
        'region_name': s3_region,
        'aws_access_key_id': ec2_creds.access,
        'aws_secret_access_key': ec2_creds.secret,
        'endpoint_url': s3_endpoint,
        'verify': cacert,
    }
    s3 = boto3.resource('s3', **kwargs)

    # Create bucket
    bucket_name = 'zaza-trilio'
    logging.info("Creating bucket: {}".format(bucket_name))
    bucket = s3.Bucket(bucket_name)
    bucket.create()

    s3_config = {
        'tv-s3-secret-key': ec2_creds.secret,
        'tv-s3-access-key': ec2_creds.access,
        'tv-s3-region-name': s3_region,
        'tv-s3-bucket': bucket_name,
        'tv-s3-endpoint-url': s3_endpoint}
    for app in ['trilio-wlm', 'trilio-data-mover']:
        logging.info("Setting s3 config for {}".format(app))
        zaza_model.set_application_config(app, s3_config)
    test_config = lifecycle_utils.get_charm_config(fatal=False)
    states = test_config.get('target_deploy_status', {})
    states['trilio-wlm'] = {
        'workload-status': 'blocked',
        'workload-status-message': 'application not trusted'}
    zaza_model.wait_for_application_states(
        states=test_config.get('target_deploy_status', {}),
        timeout=7200)
    zaza_model.block_until_all_units_idle()


def basic_setup():
    """Run basic setup for Trilio apps."""
    backup_target_type = zaza_model.get_application_config(
        'trilio-wlm')['backup-target-type']['value']
    if backup_target_type == "nfs":
        nfs_setup()
    if backup_target_type in ["s3", "experimental-s3"]:
        s3_setup()
    trust_setup()
    license_setup()


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
