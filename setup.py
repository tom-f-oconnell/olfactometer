#!/usr/bin/env python3

from setuptools import setup, find_packages

setup(
    name='olfactometer',
    packages=find_packages(),
    install_requires=[
        # For nanopb
        'protobuf',
        'grpcio-tools',

        'pyserial',
        'pyyaml',

        # TODO does it require git installed in advance? if so, specify in
        # windows part of README and include in Dockerfile
        # TODO maybe delete this if i can't resolve the olf-version-str issue
        # (possible that git version will never really be useable as i'm
        # deploying it now, or at least with some of the ways i'd like to
        # support)
        'gitpython',

        # See note in package_data section below about trying to install
        # generator that comes with the nanopb submodule we have.
        # TL;DR using this package for simplicity.
        # TODO is this still used? check in fresh 18.04 vm and delete if not
        # (test both with and without docker)
        'nanopb',

        'alicat',

        'pyperclip',

        # TODO TODO delete after debugging
        'ipdb'
    ],
    # This just duplicates what's in test_requirements.txt, because apparently
    # pip doesn't actually provide any way to install these...
    tests_require=[
        # For nanopb
        'scons',

        'pytest',
        'inflection'
    ],
    entry_points={
        'console_scripts': [
            'olf=olfactometer:main_cli',
            # TODO still want the olf prefix for this one?
            'olf-test-valves=olfactometer:valve_test_cli',
            'olf-upload=olfactometer:upload_cli',
            'olf-time=olfactometer:print_config_time_cli',
            'olf-pins2odors=olfactometer:show_pins2odors_cli',
            # See TODO in upload.version_str definition. until it's addressed,
            # that function won't be able to provide any meaningful output
            #'olf-version-str=olfactometer:version_str',
        ],
    },
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
            'olf.proto',
            'olf.options',
            'firmware/olfactometer/*',

            # TODO could also try to install the nanopb generator from the
            # submodule version we have, but i'm leaning towards just using the
            # pypi nanopb, to not have to mess with that too much. could pin
            # version if necessary. (implemented using pypi version)

            # nanopb doesn't seem to include a full fledged protoc generator, so
            # we still need that non-Python dependency.

            # The only .h and .c files in the root of nanopb seem to be the
            # things we actually use. See upload.py:make_arduino_libraries
            'nanopb/*.h',
            'nanopb/*.c',

            'nanopb-arduino/src/*.h',
            'nanopb-arduino/src/*.cpp'
        ]
    }
)

