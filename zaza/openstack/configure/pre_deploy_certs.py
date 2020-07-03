"""Module to setup pre-deploy TLS certs."""

import ipaddress
import itertools
import base64
import os

import zaza.openstack.utilities.cert

ISSUER_NAME = 'OSCI'


def set_cidr_certs():
    """Create certs and keys for deploy using IP SANS from CIDR.

    Create a certificate authority certificate and key. The CA cert and key
    are then base 64 encoded and assigned to the TEST_CAKEY and
    TEST_CACERT environment variables.

    Using the CA key a second certificate and key are generated. The new
    certificate has a SAN entry for the first 2^11 IPs in the CIDR.
    The cert and key are then base 64 encoded and assigned to the TEST_KEY
    and TEST_CERT environment variables.
    """
    (cakey, cacert) = zaza.openstack.utilities.cert.generate_cert(
        ISSUER_NAME,
        generate_ca=True)
    os.environ['TEST_CAKEY'] = base64.b64encode(cakey).decode()
    os.environ['TEST_CACERT'] = base64.b64encode(cacert).decode()
    # We need to restrain the number of SubjectAlternativeNames we attempt to
    # put # in the certificate.  There is a hard limit for what length the sum
    # of all extensions in the certificate can have.
    #
    # - 2^11 ought to be enough for anybody
    alt_names = []
    for addr in itertools.islice(
            ipaddress.IPv4Network(os.environ.get('TEST_CIDR_EXT')), 2**11):
        alt_names.append(str(addr))
    (key, cert) = zaza.openstack.utilities.cert.generate_cert(
        '*.serverstack',
        alternative_names=alt_names,
        issuer_name=ISSUER_NAME,
        signing_key=cakey)
    os.environ['TEST_KEY'] = base64.b64encode(key).decode()
    os.environ['TEST_CERT'] = base64.b64encode(cert).decode()


def set_certs_per_vips():
    """Create certs and keys for deploy using VIPS.

    Create a certificate authority certificate and key. The CA cert and key
    are then base 64 encoded and assigned to the TEST_CAKEY and
    TEST_CACERT environment variables.

    Using the CA key a certificate and key is generated for each VIP specified
    via environment variables. eg if TEST_VIP06=172.20.0.107 is set in the
    environment then a cert with a SAN entry for 172.20.0.107 is generated.
    The cert and key are then base 64 encoded and assigned to the
    TEST_VIP06_KEY and TEST_VIP06_CERT environment variables.
    """
    (cakey, cacert) = zaza.openstack.utilities.cert.generate_cert(
        ISSUER_NAME,
        generate_ca=True)
    os.environ['TEST_CAKEY'] = base64.b64encode(cakey).decode()
    os.environ['TEST_CACERT'] = base64.b64encode(cacert).decode()
    for vip_name, vip_ip in os.environ.items():
        if vip_name.startswith('TEST_VIP'):
            (key, cert) = zaza.openstack.utilities.cert.generate_cert(
                '*.serverstack',
                alternative_names=[vip_ip],
                issuer_name=ISSUER_NAME,
                signing_key=cakey)
            os.environ[
                '{}_KEY'.format(vip_name)] = base64.b64encode(key).decode()
            os.environ[
                '{}_CERT'.format(vip_name)] = base64.b64encode(cert).decode()
