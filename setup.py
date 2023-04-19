# -*- coding: utf-8 -*-

# Copyright 2018 Canonical Ltd.
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

"""Module used to setup the zaza framework tests."""

from __future__ import print_function

import os
import sys
from setuptools import setup, find_namespace_packages
from setuptools.command.test import test as TestCommand

version = "0.0.1.dev1"
install_require = [
    'futurist<2.0.0',
    'async_generator',
    'boto3',

    # pyopenssl depends on a newer version of cryptography since 22.1.0
    # TypeError: deprecated() got an unexpected keyword argument 'name'
    # https://github.com/pyca/pyopenssl/commit/a145fc3bc6d2e943434beb2f04bbf9b18930296f
    'pyopenssl<22.1.0',

    # Newer versions require a Rust compiler to build, see
    # * https://github.com/openstack-charmers/zaza/issues/421
    # * https://mail.python.org/pipermail/cryptography-dev/2021-January/001003.html
    'cryptography<3.4',

    'dnspython',
    'hvac<0.7.0',
    'jinja2',
    'lxml',
    'PyYAML',
    'tenacity',
    'oslo.config<6.12.0',
    'aodhclient',
    'gnocchiclient>=7.0.5,<8.0.0',
    'pika>=1.1.0,<2.0.0',
    'python-barbicanclient>=4.0.1,<5.0.0',
    'python-cloudkittyclient',
    'python-designateclient>=1.5,<3.0.0',
    'python-heatclient<2.0.0',
    'python-ironicclient',
    'python-glanceclient',
    'python-keystoneclient<3.22.0',
    'python-magnumclient',
    'python-manilaclient<2.0.0',
    'python-novaclient<16.0.0',
    'python-neutronclient<7.0.0',
    'python-octaviaclient<1.11.0',
    'python-ceilometerclient',
    'python-cinderclient<6.0.0',
    'python-swiftclient<3.9.0',
    # 'zaza@git+https://github.com/openstack-charmers/zaza.git#egg=zaza',
    'zaza',
]

tests_require = [
    'tox >= 2.3.1',
]


class Tox(TestCommand):
    """Tox class."""

    user_options = [('tox-args=', 'a', "Arguments to pass to tox")]

    def initialize_options(self):
        """Initialize options."""
        TestCommand.initialize_options(self)
        self.tox_args = None

    def finalize_options(self):
        """Finalize options."""
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        """Run the tests."""
        # import here, cause outside the eggs aren't loaded
        import tox
        import shlex
        args = self.tox_args
        # remove the 'test' arg from argv as tox passes it to ostestr which
        # breaks it.
        sys.argv.pop()
        if args:
            args = shlex.split(self.tox_args)
        errno = tox.cmdline(args=args)
        sys.exit(errno)


if sys.argv[-1] == 'publish':
    os.system("python setup.py sdist upload")
    os.system("python setup.py bdist_wheel upload")
    sys.exit()


if sys.argv[-1] == 'tag':
    os.system("git tag -a %s -m 'version %s'" % (version, version))
    os.system("git push --tags")
    sys.exit()


setup(
    license='Apache-2.0: http://www.apache.org/licenses/LICENSE-2.0',
    # name='zaza-openstack-tests',
    name='zaza.openstack',
    packages=find_namespace_packages(include=['zaza.*'], exclude=["unit_tests"]),
    zip_safe=False,
    include_package_data=True,
    cmdclass={'test': Tox},
    install_requires=install_require,
    extras_require={
        'testing': tests_require,
    },
    tests_require=tests_require,
)
