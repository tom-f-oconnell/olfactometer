#!/usr/bin/env bash

# TODO test this script in a fresh 18.04 VM

sudo apt update
sudo apt install protobuf-compiler

# TODO how to check we are at the git root?
# TODO get this script path and cd up a level, relative to it?
# Currently assuming they have cloned this repo and are running this script from
# the root of it.
git submodule update --init

../setup_arduino-cli.sh

echo "Make and activate a virtual environment (if you wish) and proceed with"
echo "steps in README to pip install this repo."

