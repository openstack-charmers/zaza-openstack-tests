# Zaza OpenStack Tests

This is a test library designed to be shared between the OpenStack Charms to improve code-reuse among the various components.

## Usage

This example is taken from the pacemaker-remote charm's tests.yaml:

```yaml
charm_name: pacemaker-remote
tests:
  - zaza.openstack.charm_tests.pacemaker_remote.tests.PacemakerRemoteTest
configure:
  - zaza.charm_tests.noop.setup.basic_setup
gate_bundles:
  - basic
smoke_bundles:
  - basic
```

test-requirements.txt:

```
git+https://github.com/openstack-charmers/zaza.git#egg=zaza
git+https://github.com/openstack-charmers/zaza-openstack-tests.git#egg=zaza.openstack
```

## Configuration

Zaza-openstack-test uses environment variables to configure the tests:

| Env var                      | Description                                               | Default Value                                                                                         |
|------------------------------|-----------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| `FUNCTEST_AMPHORA_LOCATION`  |                                                           | `http://tarballs.openstack.org/octavia/test-images/test-only-amphora-x64-haproxy-ubuntu-xenial.qcow2` |
| `MOJO_LOCAL_DIR`             |                                                           |                                                                                                       |
| `OS_AUTH_URL`                | Undercloud authentication url                             |                                                                                                       |
| `OS_PASSWORD`                | Undercloud password                                       |                                                                                                       |
| `OS_REGION_NAME`             | Undercloud region name                                    |                                                                                                       |
| `OS_TENANT_NAME`             | Undercloud tenant name                                    |                                                                                                       |
| `OS_USERNAME`                | Undercloud username                                       |                                                                                                       |
| `TEST_ARISTA_IMAGE_LOCAL`    |                                                           | `/tmp/arista-cvx-virt-test.qcow2`                                                                     |
| `TEST_ARISTA_IMAGE_REMOTE`   |                                                           |                                                                                                       |
| `TEST_BIONIC_IMAGE_NAME`     | Name of bionic image                                      | `bionic`                                                                                              |
| `TEST_CACERT`                |                                                           |                                                                                                       |
| `TEST_CAKEY`                 |                                                           |                                                                                                       |
| `TEST_CERT`                  |                                                           |                                                                                                       |
| `TEST_CIDR_EXT`              |                                                           |                                                                                                       |
| `TEST_CIDR_EXT`              |                                                           |                                                                                                       |
| `TEST_CIRROS_IMAGE_NAME`     | Name of cirros image                                      | `cirros`                                                                                              |
| `TEST_EXT_NET_SUBNET`        | Name of external subnet                                   | `ext_net_subnet`                                                                                      |
| `TEST_EXT_NET`               | Name of external network                                  | `ext_net`                                                                                             |
| `TEST_FIP_RANGE`             | Undercloud fip range                                      |                                                                                                       |
| `TEST_FOCAL_IMAGE_NAME`      | Name of focal image                                       | `focal`                                                                                               |
| `TEST_GATEWAY`               | Undercloud gateway                                        |                                                                                                       |
| `TEST_IRONIC_DEPLOY_INITRD`  |                                                           |                                                                                                       |
| `TEST_IRONIC_DEPLOY_VMLINUZ` |                                                           |                                                                                                       |
| `TEST_IRONIC_RAW_BM_IMAGE`   |                                                           |                                                                                                       |
| `TEST_JAMMY_IMAGE_NAME`      | Name of jammy image                                       | `jammy`                                                                                               |
| `TEST_KEYPAIR_NAME`          | Name of keypair                                           | `zaza`                                                                                                |
| `TEST_KEY`                   |                                                           |                                                                                                       |
| `TEST_MAGNUM_QCOW2_IMAGE_URL`|                                                           |                                                                                                       |
| `TEST_NAME_SERVER`           | Undercloud name server                                    |                                                                                                       |
| `TEST_NET_ID`                | Undercloud net id                                         |                                                                                                       |
| `TEST_NVIDIA_VGPU_HOST_SW`   |                                                           |                                                                                                       |
| `TEST_PRIVATE_NET_SUBNET`    | Name of private subnet                                    | `private_subnet`                                                                                      |
| `TEST_PRIVATE_NET`           | Name of private network                                   | `private`                                                                                             |
| `TEST_PRIVKEY`               | Path to private key corresponding to `TEST_KEYPAIR_NAME`  |                                                                                                       |
| `TEST_PROVIDER_ROUTER`       | Name of private-external router                           | `provider-router`                                                                                     |
| `TEST_TRILIO_LICENSE`        |                                                           |                                                                                                       |
| `TEST_VIP00`                 |                                                           |                                                                                                       |
