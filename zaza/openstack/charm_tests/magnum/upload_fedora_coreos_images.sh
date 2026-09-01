#!/bin/bash

wget -O - https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/31.20200517.3.0/x86_64/fedora-coreos-31.20200517.3.0-openstack.x86_64.qcow2.xz \
  | xzcat > ./fedora-coreos-31.qcow2

openstack object create --name images/fedora-coreos-31.qcow2 magnum ./fedora-coreos-31.qcow2

wget -O - https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/32.20201104.3.0/x86_64/fedora-coreos-32.20201104.3.0-openstack.x86_64.qcow2.xz \
  | xzcat > ./fedora-coreos-32.qcow2

openstack object create --name images/fedora-coreos-32.qcow2 magnum ./fedora-coreos-32.qcow2

wget -O - https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/35.20220424.3.0/x86_64/fedora-coreos-35.20220424.3.0-openstack.x86_64.qcow2.xz \
  | xzcat > ./fedora-coreos-35.qcow2

openstack object create --name images/fedora-coreos-35.qcow2 magnum ./fedora-coreos-35.qcow2
