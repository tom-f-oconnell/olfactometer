#!/usr/bin/env bash

# TODO also add dialout stuff (and prompt user to relog / restart)...

# https://arduino.github.io/arduino-cli/installation/
# Run this from some directory where you want arduino-cli, and put the bin/
# subdir it creates on your path.
#curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh

arduino-cli core install arduino:avr


