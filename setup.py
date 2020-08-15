#!/usr/bin/env python3

# This is mainly just so files in the ./tests/ directory can import things
# defined in the project root. Copied from very top of:
# https://docs.pytest.org/en/stable/goodpractices.html
# TODO any other way that requires less boilerplate, but can still import from
# ./tests/?

from setuptools import setup

setup(
    name='olfactometer',
    # TODO maybe just replace w/ find_package() (to not have to change
    # olfacometer twice if package name changes, and since arbitrary code
    # executtion in setup.py is not supported for all build systems)?
    packages=['olfactometer'],
    install_requires=[
        # For nanopb
        'protobuf',
        'grpcio-tools',

        'pyserial',
        'pyyaml',

        # TODO actually use this one... (and does it require git installed in
        # advance?  if so, specify in windows part of README and include in
        # Dockerfile)
        'gitpython'
    ],
    # This just duplicates what's in test_requirements.txt, because apparently
    # pip doesn't actually provide any way to install these...
    tests_require=[
        # For nanopb
        'scons',

        'pytest',
        'inflection'
    ],
    # Going to just try using 'python -m <...>' syntax for calling these scripts
    # now. Some problems could probably be avoided by refactoring so scripts and
    # module 'olfactometer.py' have different names, but not sure...
    scripts=[
        # TODO can try to change names back once get everything working with
        # unique names
        'scripts/olf',
        'scripts/olf-upload'
    ],
    # TODO will including stuff above package dir prevent some things from
    # working? like building a wheel?
    # Seems to work with python==3.6.9 pip==20.2.2 setuptools==39.0.1
    # Everything gets copied into the venv site-packages, but this has the
    # negative side effect of making 'firmware' importable (though nothing can
    # be done with it).
    # This also seems to require (just via leaving it unspecified),
    # include_package_data=False.
    # editable (-e) pip install does NOT seem to place these correctly
    # (they aren't in the same site-packages path at least...)
    # Though pkg_resources.resource_filename('olfactometer', 'olf.proto') gives
    # a path under the 'olfactometer' site-packages directory, which does not
    # exist...
    package_data={
        'olfactometer': [
            '../olf.proto',
            '../olf.options',
            '../firmware/olfactometer/*'
        ]
    }
)

