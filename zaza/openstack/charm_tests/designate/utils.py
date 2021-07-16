"""Utilities for interacting with designate."""

import dns.resolver
import logging
import tenacity

import designateclient.exceptions

import zaza.model


def create_or_return_zone(client, name, email):
    """Create zone or return matching existing zone.

    :param designate_client: Client to query designate
    :type designate_client: designateclient.v2.Client
    :param name: Name of zone
    :type name: str
    :param email: Email address to associate with zone.
    :type email: str
    :returns: Zone
    :rtype: designateclient.v2.zones.Zone
    """
    try:
        zone = client.zones.create(
            name=name,
            email=email)
    except designateclient.exceptions.Conflict:
        logging.info('{} zone already exists.'.format(name))
        zones = [z for z in client.zones.list() if z['name'] == name]
        assert len(zones) == 1, "Wrong number of zones found {}".format(zones)
        zone = zones[0]
    return zone


def create_or_return_recordset(client, zone_id, sub_domain, record_type, data):
    """Create recordset or return matching existing recordset.

    :param designate_client: Client to query designate
    :type designate_client: designateclient.v2.Client
    :param zone_id: uuid of zone
    :type zone_id: str
    :param sub_domain: Subdomain to associate records with
    :type sub_domain: str
    :param data: Dictionary of entries eg {'www.test.com': '10.0.0.24'}
    :type data: dict
    :returns: RecordSet
    :rtype: designateclient.v2.recordsets.RecordSet
    """
    try:
        rs = client.recordsets.create(
            zone_id,
            sub_domain,
            record_type,
            data)
    except designateclient.exceptions.Conflict:
        logging.info('{} record already exists.'.format(data))
        for r in client.recordsets.list(zone_id):
            if r['name'].split('.')[0] == sub_domain:
                rs = r
    return rs


def get_designate_zone_objects(designate_client, domain_name=None,
                               domain_id=None):
    """Get all domains matching a given domain_name or domain_id.

    :param designate_client: Client to query designate
    :type designate_client: designateclient.v2.Client
    :param domain_name: Name of domain to lookup
    :type domain_name: str
    :param domain_id: UUID of domain to lookup
    :type domain_id: str
    :returns: List of Domain objects matching domain_name or domain_id
    :rtype: [designateclient.v2.domains.Domain,]
    """
    all_zones = designate_client.zones.list()
    a = [z for z in all_zones
         if z['name'] == domain_name or z['id'] == domain_id]
    return a


def get_designate_domain_object(designate_client, domain_name):
    """Get the one and only domain matching the given domain_name.

    :param designate_client: Client to query designate
    :type designate_client: designateclient.v2.Client
    :param domain_name: Name of domain to lookup
    :type domain_name:str
    :returns: Domain with name domain_name
    :rtype: designateclient.v2.domains.Domain
    :raises: AssertionError
    """
    dns_zone_id = get_designate_zone_objects(designate_client,
                                             domain_name=domain_name)
    msg = "Found {} domains for {}".format(
        len(dns_zone_id),
        domain_name)
    assert len(dns_zone_id) == 1, msg
    return dns_zone_id[0]


def get_designate_dns_records(designate_client, domain_name, ip):
    """Look for records in designate that match the given ip.

    :param designate_client: Client to query designate
    :type designate_client: designateclient.v2.Client
    :param domain_name: Name of domain to lookup
    :type domain_name:str
    :returns: List of Record objects matching matching IP address
    :rtype: [designateclient.v2.records.Record,]
    """
    dns_zone = get_designate_domain_object(designate_client, domain_name)
    return [r for r in designate_client.recordsets.list(dns_zone['id'])
            if r['records'] == ip]


def check_dns_record_exists(dns_server_ip, query_name, expected_ip,
                            retry_count=3):
    """Lookup a DNS record against the given dns server address.

    :param dns_server_ip: IP address to run query against
    :type dns_server_ip: str
    :param query_name: Record to lookup
    :type query_name: str
    :param expected_ip: IP address expected to be associated with record.
    :type expected_ip: str
    :param retry_count: Number of times to retry query. Useful if waiting
                        for record to propagate.
    :type retry_count: int
    :raises: AssertionError
    """
    my_resolver = dns.resolver.Resolver()
    my_resolver.nameservers = [dns_server_ip]
    for attempt in tenacity.Retrying(
            stop=tenacity.stop_after_attempt(retry_count),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
            reraise=True):
        with attempt:
            logging.info("Checking record {} against {}".format(
                query_name,
                dns_server_ip))
            answers = my_resolver.query(query_name)
    for rdata in answers:
        logging.info("Checking address returned by {} is correct".format(
            dns_server_ip))
        assert str(rdata) == expected_ip


def check_dns_entry(des_client, ip, domain, record_name):
    """Check that record for ip is in designate and in bind.

    :param ip: IP address to lookup
    :type ip: str
    :param domain_name: Domain to look for record in
    :type domain_name:str
    :param record_name: record name
    :type record_name: str
    """
    check_dns_entry_in_designate(des_client, [ip], domain,
                                 record_name=record_name)
    check_dns_entry_in_bind(ip, record_name)


def check_dns_entry_in_designate(des_client, ip, domain, record_name=None):
    """Look for records in designate that match the given ip domain.

    :param designate_client: Client to query designate
    :type designate_client: designateclient.v2.Client
    :param ip: IP address to lookup in designate
    :type ip: str
    :param domain_name: Name of domain to lookup
    :type domain_name:str
    :param record_name: Retrieved record should have this name
    :type record_name: str
    :raises: AssertionError
    """
    records = get_designate_dns_records(des_client, domain, ip)
    assert records, "Record not found for {} in designate".format(ip)
    logging.info('Found record in {} for {} in designate'.format(domain, ip))

    if record_name:
        recs = [r for r in records if r['name'] == record_name]
        assert recs, "No DNS entry name matches expected name {}".format(
            record_name)
        logging.info('Found record in {} for {} in designate'.format(
            domain,
            record_name))


def check_dns_entry_in_bind(ip, record_name, model_name=None):
    """Check that record for ip address is in bind.

    :param ip: IP address to lookup
    :type ip: str
    :param record_name: record name
    :type record_name: str
    """
    for addr in zaza.model.get_app_ips('designate-bind',
                                       model_name=model_name):
        logging.info("Checking {} is {} against ({})".format(
            record_name,
            ip,
            addr))
        check_dns_record_exists(addr, record_name, ip, retry_count=6)
