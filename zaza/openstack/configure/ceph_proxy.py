"""Module to setup ceph-proxy charm."""

import logging
import zaza.model as model


def setup_ceph_proxy():
    """
    Configure ceph proxy with ceph metadata.

    Fetches admin_keyring and FSID from ceph-mon and
    uses those to configure ceph-proxy.
    """
    raw_admin_keyring = model.run_on_leader(
        "ceph-mon", 'cat /etc/ceph/ceph.client.admin.keyring')["Stdout"]
    admin_keyring = [
        line for line in raw_admin_keyring.split("\n") if "key" in line
    ][0].split(' = ')[-1].rstrip()
    fsid = model.run_on_leader("ceph-mon", "leader-get fsid")["Stdout"]
    cluster_ips = model.get_app_ips("ceph-mon")

    proxy_config = {
        'auth-supported': 'cephx',
        'admin-key': admin_keyring,
        'fsid': fsid,
        'monitor-hosts': ' '.join(cluster_ips)
    }

    logging.debug('Config: {}'.format(proxy_config))

    model.set_application_config("ceph-proxy", proxy_config)
