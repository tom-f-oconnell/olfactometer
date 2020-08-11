#!/usr/bin/env bash

# TODO also add dialout stuff (and prompt user to relog / restart)...

# https://arduino.github.io/arduino-cli/installation/
# Run this from some directory where you want arduino-cli, and put the bin/
# subdir it creates on your path.
#curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh

# At least in a fresh Windows Subsystem for Linux (WSL) Ubuntu 18.04,
# this line seemed necessary before proceeding:
# (wasn't required on my 16.04 laptop that did have some arduino installed, but
# not arduino-cli)
# arduino-cli core update-index

arduino-cli core install arduino:avr


