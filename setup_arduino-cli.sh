#!/usr/bin/env bash

# TODO also add dialout stuff (and prompt user to relog / restart)...
# (if run as non-root? or use an envvar set in Dockerfile to exclude in docker
# case?)

# (commented because i don't want docker build running this)
if [ -z "${OLFACTOMETER_IN_DOCKER}" ]; then
    mkdir ~/arduino-cli
    cd ~/arduino-cli
fi

# TODO just replace the curl line with something equivalent that doesn't use
# curl?
if ! [ -x "$(command -v curl)" ]; then
    if [ -z "${OLFACTOMETER_IN_DOCKER}" ]; then
        # This case will run if the above env var is undefined.
        sudo apt-get install curl -y
    else
        apt-get install curl -y
    fi
fi

# https://arduino.github.io/arduino-cli/installation/
# Run this from some directory where you want arduino-cli, and put the bin/
# subdir it creates on your path.
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh

if ! [ -z "${OLFACTOMETER_IN_DOCKER}" ]; then
    # TODO maybe just change path? at least one guy seemed to think that was
    # less ideal for some reasons: https://stackoverflow.com/questions/27093612
    # and answers describing how to change path were unclear on how it interacts
    # with host $PATH... (or which syntax does / doesn't)

    # This destination should already be on the $PATH
    mv bin/arduino-cli /usr/local/bin/.

    # This should not err, because arduino-cli should have been the only thing
    # in that directory, so it should be empty now.
    rm -r bin/
fi

# TODO should i pin particular versions of arduino-cli stuff (here? in terms of
# which versions install.sh I use? both?)

arduino-cli core update-index
arduino-cli core install arduino:avr

