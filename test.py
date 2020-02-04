#!/usr/bin/env python3

from zaza.openstack.utilities import (
    cli as cli_utils,
    openstack as openstack_utils,
    openstack_upgrade as upgrade_utils,
)


applications = []
for group in ['Core Identity', 'Storage', 'Control Plane', 'Compute']:
    applications.extend(upgrade_utils.SERVICE_GROUPS[group])
print(applications)
