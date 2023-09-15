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

"""Data for nova tests."""

import os

FLAVORS = {
    'm1.tiny': {
        'flavorid': 1,
        'ram': 512,
        'disk': 1,
        'vcpus': 1},
    'm1.small': {
        'flavorid': 2,
        'ram': 2048,
        'disk': 20,
        'vcpus': 1},
    'm1.medium': {
        'flavorid': 3,
        'ram': 4096,
        'disk': 40,
        'vcpus': 2},
    'm1.large': {
        'flavorid': 4,
        'ram': 8192,
        'disk': 40,
        'vcpus': 4},
    'm1.tempest': {
        'flavorid': 6,
        'ram': 256,
        'disk': 1,
        'vcpus': 1},
    'm2.tempest': {
        'flavorid': 7,
        'ram': 512,
        'disk': 1,
        'vcpus': 1},
    'vtpm-1.2': {
        'flavorid': 'auto',
        'ram': 512,
        'disk': 5,
        'vcpus': 1,
        'extra-specs': {
            'hw:tpm_version': '1.2',
            'hw:tpm_model': 'tpm-tis',
        },
    },
    'vtpm-2': {
        'flavorid': 'auto',
        'ram': 512,
        'disk': 5,
        'vcpus': 1,
        'extra-specs': {
            'hw:tpm_version': '2.0',
            'hw:tpm_model': 'tpm-crb',
        },
    },
    'hugepages': {
        'flavorid': 'auto',
        'ram': 1024,
        'disk': 20,
        'vcpus': 1,
        'extra-specs': {
            'hw:mem_page_size': 'large',
        },
    },
}
KEYPAIR_NAME = os.environ.get('TEST_KEYPAIR_NAME', 'zaza')
