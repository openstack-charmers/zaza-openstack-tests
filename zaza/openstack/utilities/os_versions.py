# Copyright 2018 Canonical Ltd.
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

"""Module containing data about OpenStack versions."""
from collections import OrderedDict


UBUNTU_OPENSTACK_RELEASE = OrderedDict([
    ('oneiric', 'diablo'),
    ('precise', 'essex'),
    ('quantal', 'folsom'),
    ('raring', 'grizzly'),
    ('saucy', 'havana'),
    ('trusty', 'icehouse'),
    ('utopic', 'juno'),
    ('vivid', 'kilo'),
    ('wily', 'liberty'),
    ('xenial', 'mitaka'),
    ('yakkety', 'newton'),
    ('zesty', 'ocata'),
    ('artful', 'pike'),
    ('bionic', 'queens'),
    ('cosmic', 'rocky'),
    ('disco', 'stein'),
    ('eoan', 'train'),
    ('focal', 'ussuri'),
    ('groovy', 'victoria'),
    ('hirsute', 'wallaby'),
    ('impish', 'xena'),
    ('jammy', 'yoga'),
    ('kinetic', 'zed'),
    ('lunar', 'antelope'),
])


OPENSTACK_CODENAMES = OrderedDict([
    ('2011.2', 'diablo'),
    ('2012.1', 'essex'),
    ('2012.2', 'folsom'),
    ('2013.1', 'grizzly'),
    ('2013.2', 'havana'),
    ('2014.1', 'icehouse'),
    ('2014.2', 'juno'),
    ('2015.1', 'kilo'),
    ('2015.2', 'liberty'),
    ('2016.1', 'mitaka'),
    ('2016.2', 'newton'),
    ('2017.1', 'ocata'),
    ('2017.2', 'pike'),
    ('2018.1', 'queens'),
    ('2018.2', 'rocky'),
    ('2019.1', 'stein'),
    ('2019.2', 'train'),
    ('2020.1', 'ussuri'),
    ('2020.2', 'victoria'),
    ('2021.1', 'wallaby'),
    ('2021.2', 'xena'),
    ('2022.1', 'yoga'),
    ('2022.2', 'zed'),
    ('2023.1', 'antelope'),
])

OPENSTACK_RELEASES_PAIRS = [
    'trusty_icehouse', 'trusty_kilo', 'trusty_liberty',
    'trusty_mitaka', 'xenial_mitaka', 'xenial_newton',
    'yakkety_newton', 'xenial_ocata', 'zesty_ocata',
    'xenial_pike', 'artful_pike', 'xenial_queens',
    'bionic_queens', 'bionic_rocky', 'cosmic_rocky',
    'bionic_stein', 'disco_stein', 'bionic_train',
    'eoan_train', 'bionic_ussuri', 'focal_ussuri',
    'focal_victoria', 'groovy_victoria',
    'focal_wallaby', 'hirsute_wallaby',
    'focal_xena', 'impish_xena',
    'focal_yoga', 'jammy_yoga', 'jammy_zed',
    'kinetic_zed', 'jammy_antelope', 'lunar_antelope',
]

SWIFT_CODENAMES = OrderedDict([
    ('diablo',
        ['1.4.3']),
    ('essex',
        ['1.4.8']),
    ('folsom',
        ['1.7.4']),
    ('grizzly',
        ['1.7.6', '1.7.7', '1.8.0']),
    ('havana',
        ['1.9.0', '1.9.1', '1.10.0']),
    ('icehouse',
        ['1.11.0', '1.12.0', '1.13.0', '1.13.1']),
    ('juno',
        ['2.0.0', '2.1.0', '2.2.0']),
    ('kilo',
        ['2.2.1', '2.2.2']),
    ('liberty',
        ['2.3.0', '2.4.0', '2.5.0']),
    ('mitaka',
        ['2.5.0', '2.6.0', '2.7.0']),
    ('newton',
        ['2.8.0', '2.9.0']),
    ('ocata',
        ['2.11.0', '2.12.0', '2.13.0']),
    ('pike',
        ['2.13.0', '2.15.0']),
    ('queens',
        ['2.16.0', '2.17.0']),
    ('rocky',
        ['2.18.0', '2.19.0']),
    ('stein',
        ['2.20.0', '2.21.0']),
    ('train',
        ['2.22.0']),
    ('ussuri',
        ['2.24.0', '2.25.0']),
    ('victoria',
        ['2.25.0']),
])

OVN_CODENAMES = OrderedDict([
    ('train',
        ['2.12']),
    ('ussuri',
        ['20.03']),
    ('victoria',
        ['20.06']),
    ('wallaby',
        ['20.12']),
])

# >= Liberty version->codename mapping
PACKAGE_CODENAMES = {
    'nova-common': OrderedDict([
        ('12', 'liberty'),
        ('13', 'mitaka'),
        ('14', 'newton'),
        ('15', 'ocata'),
        ('16', 'pike'),
        ('17', 'queens'),
        ('18', 'rocky'),
        ('19', 'stein'),
        ('20', 'train'),
        ('21', 'ussuri'),
        ('22', 'victoria'),
    ]),
    'neutron-common': OrderedDict([
        ('7', 'liberty'),
        ('8', 'mitaka'),
        ('9', 'newton'),
        ('10', 'ocata'),
        ('11', 'pike'),
        ('12', 'queens'),
        ('13', 'rocky'),
        ('14', 'stein'),
        ('15', 'train'),
        ('16', 'ussuri'),
        ('17', 'victoria'),
    ]),
    'cinder-common': OrderedDict([
        ('7', 'liberty'),
        ('8', 'mitaka'),
        ('9', 'newton'),
        ('10', 'ocata'),
        ('11', 'pike'),
        ('12', 'queens'),
        ('13', 'rocky'),
        ('14', 'stein'),
        ('15', 'train'),
        ('16', 'ussuri'),
        ('17', 'victoria'),
    ]),
    'keystone': OrderedDict([
        ('8', 'liberty'),
        ('9', 'mitaka'),
        ('10', 'newton'),
        ('11', 'ocata'),
        ('12', 'pike'),
        ('13', 'queens'),
        ('14', 'rocky'),
        ('15', 'stein'),
        ('16', 'train'),
        ('17', 'ussuri'),
        ('18', 'victoria'),
    ]),
    'horizon-common': OrderedDict([
        ('8', 'liberty'),
        ('9', 'mitaka'),
        ('10', 'newton'),
        ('11', 'ocata'),
        ('12', 'pike'),
        ('13', 'queens'),
        ('14', 'rocky'),
        ('15', 'stein'),
        ('16', 'train'),
        ('18', 'ussuri'),
        ('19', 'victoria'),
    ]),
    'ceilometer-common': OrderedDict([
        ('5', 'liberty'),
        ('6', 'mitaka'),
        ('7', 'newton'),
        ('8', 'ocata'),
        ('9', 'pike'),
        ('10', 'queens'),
        ('11', 'rocky'),
        ('12', 'stein'),
        ('13', 'train'),
        ('14', 'ussuri'),
        ('15', 'victoria'),
    ]),
    'heat-common': OrderedDict([
        ('5', 'liberty'),
        ('6', 'mitaka'),
        ('7', 'newton'),
        ('8', 'ocata'),
        ('9', 'pike'),
        ('10', 'queens'),
        ('11', 'rocky'),
        ('12', 'stein'),
        ('13', 'train'),
        ('14', 'ussuri'),
        ('15', 'victoria'),
    ]),
    'glance-common': OrderedDict([
        ('11', 'liberty'),
        ('12', 'mitaka'),
        ('13', 'newton'),
        ('14', 'ocata'),
        ('15', 'pike'),
        ('16', 'queens'),
        ('17', 'rocky'),
        ('18', 'stein'),
        ('19', 'train'),
        ('20', 'ussuri'),
        ('21', 'victoria'),
    ]),
    'openstack-dashboard': OrderedDict([
        ('8', 'liberty'),
        ('9', 'mitaka'),
        ('10', 'newton'),
        ('11', 'ocata'),
        ('12', 'pike'),
        ('13', 'queens'),
        ('14', 'rocky'),
        ('15', 'stein'),
        ('16', 'train'),
        ('18', 'ussuri'),
        ('19', 'victoria'),
    ]),
    'designate-common': OrderedDict([
        ('1', 'liberty'),
        ('2', 'mitaka'),
        ('3', 'newton'),
        ('4', 'ocata'),
        ('5', 'pike'),
        ('6', 'queens'),
        ('7', 'rocky'),
        ('8', 'stein'),
        ('9', 'train'),
        ('10', 'ussuri'),
        ('11', 'victoria'),
    ]),
    'ceph-common': OrderedDict([
        ('10', 'mitaka'),    # jewel
        ('12', 'queens'),    # luminous
        ('13', 'rocky'),     # mimic
        ('14', 'train'),     # nautilus
        ('15', 'ussuri'),    # octopus
        ('16', 'victoria'),  # pacific
        ('17', 'yoga'),      # quincy
    ]),
    'placement-common': OrderedDict([
        ('2', 'train'),
        ('3', 'ussuri'),
        ('4', 'victoria'),
    ]),
}


UBUNTU_RELEASES = (
    'lucid',
    'maverick',
    'natty',
    'oneiric',
    'precise',
    'quantal',
    'raring',
    'saucy',
    'trusty',
    'utopic',
    'vivid',
    'wily',
    'xenial',
    'yakkety',
    'zesty',
    'artful',
    'bionic',
    'cosmic',
    'disco',
    'eoan',
    'focal',
    'groovy',
    'hirsute',
    'impish',
    'jammy',
    'kinetic',
    'lunar',
)


class BasicStringComparator(object):
    """Provides a class that will compare strings from an iterator type object.

    Used to provide > and < comparisons on strings that may not necessarily be
    alphanumerically ordered.  e.g. OpenStack or Ubuntu releases AFTER the
    z-wrap.
    """

    _list = None

    def __init__(self, item):
        """Do init."""
        if self._list is None:
            raise Exception("Must define the _list in the class definition!")
        try:
            self.index = self._list.index(item)
        except Exception:
            raise KeyError("Item '{}' is not in list '{}'"
                           .format(item, self._list))

    def __eq__(self, other):
        """Do equals."""
        assert isinstance(other, str) or isinstance(other, self.__class__)
        return self.index == self._list.index(other)

    def __ne__(self, other):
        """Do not equals."""
        return not self.__eq__(other)

    def __lt__(self, other):
        """Do less than."""
        assert isinstance(other, str) or isinstance(other, self.__class__)
        return self.index < self._list.index(other)

    def __ge__(self, other):
        """Do greater than or equal."""
        return not self.__lt__(other)

    def __gt__(self, other):
        """Do greater than."""
        assert isinstance(other, str) or isinstance(other, self.__class__)
        return self.index > self._list.index(other)

    def __le__(self, other):
        """Do less than or equals."""
        return not self.__gt__(other)

    def __repr__(self):
        """Return the representation of CompareOpenStack."""
        return "%s<%s>" % (self.__class__.__name__, self._list[self.index])

    def __str__(self):
        """Give back the item at the index.

        This is so it can be used in comparisons like:

        s_mitaka = CompareOpenStack('mitaka')
        s_newton = CompareOpenstack('newton')

        assert s_newton > s_mitaka

        :returns: <string>
        """
        return self._list[self.index]


class CompareHostReleases(BasicStringComparator):
    """Provide comparisons of Ubuntu releases.

    Use in the form of

    if CompareHostReleases(release) > 'trusty':
        # do something with mitaka
    """

    _list = UBUNTU_RELEASES


class CompareOpenStack(BasicStringComparator):
    """Provide comparisons of OpenStack releases.

    Use in the form of

    if CompareOpenStack(release) > 'yoga':
        # do something
    """

    _list = list(OPENSTACK_CODENAMES.values())
