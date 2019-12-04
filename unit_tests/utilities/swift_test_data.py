# flake8: noqa

SWIFT_GET_NODES_STDOUT = """
Account         23934cb1850c4d28b1ca113a24c0e46b
Container       zaza-swift-gr-tests-f3129278-container
Object          zaza_test_object.txt


Partition       146
Hash            928c2f8006efeeb4b1164f4cce035887

Server:Port Device      10.5.0.38:6000 loop0
Server:Port Device      10.5.0.4:6000 loop0
Server:Port Device      10.5.0.9:6000 loop0      [Handoff]
Server:Port Device      10.5.0.34:6000 loop0     [Handoff]
Server:Port Device      10.5.0.15:6000 loop0     [Handoff]
Server:Port Device      10.5.0.18:6000 loop0     [Handoff]


curl -g -I -XHEAD "http://10.5.0.38:6000/loop0/146/23934cb1850c4d28b1ca113a24c0e46b/zaza-swift-gr-tests-f3129278-container/zaza_test_object.txt"
curl -g -I -XHEAD "http://10.5.0.4:6000/loop0/146/23934cb1850c4d28b1ca113a24c0e46b/zaza-swift-gr-tests-f3129278-container/zaza_test_object.txt"
curl -g -I -XHEAD "http://10.5.0.9:6000/loop0/146/23934cb1850c4d28b1ca113a24c0e46b/zaza-swift-gr-tests-f3129278-container/zaza_test_object.txt" # [Handoff]
curl -g -I -XHEAD "http://10.5.0.34:6000/loop0/146/23934cb1850c4d28b1ca113a24c0e46b/zaza-swift-gr-tests-f3129278-container/zaza_test_object.txt" # [Handoff]
curl -g -I -XHEAD "http://10.5.0.15:6000/loop0/146/23934cb1850c4d28b1ca113a24c0e46b/zaza-swift-gr-tests-f3129278-container/zaza_test_object.txt" # [Handoff]
curl -g -I -XHEAD "http://10.5.0.18:6000/loop0/146/23934cb1850c4d28b1ca113a24c0e46b/zaza-swift-gr-tests-f3129278-container/zaza_test_object.txt" # [Handoff]


Use your own device location of servers:
such as "export DEVICE=/srv/node"
ssh 10.5.0.38 "ls -lah ${DEVICE:-/srv/node*}/loop0/objects/146/887/928c2f8006efeeb4b1164f4cce035887"
ssh 10.5.0.4 "ls -lah ${DEVICE:-/srv/node*}/loop0/objects/146/887/928c2f8006efeeb4b1164f4cce035887"
ssh 10.5.0.9 "ls -lah ${DEVICE:-/srv/node*}/loop0/objects/146/887/928c2f8006efeeb4b1164f4cce035887" # [Handoff]
ssh 10.5.0.34 "ls -lah ${DEVICE:-/srv/node*}/loop0/objects/146/887/928c2f8006efeeb4b1164f4cce035887" # [Handoff]
ssh 10.5.0.15 "ls -lah ${DEVICE:-/srv/node*}/loop0/objects/146/887/928c2f8006efeeb4b1164f4cce035887" # [Handoff]
ssh 10.5.0.18 "ls -lah ${DEVICE:-/srv/node*}/loop0/objects/146/887/928c2f8006efeeb4b1164f4cce035887" # [Handoff]

note: `/srv/node*` is used as default value of `devices`, the real value is set in the config file on each storage node.
"""

STORAGE_TOPOLOGY = {
    '10.5.0.18': {
        'app_name': 'swift-storage-region1-zone1',
        'unit': "swift-storage-region1-zone1/0",
        'region': 1,
        'zone': 1},
    '10.5.0.34': {
        'app_name': 'swift-storage-region1-zone2',
        'unit': "swift-storage-region1-zone2/0",
        'region': 1,
        'zone': 2},
    '10.5.0.4': {
        'app_name': 'swift-storage-region1-zone3',
        'unit': "swift-storage-region1-zone3/0",
        'region': 1,
        'zone': 3},
    '10.5.0.9': {
        'app_name': 'swift-storage-region2-zone1',
        'unit': "swift-storage-region2-zone1/0",
        'region': 2,
        'zone': 1},
    '10.5.0.15': {
        'app_name': 'swift-storage-region2-zone2',
        'unit': "swift-storage-region2-zone2/0",
        'region': 2, 'zone': 2},
    '10.5.0.38': {
        'app_name': 'swift-storage-region2-zone3',
        'unit': "swift-storage-region2-zone3/0",
        'region': 2,
        'zone': 3}}
