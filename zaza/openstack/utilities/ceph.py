"""Module containing Ceph related utilities."""
import json
import logging

import zaza.model as zaza_model
import zaza.utilities.juju as zaza_juju

import zaza.openstack.utilities.openstack as openstack_utils

REPLICATED_POOL_TYPE = 'replicated'
ERASURE_POOL_TYPE = 'erasure-coded'
REPLICATED_POOL_CODE = 1
ERASURE_POOL_CODE = 3


def get_expected_pools(radosgw=False):
    """Get expected ceph pools.

    Return a list of expected ceph pools in a ceph + cinder + glance
    test scenario, based on OpenStack release and whether ceph radosgw
    is flagged as present or not.
    :param radosgw: If radosgw is used or not
    :type radosgw: boolean
    :returns: List of pools that are expected
    :rtype: list
    """
    current_release = openstack_utils.get_os_release()
    trusty_icehouse = openstack_utils.get_os_release('trusty_icehouse')
    trusty_kilo = openstack_utils.get_os_release('trusty_kilo')
    zesty_ocata = openstack_utils.get_os_release('zesty_ocata')
    if current_release == trusty_icehouse:
        # Icehouse
        pools = [
            'data',
            'metadata',
            'rbd',
            'cinder-ceph',
            'glance'
        ]
    elif (trusty_kilo <= current_release <= zesty_ocata):
        # Kilo through Ocata
        pools = [
            'rbd',
            'cinder-ceph',
            'glance'
        ]
    else:
        # Pike and later
        pools = [
            'cinder-ceph',
            'glance'
        ]

    if radosgw:
        pools.extend([
            '.rgw.root',
            '.rgw.control',
            '.rgw',
            '.rgw.gc',
            '.users.uid'
        ])

    return pools


def get_ceph_pools(unit_name, model_name=None):
    """Get ceph pools.

    Return a dict of ceph pools from a single ceph unit, with
    pool name as keys, pool id as vals.

    :param unit_name: Name of the unit to get the pools on
    :type unit_name: string
    :param model_name: Name of model to operate in
    :type model_name: str
    :returns: Dict of ceph pools
    :rtype: dict
    :raise: zaza_model.CommandRunFailed
    """
    pools = {}
    cmd = 'sudo ceph osd lspools'
    result = zaza_model.run_on_unit(unit_name, cmd, model_name=model_name)
    output = result.get('Stdout').strip()
    code = int(result.get('Code'))
    if code != 0:
        raise zaza_model.CommandRunFailed(cmd, result)

    # Example output: 0 data,1 metadata,2 rbd,3 cinder,4 glance,
    # It can also be something link 0 data\n1 metadata

    # First split on new lines
    osd_pools = str(output).split('\n')
    # If we have a len of 1, no new lines found -> splitting on commas
    if len(osd_pools) == 1:
        osd_pools = osd_pools[0].split(',')
    for pool in osd_pools:
        pool_id_name = pool.split(' ')
        if len(pool_id_name) == 2:
            pool_id = pool_id_name[0]
            pool_name = pool_id_name[1]
            pools[pool_name] = int(pool_id)

    logging.debug('Pools on {}: {}'.format(unit_name, pools))
    return pools


def get_ceph_pool_details(query_leader=True, unit_name=None, model_name=None):
    """Get ceph pool details.

    Return a list of ceph pools details dicts.

    :param query_leader: Whether to query the leader for pool details.
    :type query_leader: bool
    :param unit_name: Name of unit to get the pools on if query_leader is False
    :type unit_name: string
    :param model_name: Name of model to operate in
    :type model_name: str
    :returns: Dict of ceph pools
    :rtype: List[Dict,]
    :raise: zaza_model.CommandRunFailed
    """
    cmd = 'sudo ceph osd pool ls detail -f json'
    if query_leader and unit_name:
        raise ValueError("Cannot set query_leader and unit_name")
    if query_leader:
        result = zaza_model.run_on_leader(
            'ceph-mon',
            cmd,
            model_name=model_name)
    else:
        result = zaza_model.run_on_unit(
            unit_name,
            cmd,
            model_name=model_name)
    if int(result.get('Code')) != 0:
        raise zaza_model.CommandRunFailed(cmd, result)
    return json.loads(result.get('Stdout'))


def get_ceph_df(unit_name, model_name=None):
    """Return dict of ceph df json output, including ceph pool state.

    :param unit_name: Name of the unit to get ceph df
    :type unit_name: string
    :param model_name: Name of model to operate in
    :type model_name: str
    :returns: Dict of ceph df output
    :rtype: dict
    :raise: zaza.model.CommandRunFailed
    """
    cmd = 'sudo ceph df --format=json'
    result = zaza_model.run_on_unit(unit_name, cmd, model_name=model_name)
    if result.get('Code') != '0':
        raise zaza_model.CommandRunFailed(cmd, result)
    return json.loads(result.get('Stdout'))


def get_ceph_pool_sample(unit_name, pool_id=0, model_name=None):
    """Return list of ceph pool attributes.

    Take a sample of attributes of a ceph pool, returning ceph
    pool name, object count and disk space used for the specified
    pool ID number.

    :param unit_name: Name of the unit to get the pool sample
    :type unit_name: string
    :param pool_id: Ceph pool ID
    :type pool_id: int
    :param model_name: Name of model to operate in
    :type model_name: str
    :returns: List of pool name, object count, kb disk space used
    :rtype: list
    :raises: zaza.model.CommandRunFailed
    """
    df = get_ceph_df(unit_name, model_name)
    for pool in df['pools']:
        if pool['id'] == pool_id:
            pool_name = pool['name']
            obj_count = pool['stats']['objects']
            kb_used = pool['stats']['kb_used']

    logging.debug('Ceph {} pool (ID {}): {} objects, '
                  '{} kb used'.format(pool_name, pool_id,
                                      obj_count, kb_used))
    return pool_name, obj_count, kb_used


def get_rbd_hash(unit_name, pool, image, model_name=None):
    """Get SHA512 hash of RBD image.

    :param unit_name: Name of unit to execute ``rbd`` command on
    :type unit_name: str
    :param pool: Name of pool to export image from
    :type pool: str
    :param image: Name of image to export and compute checksum on
    :type image: str
    :param model_name: Name of Juju model to operate on
    :type model_name: str
    :returns: SHA512 hash of RBD image
    :rtype: str
    :raises: zaza.model.CommandRunFailed
    """
    cmd = ('sudo rbd -p {} export --no-progress {} - | sha512sum'
           .format(pool, image))
    result = zaza_model.run_on_unit(unit_name, cmd, model_name=model_name)
    if result.get('Code') != '0':
        raise zaza_model.CommandRunFailed(cmd, result)
    return result.get('Stdout').rstrip()


def get_pools_from_broker_req(application_or_unit, model_name=None):
    """Get pools requested by application or unit.

    By retrieving and parsing broker request from relation data we can get a
    list of pools a unit has requested.

    :param application_or_unit: Name of application or unit that is at the
                                other end of a ceph-mon relation.
    :type application_or_unit: str
    :param model_name: Name of Juju model to operate on
    :type model_name: Optional[str]
    :returns: List of pools requested.
    :rtype: List[str]
    :raises: KeyError
    """
    # NOTE: we do not pass on a name for the remote_interface_name as that
    # varies between the Ceph consuming applications.
    relation_data = zaza_juju.get_relation_from_unit(
        'ceph-mon', application_or_unit, None, model_name=model_name)

    # NOTE: we probably should consume the Ceph broker code from c-h but c-h is
    # such a beast of a dependency so let's defer adding it to Zaza if we can.
    broker_req = json.loads(relation_data['broker_req'])

    # A charm may request modifications to an existing pool by adding multiple
    # 'create-pool' broker requests so we need to deduplicate the list before
    # returning it.
    return list(set([
        op['name']
        for op in broker_req['ops']
        if op['op'] == 'create-pool'
    ]))
