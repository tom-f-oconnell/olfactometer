#!/usr/bin/env python3

# This is mainly just so files in the ./tests/ directory can import things
# defined in the project root. Copied from very top of:
# https://docs.pytest.org/en/stable/goodpractices.html
# TODO any other way that requires less boilerplate, but can still import from
# ./tests/?

from setuptools import setup

setup(
    name='olfactometer',
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
    scripts=[
        'olfactometer/olfactometer.py',
        'olfactometer/upload.py'
    ]
)

