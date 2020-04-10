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

import mock
import unittest

import zaza.openstack.charm_tests.rabbitmq_server.utils as rabbit_utils


class TestRabbitUtils(unittest.TestCase):
    """Test class to encapsulate testing Mysql test utils."""

    @mock.patch.object(rabbit_utils.zaza, 'model')
    def test_rabbit_complete_cluster_series_upgrade(self, mock_model):
        run_action_on_leader = mock.MagicMock()
        mock_model.run_action_on_leader = run_action_on_leader
        rabbit_utils.complete_cluster_series_upgrade()
        run_action_on_leader.assert_called_once_with(
            'rabbitmq-server',
            'complete-cluster-series-upgrade',
            action_params={})
