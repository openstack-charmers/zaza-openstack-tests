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

| Env var                      | Description                                               | Default Value        |
|------------------------------|-----------------------------------------------------------|----------------------|
| `TEST_EXT_NET`               | Name of external network                                  | `ext_net`            |
| `TEST_EXT_NET_SUBNET`        | Name of external subnet                                   | `ext_net_subnet`     |
| `TEST_PRIVATE_NET`           | Name of private network                                   | `private`            |
| `TEST_PRIVATE_NET_SUBNET`    | Name of private subnet                                    | `private_subnet`     |
| `TEST_PROVIDER_ROUTER`       | Name of private-external router                           | `provider-router`    |
| `TEST_CIRROS_IMAGE_NAME`     | Name of cirros image                                      | `cirros`             |
| `TEST_BIONIC_IMAGE_NAME`     | Name of bionic image                                      | `bionic`             |
| `TEST_FOCAL_IMAGE_NAME`      | Name of focal image                                       | `focal`              |
| `TEST_JAMMY_IMAGE_NAME`      | Name of jammy image                                       | `jammy`              |
| `TEST_PRIVKEY`               | Path to private key corresponding to `TEST_KEYPAIR_NAME`  |                      |
| `TEST_KEYPAIR_NAME`          | Name of keypair                                           | `zaza`               |
