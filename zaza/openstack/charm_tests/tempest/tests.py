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

"""Code for running tempest tests."""

import os
import subprocess

import zaza
import zaza.charm_lifecycle.utils
import zaza.charm_lifecycle.test
import tempfile


class TempestTest():
    """Tempest test class."""

    test_runner = zaza.charm_lifecycle.test.DIRECT

    def run(self):
        """Run tempest tests as specified in tests/tests.yaml.

        Test keys are parsed from ['tests_options']['tempest']['model'], where
        valid test keys are: smoke (bool), whitelist (list of tests), blacklist
        (list of tests), and regex (list of regex's).

        :returns: Status of tempest run
        :rtype: bool
        """
        charm_config = zaza.charm_lifecycle.utils.get_charm_config()
        tempest_options = ['tempest', 'run', '--workspace',
                           'tempest-workspace', '--config',
                           'tempest-workspace/etc/tempest.conf']
        for model_alias in zaza.model.get_juju_model_aliases().keys():
            tempest_test_key = model_alias
            if model_alias == zaza.charm_lifecycle.utils.DEFAULT_MODEL_ALIAS:
                tempest_test_key = 'default'
            config = charm_config['tests_options']['tempest'][tempest_test_key]
            if config.get('smoke'):
                tempest_options.extend(['--smoke'])
            if config.get('regex'):
                tempest_options.extend(
                    ['--regex',
                     ' '.join([reg for reg in config.get('regex')])])
            if config.get('black-regex'):
                tempest_options.extend(
                    ['--black-regex',
                     ' '.join([reg for reg in config.get('black-regex')])])
            with tempfile.TemporaryDirectory() as tmpdirname:
                if config.get('whitelist'):
                    white_file = os.path.join(tmpdirname, 'white.cfg')
                    with open(white_file, 'w') as f:
                        f.write('\n'.join(config.get('whitelist')))
                        f.write('\n')
                    tempest_options.extend(['--whitelist-file', white_file])
                if config.get('blacklist'):
                    black_file = os.path.join(tmpdirname, 'black.cfg')
                    with open(black_file, 'w') as f:
                        f.write('\n'.join(config.get('blacklist')))
                        f.write('\n')
                    tempest_options.extend(['--blacklist-file', black_file])
                print(tempest_options)
                try:
                    subprocess.check_call(tempest_options)
                except subprocess.CalledProcessError:
                    return False
        return True
