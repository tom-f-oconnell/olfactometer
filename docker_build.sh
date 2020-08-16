#!/usr/bin/env bash

# TODO maybe all protobuf stuff should be generated in advance, and only the
# outputs baked into the docker image? only might need to compile to different
# arduino-cli targets using the deployed docker image, right?

# TODO maybe "git submodule init / update" here (in an idempotent way, and
# probably don't want to bump version of nanopb each time), in case not done on
# clone?

# NOTE: you should be able to use .custom_build_dockerignore as a normal
# .dockerignore, but I called it something different so we can generate 
# a .dockerignore in here without having to worry about saving and restoring
# the original (with modification time and everything...)

# (assuming we are running this script from the directory that contains it)
DOCKER_IGNORE_PATH=".dockerignore"

# So far haven't found a great way to only copy over files that are tracked by
# git.
#
# Found this: https://stackoverflow.com/questions/51693245 but I couldn't 
# figure out how to import it on top of the base image I had specified in an
# attempt at a Dockerfile ('FROM python:3.6.11-slim-buster'...).
#
# I also tried symlinking .gitignore to .dockerignore, and disabling global
# .gitignore with 'git config --local core.excludesfile', but that doesn't
# include the stuff ignored with .gitignore files in other directories, and
# I feel like it might also miss some other cases.
#
# So now, I'm just going to forgo the static Dockerfile, and dynamically
# generate one that explicitly copies all of the files tracked by git.

CUSTOM=".custom_build_dockerignore"
echo "Generating ${DOCKER_IGNORE_PATH} from ${CUSTOM} and git untracked files"

cp "${CUSTOM}" "${DOCKER_IGNORE_PATH}"

GIT_LS_CMD="git ls-files --others --directory"
eval "${GIT_LS_CMD}" >>"${DOCKER_IGNORE_PATH}"

# There's probably a simpler way, but this seems to work.
# Compare to output of (with and without the -q):
# git submodule foreach -q 'git ls-files --directory --others'
git submodule foreach -q "${GIT_LS_CMD}"' | xargs printf "$path//%s\n"' | \
    grep -v '//$' | sed 's/\/\//\//' >>"${DOCKER_IGNORE_PATH}"

# Calling it 'olf' for now, to be consistent w/ main script installed via pip.
# (and also it's shorter...)
DOCKER_USERNAME="tom0connell"
#TAG_NAME="olf"
TAG_NAME="$(basename `pwd`)"

# The ':latest' part of the tag (the version?) seems to be filled in
# automatically (as 'latest') if not specified.
sudo docker build -t "${DOCKER_USERNAME}/${TAG_NAME}" .

