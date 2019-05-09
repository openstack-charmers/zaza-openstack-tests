# Zaza OpenStack Tests

This is a test library designed to be shared between the OpenStack Charms to improve code-reuse among the various components.

## Usage

This example is taken from the pacemaker-remote charm's tests.yaml:

```yaml
charm_name: pacemaker-remote
tests:
  - zaza.openstack.charm_tests.pacemaker_remote.tests.PacemakerRemoteTest
configure:
  - zaza.openstack.charm_tests.noop.setup.basic_setup
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