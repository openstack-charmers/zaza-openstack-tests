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

import logging
import os
import subprocess
import tenacity

import zaza
import zaza.charm_lifecycle.utils
import zaza.charm_lifecycle.test
import zaza.openstack.charm_tests.tempest.utils as tempest_utils
import zaza.charm_lifecycle.utils as lifecycle_utils
import tempfile


class TempestTestBase():
    """Tempest test base class."""

    test_runner = zaza.charm_lifecycle.test.DIRECT

    def run(self):
        """Run tempest tests as specified in tests/tests.yaml.

        Test keys are parsed from ['tests_options']['tempest']['model'], where
        valid test keys are:
          - smoke (bool)
          - include-list (list of tests)
          - exclude-list (list of tests)
          - regex (list of regex's)
          - exclude-regex (list of regex's)
          - keep-workspace (bool)

        :returns: Status of tempest run
        :rtype: bool
        """
        result = True
        charm_config = zaza.charm_lifecycle.utils.get_charm_config()
        workspace_name, workspace_path = tempest_utils.get_workspace()
        tempest_options = ['tempest', 'run', '--workspace',
                           workspace_name, '--config',
                           os.path.join(workspace_path, 'etc/tempest.conf')]
        for model_alias in zaza.model.get_juju_model_aliases().keys():
            tempest_test_key = model_alias
            if model_alias == zaza.charm_lifecycle.utils.DEFAULT_MODEL_ALIAS:
                tempest_test_key = 'default'
            config = charm_config['tests_options']['tempest'][tempest_test_key]
            smoke = config.get('smoke')
            if smoke and smoke is True:
                tempest_options.extend(['--smoke'])
            if config.get('regex'):
                tempest_options.extend(
                    ['--regex',
                     ' '.join([reg for reg in config.get('regex')])])
            if config.get('exclude-regex'):
                tempest_options.extend(
                    ['--exclude-regex',
                     ' '.join([reg for reg in config.get('exclude-regex')])])
            with tempfile.TemporaryDirectory() as tmpdirname:
                if config.get('include-list'):
                    include_file = os.path.join(tmpdirname, 'include.cfg')
                    with open(include_file, 'w') as f:
                        f.write('\n'.join(config.get('include-list')))
                        f.write('\n')
                    tempest_options.extend(['--include-list', include_file])
                if config.get('exclude-list'):
                    exclude_file = os.path.join(tmpdirname, 'exclude.cfg')
                    with open(exclude_file, 'w') as f:
                        f.write('\n'.join(config.get('exclude-list')))
                        f.write('\n')
                    tempest_options.extend(['--exclude-list', exclude_file])
                print(tempest_options)
                try:
                    subprocess.check_call(tempest_options)
                except subprocess.CalledProcessError:
                    result = False
                    break
        keep_workspace = config.get('keep-workspace')
        if not keep_workspace or keep_workspace is not True:
            tempest_utils.destroy_workspace(workspace_name, workspace_path)
        return result


class TempestTestWithKeystoneV2(TempestTestBase):
    """Tempest test class to validate an OpenStack setup with Keystone V2."""

    def run(self):
        """Run tempest tests as specified in tests/tests.yaml.

        See TempestTestBase.run() for the available test options.

        :returns: Status of tempest run
        :rtype: bool
        """
        tempest_utils.render_tempest_config_keystone_v2()
        return super().run()


class TempestTestWithKeystoneV3(TempestTestBase):
    """Tempest test class to validate an OpenStack setup with Keystone V2."""

    def run(self):
        """Run tempest tests as specified in tests/tests.yaml.

        See TempestTestBase.run() for the available test options.

        :returns: Status of tempest run
        :rtype: bool
        """
        tempest_utils.render_tempest_config_keystone_v3()
        return super().run()


class TempestTestWithKeystoneMinimal(TempestTestBase):
    """Tempest test class to validate an OpenStack setup with Keystone V2."""

    def run(self):
        """Run tempest tests as specified in tests/tests.yaml.

        Allow test to run even if some components are missing (like
        external network setup).
        See TempestTestBase.run() for the available test options.

        :returns: Status of tempest run
        :rtype: bool
        """
        tempest_utils.render_tempest_config_keystone_v3(minimal=True)
        return super().run()


class TempestTestScaleK8SBase(TempestTestBase):
    """Tempest test class to validate an OpenStack setup after scaling."""

    @property
    def application_name(self):
        """Name of application to scale."""
        raise NotImplementedError()

    @property
    def expected_statuses(self):
        """Collect expected statuses from config."""
        test_config = lifecycle_utils.get_charm_config(fatal=False)
        return test_config.get("target_deploy_status", {})

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, max=60),
                    reraise=True, stop=tenacity.stop_after_attempt(8))
    def wait_for_dead_units(self, application_name, dead_count):
        """Check that dying units have appeared.

        Due to Bug: #2009503 the old units remain in the model but
        are marked as dying
        """
        logging.warning(
            "Waiting for dying units to work around Bug #2009503. If this is "
            "fixed please update this test")
        app_status = zaza.model.get_status()['applications'][
            application_name]
        dead_units = [ustatus
                      for ustatus in app_status['units'].values()
                      if ustatus.agent_status.life == 'dying']
        assert len(dead_units) == dead_count

    def run(self):
        """Run tempest tests as specified in tests/tests.yaml.

        Allow test to run even if some components are missing (like
        external network setup).
        See TempestTestBase.run() for the available test options.

        :returns: Status of tempest run
        :rtype: bool
        """
        tempest_utils.render_tempest_config_keystone_v3(minimal=True)
        if not super().run():
            return False

        logging.info("Adding unit ...")
        zaza.model.scale(self.application_name, scale_change=1, wait=True)
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()
        logging.info("Wait for status ready ...")
        zaza.model.wait_for_application_states(states=self.expected_statuses)
        tempest_utils.render_tempest_config_keystone_v3(minimal=True)
        if not super().run():
            return False

        # Cannot use normal wait as removed units remain in juju status
        # Bug: #2009503
        logging.info("Scaling back ...")
        zaza.model.scale(self.application_name, scale_change=-1, wait=False)
        self.wait_for_dead_units(self.application_name, 1)
        logging.info("Wait till model is idle ...")
        zaza.model.block_until_all_units_idle()
        logging.info("Wait for status ready ...")
        zaza.model.wait_for_application_states(states=self.expected_statuses)
        tempest_utils.render_tempest_config_keystone_v3(minimal=True)
        return super().run()


class TempestTest(TempestTestBase):
    """Tempest test class.

    Requires running one of the render_tempest_config_keystone_v? Zaza
    configuration steps before.
    """

    def run(self):
        """Run tempest tests as specified in tests/tests.yaml.

        See TempestTestBase.run() for the available test options.

        :returns: Status of tempest run
        :rtype: bool
        """
        logging.warning(
            'The TempestTest test class is deprecated. Please use one of the '
            'TempestTestWithKeystoneV? test classes instead.')
        return super().run()
