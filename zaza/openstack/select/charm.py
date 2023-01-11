# Copyright 2023 Canonical Ltd.
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

"""Selector for running centralised charm tests.

This module contains the runner for centralised tests for charms.  This allows
a charm to describe what it is (charm name, branch) and then for the select to
select the appropriate tests to run.

zaza supports a CLI program called `run_module` that accepts a module name and
then passes the remaining parameters (less the --log option) to a function.

This selector should be run as:

    run_module [--log LOG_LEVEL] zaza.openstack.select.charm.run_tests
        <charm>
        <bundle>

The `run_tests` function will then use the charm (say 'keystone') and the
bundle (say 'jammy-yoga') to select the appropriate bundle(s) to run.

The charm tests are in ../bundles/charms/<charm> ==> TEST_DIR

The `TEST_DIR/tests.yaml` provides the phases for deployment and the tests to
run (along with tests options), and the `TEST_DIR/bundles/<bundle>.yaml` is the
bundle to deploy.

By default, the charm under-test is the passed name as `<charm>` and will be
located in the CWD from where the zaza `run_module` command is run from (e.g.
the CWD of the tox.ini); the bundles need to refer to the charm as `./<charm
name>.charm>`.  i.e. the deployment will us
"""

import argparse
import logging
import os
import pathlib

import zaza
import zaza.charm_lifecycle.func_test_runner


def parse_args(args):
    """Parse command line arguments for run_module.

    :param args: List of configure functions functions
    :type list: [str1, str2,...] List of command line arguments
    :returns: Parsed arguments
    :rtype: Namespace
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('charm',
                        help='The charm name to lookup.')
    parser.add_argument('bundle',
                        help='The bundle to load and run against.')
    parser.set_defaults(loglevel='INFO')
    return parser.parse_args(args)


def run_tests(args):
    """Run tests for a charm and branch.

    args[0] is the charm, and args[1] is the branch (if not present, then
    assume to be master).

    Successfully completing the run, results in exit(0).

    :param args: the charm and branch.
    :type args: List[str]
    """
    parsed_args = parse_args(args)
    # test_directory needs to be ../bundles/charms/<charm>
    logging.debug("run_test: here is %s", str(pathlib.Path(__file__)))
    path = (pathlib.Path(__file__) / '..' / '..' / 'bundles' / 'charms' /
            parsed_args.charm)
    path = path.resolve()
    logging.debug("run_test: test_directory path is %s", str(path))
    # check that tests.yaml exists in the path.
    if not (path / 'tests.yaml').exists():
        msg = ("run_tests: {}/tests.yaml doesn't exist; no way to continue"
               .format(str(path)))
        logging.error(msg)
        raise RuntimeError(msg)

    # TODO: need to work out how to reference the local charm
    zaza.charm_lifecycle.func_test_runner.func_test_runner(
        keep_last_model=True,
        keep_all_models=False,
        keep_faulty_model=False,
        smoke=False,
        dev=False,
        bundles=[parsed_args.bundle],
        force=False,
        test_directory=str(path),
        trust=False)

