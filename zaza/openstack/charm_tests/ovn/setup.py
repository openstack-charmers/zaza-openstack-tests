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

"""Code for configuring OVN tests."""

import logging

import zaza

import zaza.openstack.charm_tests.test_utils as test_utils


class _OVNSetupHelper(test_utils.BaseCharmTest):
    """Helper class to get at the common `config_change` helper."""

    @staticmethod
    def _get_instance_mtu_from_global_physnet_mtu():
        """Calculate instance mtu from Neutron API global-physnet-mtu.

        :returns: Value for instance mtu after migration.
        :rtype: int
        """
        n_api_config = zaza.model.get_application_config('neutron-api')

        # NOTE: we would have to adjust this calculation if we use IPv6 tunnel
        # endpoints
        GENEVE_ENCAP_OVERHEAD = 38
        IP4_HEADER_SIZE = 20
        return int(n_api_config['global-physnet-mtu']['value']) - (
            GENEVE_ENCAP_OVERHEAD + IP4_HEADER_SIZE)

    def _configure_apps(self, apps, cfg,
                        first_match_raise_if_none_found=False):
        """Conditionally configure a set of applications.

        :param apps: Applications.
        :type apps: Iterator[str]
        :param cfg: Configuration to apply.
        :type cfg: Dict[str,any]
        :param first_match_raise_if_none_found: When set the method will
                                                configure the first application
                                                it finds in the model and raise
                                                an exception if none are found.
        :type first_match_raise_if_none_found: bool
        :raises: RuntimeError
        """
        for app in apps:
            try:
                zaza.model.get_application(app)
                for k, v in cfg.items():
                    logging.info('Setting `{}` to "{}" on "{}"...'
                                 .format(k, v, app))
                    with self.config_change(cfg, cfg, app):
                        # The intent here is to change the config and not
                        # restore it. We accomplish that by passing in the same
                        # value for default and alternate.
                        #
                        # The reason for using the `config_change` helper for
                        # this is that it already deals with all the
                        # permutations of config already being set etc and does
                        # not get into trouble if the test bundle already has
                        # the values we try to set.
                        if first_match_raise_if_none_found:
                            break
                        else:
                            continue
                else:
                    if first_match_raise_if_none_found:
                        raise RuntimeError(
                            'None of the expected apps ({}) are present in '
                            'the model.'
                            .format(apps)
                        )
            except KeyError:
                pass

    def configure_ngw_novs(self):
        """Configure n-ovs and n-gw units."""
        cfg = {
            # To be able to have instances successfully survive the migration
            # without communication issues we need to lower the MTU announced
            # to instances prior to migration.
            #
            # NOTE: In a real world scenario the end user would configure the
            # MTU at least 24 hrs prior to doing the migration to allow
            # instances to reconfigure as they renew the DHCP lease.
            #
            # NOTE: For classic n-gw topologies the `instance-mtu` config
            # is a NOOP on neutron-openvswitch units, but that is ok.
            'instance-mtu': self._get_instance_mtu_from_global_physnet_mtu()
        }
        apps = ('neutron-gateway', 'neutron-openvswitch')
        self._configure_apps(apps, cfg)
        cfg_ovs = {
            # To be able to successfully clean up after the Neutron agents we
            # need to use the 'openvswitch' `firewall-driver`.
            'firewall-driver': 'openvswitch',
        }
        self._configure_apps(('neutron-openvswitch',), cfg_ovs)

    def configure_ovn_mappings(self):
        """Copy mappings from n-gw or n-ovs application."""
        dst_apps = ('ovn-dedicated-chassis', 'ovn-chassis')
        src_apps = ('neutron-gateway', 'neutron-openvswitch')
        ovn_cfg = {}
        for app in src_apps:
            try:
                app_cfg = zaza.model.get_application_config(app)
                ovn_cfg['bridge-interface-mappings'] = app_cfg[
                    'data-port']['value']
                ovn_cfg['ovn-bridge-mappings'] = app_cfg[
                    'bridge-mappings']['value']
                # Use values from neutron-gateway when present, otherwise use
                # values from neutron-openvswitch
                break
            except KeyError:
                pass
        else:
            raise RuntimeError(
                'None of the expected apps ({}) are present in the model.'
                .format(src_apps)
            )

        self._configure_apps(
            dst_apps, ovn_cfg, first_match_raise_if_none_found=True)


def pre_migration_configuration():
    """Perform pre-migration configuration steps.

    NOTE: Doing the configuration post-deploy and after doing initial network
    configuration is an important part of the test as we need to prove that our
    end users would be successful in doing this in the wild.
    """
    # we use a helper class to leverage common setup code and the
    # `config_change` helper
    helper = _OVNSetupHelper()
    helper.setUpClass()
    # Configure `firewall-driver` and `instance-mtu` on n-gw and n-ovs units.
    helper.configure_ngw_novs()
    # Copy mappings from n-gw or n-ovs application to ovn-dedicated-chassis or
    # ovn-chassis.
    helper.configure_ovn_mappings()
