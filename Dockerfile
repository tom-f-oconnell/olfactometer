
################################################################################
# NOTE: do not run `docker build ...` using this file directly.
# Call `docker_build.sh`, which generates the appropriate list of files to
# ignore and saves them to a temporary .dockerignore before building.
################################################################################

# https://pythonspeed.com/articles/base-image-python-docker-images
# TODO try using 3.8 after checking it still works w/ 3.6.11
#FROM python:3.8-slim-buster
FROM python:3.6.11-slim-buster

# To be tested in some install scripts, to change behavior slightly for Docker
# target (e.g. setup_arduino_cli.sh).
ENV OLFACTOMETER_IN_DOCKER=0

# TODO experiment w/ fewer RUN statements their effect on final image size.
# some conflicting info online. https://stackoverflow.com/questions/39223249

# This seems to install libprotoc 3.6.1
RUN apt-get update -y && apt-get install protobuf-compiler -y

# TODO how important is it to apt update && apt upgrade (for security reasons,
# or what have you)? very exposed if just using a local python app?

# So the relative paths to [test_]requirements.txt work, as well as so some
# assumptions in setup_arduino-cli.sh are satisfied.
WORKDIR /olfactometer

COPY setup_arduino-cli.sh .
# So this step seems to increase the size from 170MB to 505MB (by far largest)
# The /root/.arduino15/packages/arduino/tools/avr-gcc directory is itself 215M,
# which is most of this increment. I'm not sure there's anything in there that I
# can really delete.
# Could maybe delete:
# /room/.arduino/staging (46M) (not sure if even this is worth the risk though)
RUN ./setup_arduino-cli.sh

# This was nice because changes to code didn't necessarily require installing
# all the dependencies again, because of the Docker build caching, but it seems
# `setup.py` is basically required to have the tests in their own tree...
# "When using COPY with more than one source file, the destination must be a
# directory and end with a /"
#COPY *requirements.txt ./
#RUN pip install -r requirements.txt && pip install -r test_requirements.txt

# TODO any real way to just have changes to setup.py requirements
# invalidate the 'pip install .' step, and have changes to the code not trigger.
# The issue as i see it, is that i think i need to copy all the code before
# "pip install ." (i'm not 100% clear it's not cached in some way...)

# This might also copy the stuff we already copied above, but that's a small
# price to pay for the simplicity of not explicitly copying everything else,
# and the earlier copies help with caching.
COPY . .

# Since we disable the automatic generation when `olfactometer.py` is run in
# Docker (since the code should never change, without triggering this anyway...)
# Need to do this before the "pip install ." step.
WORKDIR /olfactometer/olfactometer
RUN protoc --python_out=. olf.proto

# TODO did this pip install (in the second of two builds, without clearing
# anything) actually manage to use some kind of pip cache? (olfactometer.py
# changed, so i would have thought it'd completely redo the pip install, but it
# seemed faster?)
WORKDIR /olfactometer
RUN pip install .

# TODO also do the nanopb generation stuff + setting up arduino libraries in
# here? (maybe call one of my own functions for this?)

# TODO TODO run nanopb tests (and any of mine, if i make them...), and maybe use
# the healthcheck command or whatever it was called to do that?
# TODO and maybe pip uninstall test_requirements.txt after, if at build time
# only?

ENTRYPOINT ["olf"]

