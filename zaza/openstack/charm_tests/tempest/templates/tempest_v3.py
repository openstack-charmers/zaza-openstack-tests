file_contents = """
[DEFAULT]
debug = true
use_stderr = false
log_file = tempest.log

[auth]
test_accounts_file = accounts.yaml
default_credentials_domain_name = admin_domain
admin_username = admin
admin_project_name = admin
admin_password = openstack
admin_domain_name = admin_domain

[compute]
image_ref = {image_id}
image_ref_alt = {image_alt_id}
flavor_ref = 7
flavor_ref_alt = 8
min_compute_nodes = 3

# TODO: review this as its release specific
# min_microversion = 2.2
# max_microversion = latest

[compute-feature-enabled]
console_output = true
resize = true
live_migration = true
block_migration_for_live_migration = true
attach_encrypted_volume = false

[identity]
uri = {proto}://{keystone}:5000/v2.0
uri_v3 = {proto}://{keystone}:5000/v3
auth_version = v3
admin_role = Admin
region = RegionOne
default_domain_id = {default_domain_id}
admin_domain_scope = true

[identity-feature-enabled]
api_v2 = false
api_v3 = true

[image]
http_image = http://{os_test_swift_ip}:80/swift/v1/images/cirros-0.3.4-x86_64-uec.tar.gz

[network]
project_network_cidr = {os_test_cidr_priv}
public_network_id = {ext_net}
dns_servers = {os_test_nameserver}
project_networks_reachable = false

[network-feature-enabled]
ipv6 = false

[orchestration]
stack_owner_role = Admin
instance_type = m1.small
keypair_name = testkey

[oslo_concurrency]
lock_path = /tmp

[scenario]
img_dir = /home/ubuntu/images
img_file = cirros-0.3.4-x86_64-disk.img
img_container_format = bare
img_disk_format = qcow2

[validation]
run_validation = true
image_ssh_user = cirros

[service_available]
ceilometer = true
cinder = true
glance = true
heat = true
horizon = true
ironic = false
neutron = true
nova = true
sahara = false
swift = true
trove = false
zaqar = false

[volume]
backend_names = cinder-ceph
storage_protocol = ceph

[volume-feature-enabled]
backup = false"""
