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


# TODO TODO TODO maybe i should make another endpoint (or python wrapper around
# -> command line args in one of current cmds / endpoints) so people can install
# more of these at runtime? would that work? maybe with extra args to persist
# the data if they need? or just always need to do it in same step / set up
# something like a volume?
# TODO TODO maybe (if would be uploaded) do a "arduino-cli board list" ->
# parse second to last col (FQBN) and check prefix matches one of the installed
# cores from "... core list"? (that prefix match appropriate?)
# (actually it seems the last column "Core" is already what i want...)

arduino-cli core update-index

# Not 100% clear on why my Mega (MEGA2560) doesn't fall under the
# arduino:megaavr core instead, but with only that core installed, arduino-cli
# build fails.
arduino-cli core install arduino:avr
# "Arduino Nano Every" that Han tested it with needed this core.
arduino-cli core install arduino:megaavr

