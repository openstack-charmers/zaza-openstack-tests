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

"""Encapsulate Manila Ganesha testing."""

import logging

from zaza.openstack.charm_tests.manila_ganesha.setup import (
    MANILA_GANESHA_TYPE_NAME,
)

import zaza.openstack.charm_tests.manila.tests as manila_tests
import zaza.model


class ManilaGaneshaTests(manila_tests.ManilaBaseTest):
    """Encapsulate Manila Ganesha tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(ManilaGaneshaTests, cls).setUpClass()
        cls.share_name = 'cephnfsshare1'
        cls.share_type_name = MANILA_GANESHA_TYPE_NAME
        cls.share_protocol = 'nfs'

    def _restart_share_instance(self):
        logging.info('Restarting manila-share and nfs-ganesha')
        # It would be better for thie to derive the application name,
        # manila-ganesha-az1, from deployed instances of the manila-ganesha
        # charm; however, that functionality isn't present yet in zaza, so
        # this is a best-guestimate arrived at by looking for applications
        # with the word 'ganesha' in their names.
        ganeshas = [
            app for app in zaza.model.sync_deployed()
            if 'ganesha' in app and 'mysql' not in app]
        for ganesha in ganeshas:
            for unit in zaza.model.get_units(ganesha):
                # While we really only need to run this on the machine hosting
                # nfs-ganesha and manila-share, running it everywhere isn't
                # harmful. Pacemaker handles restarting the services
                zaza.model.run_on_unit(
                    unit.entity_id,
                    "systemctl stop manila-share nfs-ganesha")
        return True
