import os

IN_DOCKER =  os.environ.get('OLFACTOMETER_IN_DOCKER') == '1'
_DEBUG = os.environ.get('OLFACTOMETER_DEBUG') == '1'

# TODO TODO could try to replace everything using this w/
# pkg_resources.find_resource, though not sure this will actually support any
# more cases as i'm using both (+ in python 3.7+ another module is recommended
# for the same function) (.whl should be the case to test)
# This will be under site-packages if pip installed (in default, non-editable
# mode at least).
THIS_PACKAGE_DIR = os.path.split(os.path.abspath(os.path.realpath(__file__)))[0]

assert os.path.exists(THIS_PACKAGE_DIR), \
    f'THIS_PACKAGE_DIR={THIS_PACKAGE_DIR} does not exist'

# TODO need to specify path to .proto file when this is installed as a script
# (probably need to put it in some findable location using setuptools...)
# (i'm just going to try 'python -m <...>' syntax for running scripts for now)

from .util import generate_protobuf_outputs

# The build process handles this in the Docker case. If the code would changes
# (which can only happen through a build) it would trigger protoc compilation as
# part of the build.
if not IN_DOCKER:
    generate_protobuf_outputs()

# Because we don't want to expose these under `olfactometer` package.
del os, generate_protobuf_outputs

from .config_io import load
from .olf import write_message, main
from .cli_entry_points import *
