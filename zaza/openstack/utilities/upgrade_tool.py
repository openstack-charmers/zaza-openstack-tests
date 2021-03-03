# Copyright 2021 Canonical Ltd.
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

"""Helper application to upgrade charms, openstack and ubuntu-series."""
import argparse
import asyncio
import logging
import os
import sys
import yaml

import zaza.utilities.cli as cli_utils


def do_charm_upgrade(args):
    print("TODO: charm upgrade")
    pass


def do_openstack_upgrade(args):
    print("TODO: openstack upgrade")
    pass


def do_series_upgrade(args):
    dry_run_str = "DRY_RUN: " if args.dry_run else ""
    print(f"{dry_run_str}Do a series upgrade with {args.application}")



def parse_args(args):
    """Parse command line arguments.

    :param args: List of configure functions functions
    :type list: [str1, str2,...] List of command line arguments
    :returns: Parsed arguments
    :rtype: Namespace
    """
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(
        title="Type of upgrade to perform (charm, openstack, series)",
        dest="upgrade_type",
        metavar="UPGRADE_TYPE",
        help='Type of upgrade to perform help')

    # create upgrade-charm subparser
    parser_upgrade_charm = subparsers.add_parser(
        "charm",
        help='Do a charm upgrade by application.')
    parser_upgrade_charm.add_argument(
        'application_name',
        metavar='APPLICATION',
        type=str,
        help="The application name to upgrade.")

    # create the openstack-upgrade subparser
    parser_openstack_upgrade = subparsers.add_parser(
        "openstack",
        help='Do an openstack upgrade by application.')
    parser_openstack_upgrade.add_argument(
        'application_name',
        metavar='APPLICATION',
        type=str,
        help='The application to openstack upgrade.  Note that the command '
             'determines the current version and picks the next if it is '
             'available.')
    parser_openstack_upgrade.add_argument(
        '--concurrently',
        dest='do_concurrent_upgrade',
        action='store_true',
        help='Force a concurrent upgrade, rather than default for application')
    parser_openstack_upgrade.add_argument(
        '--no-pause-non-leaders',
        dest='no_pause_not_leaders',
        action='store_true',
        help="Don't bother pausing the non leaders, otherwise default for "
             "application.")
    parser_openstack_upgrade.add_argument(
        '--no-pause-subordinates',
        dest='no_pause_subordinates',
        action='store_true',
        help="Don't pause the subordinates, otherwise default for "
             "application.")

    # create the Ubuntu series-upgrade subparser
    ubuntu_openstack_upgrade = subparsers.add_parser(
        "series",
        help='Do an Ubuntu series upgrade by machine.')
    ubuntu_openstack_upgrade.add_argument(
        'application',
        metavar='APPLICATION',
        type=str,
        help='The application to upgrade.')
    ubuntu_openstack_upgrade.add_argument(
        '--concurrently',
        dest='do_concurrent_upgrade',
        action='store_true',
        help='Force a concurrent upgrade, rather than default for application')
    ubuntu_openstack_upgrade.add_argument(
        '--no-pause-non-leaders',
        dest='no_pause_not_leaders',
        action='store_true',
        help="Don't bother pausing the non leaders, otherwise default for "
             "application.")
    ubuntu_openstack_upgrade.add_argument(
        '--no-pause-subordinates',
        dest='no_pause_subordinates',
        action='store_true',
        help="Don't pause the subordinates, otherwise default for "
             "application.")

    parser.add_argument('-m', '--model', dest='model',
                        help='The model to work against.',
                        action='store_true')
    parser.add_argument('--dry-run', dest='dry_run',
                        help='Pretend to do the upgrade. Just print what '
                             'would be done',
                        action='store_true')
    parser.add_argument('--log', dest='loglevel',
                        help='Loglevel [DEBUG|INFO|WARN|ERROR|CRITICAL]')
    parser.set_defaults(dry_run=False,
                        loglevel='INFO')
    result = parser.parse_args(args)
    if not result.upgrade_type:
        parser.print_usage()
        sys.exit(1)
    return result


def main():
    """Run the zot-upgrade-tool helper."""
    args = parse_args(sys.argv[1:])

    cli_utils.setup_logging(log_level=args.loglevel.upper())

    # Run the upgrade: note it's just a handy way of doing a case statement.
    {
        'charm': do_charm_upgrade,
        'openstack': do_openstack_upgrade,
        'series': do_series_upgrade,
    }[args.upgrade_type](args)

    asyncio.get_event_loop().close()
