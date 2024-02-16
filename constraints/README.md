# Constraints

This directory holds the pip constraints used by the different testing
environments used by Charmed OpenStack.

It's worth emphasize that these constraints are used for testing environments,
that means used in tox.ini files, but never to build charms.

## Naming scheme

The constraints files follow the following nomenclature:

    constraints-$RELEASE.txt
    
`$RELEASE` represents the OpenStack release, with the special exception of
`master` that's used to apply constraints to the `master` and `main` branches.

For example for the case of OpenStack 2023.1 (Antelope), the constraints file
would be named `constraints-2023.1.txt`.
