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
import tempfile


# The temporary directory can't be used when juju's snap is installed in strict
# mode, so zaza-openstack-tests changes the default tmp directory to the
# directory referenced by TEST_TMPDIR otherwise a directory is created under
# the user's home.
def _set_tmpdir():
    tmpdir = os.environ.get('TEST_TMPDIR')

    if tmpdir and os.path.exists(tmpdir) and os.path.isdir(tmpdir):
        tempfile.tempdir = tmpdir
    else:
        tmpdir = os.path.expanduser('~/tmp')
        if not os.path.isdir(tmpdir):
            os.mkdir(tmpdir, 0o770)
        tempfile.tempdir = tmpdir


_set_tmpdir()
