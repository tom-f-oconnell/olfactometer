#!/usr/bin/env bash

# TODO test this script in a fresh 18.04 VM
# (w/ some automated test that actually checks pip install after this, ideally)

sudo apt update
sudo apt install protobuf-compiler -y

# TODO how to check we are at the git root?
# TODO get this script path and cd up a level, relative to it?
# Currently assuming they have cloned this repo and are running this script from
# the root of it.
# TODO need --recursive too, or is that just for submodules within submodules?
git submodule update --init

# https://stackoverflow.com/questions/4774054
SCRIPTPATH="$( cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

# TODO cases where this env var prefix used to call script won't work
# (maybe some of the reasons people usually insist on quoting env vars?)
$SCRIPTPATH/../setup_arduino-cli.sh

echo "Make and activate a virtual environment (if you wish) and proceed with"
echo "steps in README to pip install this repo."

