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

"""OpenStack specific zaza functionality."""
import os


def _set_proxy_vars():
    # Set proxy vars if provided so that all code gets to use it.
    for key, val in os.environ.items():
        if not key.startswith('TEST_') or 'PROXY' not in key:
            continue

        _key = key.partition('TEST_')[2]
        os.environ[_key.lower()] = val


_set_proxy_vars()
