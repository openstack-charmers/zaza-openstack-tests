# Copyright 2024 Canonical Ltd.
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

"""Test zaza.openstack module's __init__ code"""

import tempfile
import unittest

from unittest import mock

import zaza.openstack


class TestInit(unittest.TestCase):
    def setUp(self):
        self.orig_tmpdir = tempfile.tempdir

    def tearDown(self):
        # restore original's value of tempdir
        tempfile.tempdir = self.orig_tmpdir

    @mock.patch('os.environ')
    @mock.patch('os.mkdir')
    @mock.patch('os.path.expanduser')
    @mock.patch('os.path.exists')
    @mock.patch('os.path.isdir')
    def test_init(self, isdir, exists, expanduser, mkdir, environ):

        fake_environ = {}
        environ.get.side_effect = lambda key: fake_environ.get(key)
        exists.return_value = False
        isdir.return_value = False
        expanduser.return_value = '/foo/bar'
        zaza.openstack._set_tmpdir()
        expanduser.assert_called_with('~/tmp')
        mkdir.assert_called_with('/foo/bar', 0o770)
        self.assertEqual(tempfile.tempdir, '/foo/bar')

        expanduser.reset_mock()
        mkdir.reset_mock()
        fake_environ['TEST_TMPDIR'] = '/my/tmpdir'
        exists.return_value = True
        isdir.return_value = True
        zaza.openstack._set_tmpdir()
        expanduser.assert_not_called()
        mkdir.assert_not_called()

        self.assertEqual(tempfile.tempdir, '/my/tmpdir')
