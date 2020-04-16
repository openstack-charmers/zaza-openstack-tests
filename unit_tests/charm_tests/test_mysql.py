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

import asyncio
import mock
import unittest
import sys

import zaza.openstack.charm_tests.mysql.utils as mysql_utils


class TestMysqlUtils(unittest.TestCase):
    """Test class to encapsulate testing Mysql test utils."""

    def setUp(self):
        super(TestMysqlUtils, self).setUp()
        if sys.version_info < (3, 6, 0):
            raise unittest.SkipTest("Can't AsyncMock in py35")

    @mock.patch.object(mysql_utils, 'model')
    def test_mysql_complete_cluster_series_upgrade(self, mock_model):
        run_action_on_leader = mock.AsyncMock()
        mock_model.async_run_action_on_leader = run_action_on_leader
        asyncio.get_event_loop().run_until_complete(
            mysql_utils.complete_cluster_series_upgrade())
        run_action_on_leader.assert_called_once_with(
            'mysql',
            'complete-cluster-series-upgrade',
            action_params={})
