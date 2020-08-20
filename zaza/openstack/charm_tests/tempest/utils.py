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

"""Utility code for working with tempest workspaces."""

import os
from pathlib import Path
import shutil
import subprocess

import zaza.model as model


def get_workspace():
    """Get tempest workspace name and path.

    :returns: A tuple containing tempest workspace name and workspace path
    :rtype: Tuple[str, str]
    """
    home = str(Path.home())
    workspace_name = model.get_juju_model()
    workspace_path = os.path.join(home, '.tempest', workspace_name)
    return (workspace_name, workspace_path)


def destroy_workspace(workspace_name, workspace_path):
    """Delete tempest workspace.

    :param workspace_name: name of workspace
    :type workspace_name: str
    :param workspace_path: directory path where workspace is stored
    :type workspace_path: str
    :returns: None
    :rtype: None
    """
    try:
        subprocess.check_call(['tempest', 'workspace', 'remove', '--rmdir',
                               '--name', workspace_name])
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    if os.path.isdir(workspace_path):
        shutil.rmtree(workspace_path)


def init_workspace(workspace_path):
    """Initialize tempest workspace.

    :param workspace_path: directory path where workspace is stored
    :type workspace_path: str
    :returns: None
    :rtype: None
    """
    try:
        subprocess.check_call(['tempest', 'init', workspace_path])
    except subprocess.CalledProcessError:
        pass
