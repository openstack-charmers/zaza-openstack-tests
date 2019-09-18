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

"""Encapsulate policyd testing."""

import logging
import os
import shutil
import tempfile
import zipfile

import zaza.model as zaza_model

import zaza.openstack.charm_tests.test_utils as test_utils


class PolicydTest(test_utils.OpenStackBaseTest):
    """Charm operation tests.

    The policyd test needs some config from the tests.yaml in order to work
    properly.  A top level key of "tests_options".  Under that key is
    'policyd', and then the k:v of 'service': <name>.  e.g. for keystone

    tests_options:
      policyd:
        service: keystone
    """

    @classmethod
    def setUpClass(cls, application_name=None):
        super(PolicydTest, cls).setUpClass(application_name)
        cls._tmp_dir = tempfile.mkdtemp()
        cls._service_name = \
            cls.test_config['tests_options']['policyd']['service']

    @classmethod
    def tearDownClass(cls):
        super(PolicydTest, cls).tearDownClass()
        try:
            shutil.rmtree(cls._tmp_dir, ignore_errors=True)
        except Exception as e:
            logging.error("Removing the policyd tempdir/files failed: {}"
                          .format(str(e)))

    def tearDown(self):
        """Ensure that the policyd config is switched off and the charm is
        stable at the end of the test.
        """
        self._set_config_and_wait(False)

    def _set_config_and_wait(self, state):
        zaza_model.set_application_config(self.application_name,
                                          {"use-policyd-override": state})
        zaza_model.block_until_all_units_idle()

    def _make_zip_file_from(self, name, files):
        """Make a zip file from a dictionary of filename: string.

        :param name: the name of the zip file
        :type name: PathLike
        :param files: a dict of name: string to construct the files from.
        :type files: Dict[str, str]
        :returns: temp file that is the zip file.
        :rtype: PathLike
        """
        path = os.path.join(self._tmp_dir, name)
        with zipfile.ZipFile(path, "w") as zfp:
            for name, contents in files.items():
                zfp.writestr(name, contents)
        return path

    def test_policyd_good_yaml(self):
        # Test that the policyd with a good zipped yaml file puts the yaml file
        # in the right directory
        good = {
            'file1.yaml': "{'rule1': '!'}"
        }
        good_zip_path = self._make_zip_file_from('good.zip', good)
        zaza_model.attach_resource(self.application_name,
                                   'policyd-override',
                                   good_zip_path)
        zaza_model.block_until_all_units_idle()
        self._set_config_and_wait(True)
        # check that the file gets to the right location
        path = os.path.join(
            "/etc", self._service_name, "policy.d", 'file1.yaml')
        zaza_model.block_until_file_has_contents(self.application_name,
                                                 path,
                                                 "'rule1': '!'")
