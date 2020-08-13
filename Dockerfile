
# https://pythonspeed.com/articles/base-image-python-docker-images
# TODO try using 3.8 after checking it still works w/ 3.6.11
#FROM python:3.8-slim-buster
FROM python:3.6.11-slim-buster

# TODO how important is it to apt update && apt upgrade (for security reasons,
# or what have you)? very exposed if just using a local python app?

# Need to build from a directory containing both olfactometer and nanopb-arduino
# because building inside olfactometer will not allow us to copy nanopb-arduino
# at ../nanopb-arduino, because it is out of the build context.
# https://stackoverflow.com/questions/27068596
# Originally tried it this way, but all of the contents of my ~/src directory
# containing these two seemed to be getting sent to the docker daemon as first
# part of build, and that was taking forever, so that doesn't seem like a good
# solution. Now I've moved nanopb-arduino to be a submodule, so it will be in
# the build context of a build executed from the root of this repo.
#COPY olfactometer /
# was originally planning on 
#COPY nanopb-arduino /

#COPY . /olfactometer

#COPY Dockerfile /

COPY olfactometer /
