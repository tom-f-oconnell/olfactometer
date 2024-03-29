"""
Functions for loading / saving configuration.
"""

import glob
from datetime import datetime
import json
import os
from os.path import split, join, isdir, isfile, splitext, exists
import sys
import tempfile
from pprint import pformat
from typing import Union, Sequence, Dict, Any

from google.protobuf import json_format
import yaml

from olfactometer import util, IN_DOCKER
from olfactometer.generators.common import validate_hardware_dict

# NOTE: this import must come after `util.generate_protobuf_outputs` call, which
# is currently ensured by happening on first module import (via __init__.py)
# TODO is pb2 suffix indication i'm not using the version i want?
# syntax was version 3, and the generated code seems to acknowledge that...
from olfactometer import olf_pb2
# This might have been (temporarily) necessary during a fresh install on python 3.10, to
# get the olf_pb2 import to not fail (may or may not have actually been a circular
# dependency issue). Issue may still present in some future fresh installs...
#import olfactometer


HARDWARE_DIR_ENVVAR = 'OLFACTOMETER_HARDWARE_DIR'
DEFAULT_HARDWARE_ENVVAR = 'OLFACTOMETER_DEFAULT_HARDWARE'

def load_hardware_config(hardware_config=None):
    """Returns dict loaded from YAML hardware config or None if no config.

    Args:
    hardware_config (optional str): (default=`None`) path to YAML config file,
        or prefix of one of the YAML files under `HARDWARE_DIR_ENVVAR`.
        If `None`, will try `HARDWARE_DIR_ENVVAR` and `DEFAULT_HARDWARE_ENVVAR`.

    Raises `IOError` if some required file / directory is not found.
    """
    # TODO add command line arg to list hardware and exit or separate script to
    # do so (maybe also printing out env var values (if set) and data in each of
    # the hardware config files) (maybe [also] list all this stuff if hardware
    # specified is invalid?)

    # TODO (probably simultaneously w/ fixing json support wrt `config`)
    # refactor handling of this to also support json
    hardware_config_dir = os.environ.get(HARDWARE_DIR_ENVVAR)

    if hardware_config_dir is not None:
        if not isdir(hardware_config_dir):
            raise IOError(f'environment variable {HARDWARE_DIR_ENVVAR}='
                f'{hardware_config_dir} was specified, but is not an existing '
                'directory'
            )

    def find_hardware_config(h, err_prefix):
        # We are just taking the chance that this might exist when really we
        # wanted to refer to something under OLFACTOMETER_HARDWARE_DIR.
        if isfile(h):
            return h

        if hardware_config_dir is None:
            raise IOError(f'{err_prefix} is not a fullpath to a file, and the '
                f'environment variable {HARDWARE_DIR_ENVVAR} is not defined, so cannot '
                'use a prefix'
            )

        _hardware_config_path = None
        hardware_config_prefixes = []
        for f in glob.glob(join(hardware_config_dir, '*')):
            n = split(f)[1]
            if n == h:
                _hardware_config_path = f
                break

            # Using prefix is only allowed if `hardware_config_dir` is specified
            # (via the environment variable named in `HARDWARE_DIR_ENVVAR`).
            #
            # ext includes the '.'
            prefix, ext = splitext(n)

            # Currently not checking if ext is in {'.yaml', '.yml', '.json'} / similar.
            hardware_config_prefixes.append(prefix)
            if prefix == h:
                _hardware_config_path = f
                break

        if _hardware_config_path is None:
            raise IOError(f'{err_prefix} is neither a fullpath to a file, nor a file/'
                f'prefix directly under {HARDWARE_DIR_ENVVAR}={hardware_config_dir}\n'
                'prefixes of files under this directory:\n'
                f'{pformat(hardware_config_prefixes)}'
            )

        return _hardware_config_path

    if hardware_config is not None:
        hardware_config_path = find_hardware_config(hardware_config,
            f'hardware_config={hardware_config} was passed, but it'
        )
    else:
        default_hardware = os.environ.get(DEFAULT_HARDWARE_ENVVAR)
        if default_hardware is not None:
            hardware_config_path = find_hardware_config(default_hardware,
                f'{DEFAULT_HARDWARE_ENVVAR}={default_hardware}'
            )
            # TODO maybe raise separte IOError error here if HARDWARE_DIR_ENVVAR
            # is not defined

    print('Using olfactometer hardware definition at:', hardware_config_path)
    with open(hardware_config_path, 'r') as f:
        hardware_yaml_dict = yaml.safe_load(f)

    validate_hardware_dict(hardware_yaml_dict)
    return hardware_yaml_dict


def load_dict(config_dict, message=None):
    """Returns a populated protobuf message and a dict with extra metadata.
    """
    if message is None:
        #message = olfactometer.olf_pb2.AllRequiredData()
        message = olf_pb2.AllRequiredData()

    # Always ignoring unknown fields for now, so the generators can store extra
    # metadata for use at analysis only in the same config files.
    json_format.ParseDict(config_dict, message, ignore_unknown_fields=True)
    return message, config_dict


def _load_helper(filelike2dict_fn, filelike, message=None):
    """Returns a populated protobuf message and a dict with extra metadata.
    """
    config_dict = filelike2dict_fn(filelike)
    return load_dict(config_dict, message=message)


# TODO update any unit tests involving load_json / load_yaml to ignore new
# second return argument (extra_metadata)

def load_json(json_filelike, message=None):
    '''
    # ...
    json_data = json_filelike.read()
    # filelike does not work here. str does.
    json_format.Parse(json_data, message,
        ignore_unknown_fields=_ignore_unknown_fields
    )
    # ...
    '''
    # TODO unit test this change to json loading
    return _load_helper(json.load, json_filelike, message=message)


def load_yaml(yaml_filelike, message=None):
    # TODO do we actually need any of the yaml 1.2(+?) features
    # available in ruamel.yaml but not in PyYAML (1.1 only)?
    return _load_helper(yaml.safe_load, yaml_filelike, message=message)


def load(config=None):
    """Parses config for a single run into a AllRequiredData message object

    Args:
    config (str|dict|None): If `str`, path to JSON or YAML file, which
        must end in .json or .yaml. If `None`, reads from `sys.stdin`.

    Returns an `olf_pb2.AllRequiredData` object and a `dict` that contains all
    of the loaded config data, including fields beyond those that affect
    contents of the `AllRequiredData` object.
    """
    # TODO any way to pass stdin back to interactive input, after (EOF?)?
    # (for interactive stuff during trial, like pausing...) (if not, maybe
    # implement pausing as arduino tracking state and knowing when host
    # disconnects?)
    if config is None:
        # Assuming we are reading from `sys.stdin` in this case, as I have not
        # yet settled on other mechanisms for getting files into Docker.
        print('Reading config from stdin')
        stdin_str = sys.stdin.read()

        if len(stdin_str) == 0:
            assert IN_DOCKER
            raise IOError('you must use the -i flag with docker run')

        # TODO check output of yaml dumping w/ default_flow_style=True again.
        # that might be an example of a case where YAML also would trigger this,
        # in which case i might want to do something different to detect JSON...
        if stdin_str.lstrip()[0] == '{':
            suffix = '.json'
        else:
            suffix = '.yaml'

        if util.in_windows():
            # To avoid weird errors with NamedTemporaryFile, which I vaguely
            # remember hearing didn't work as I need on Windows. See perhaps:
            # https://stackoverflow.com/questions/2549384
            # TODO test though. maybe this error is no longer relevant?
            # TODO maybe i can just do the rest of the stuff inside the tempfile
            # block? this was just Named for the suffix, right? maybe just
            # handle that separately (or do other tempfile objects also support
            # this?)?
            raise NotImplementedError('using stdin as input not supported in '
                'Windows'
            )

        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False
            ) as temp:
            config = temp.name
            temp.write(stdin_str)

    #all_required_data = olfactometer.olf_pb2.AllRequiredData()
    all_required_data = olf_pb2.AllRequiredData()

    if type(config) is dict:
        _, config_dict = load_dict(config, all_required_data)

    elif type(config) is str:
        with open(config, 'r') as f:
            if config.endswith('.json'):
                # First return argument is just the same as the second argument.
                # No need to store it again, as it's mutated.
                _, config_dict = load_json(f, all_required_data)

            elif config.endswith('.yaml'):
                _, config_dict = load_yaml(f, all_required_data)
            else:
                raise ValueError('file must end with either .json or .yaml')

    else:
        # TODO i think i have a few such error lines now. maybe factor out?
        raise ValueError(f'unrecognized config type {type(config)}. must be str'
            ' path to .yaml/.json config or dict'
        )

    return all_required_data, config_dict


# TODO ~pathlike type hint for generated_yaml_fname
# TODO factor this Dict[str, Any] to an alias -> use throughout (here and other modules)
def write_yaml(generated_config: Dict[str, Any], generated_yaml_fname) -> None:

    # Now that we are no longer letting PyYAML sort keys, we want to sort this
    # ourselves. It makes configs / interactive output easier to read.
    pins2odors = generated_config['pins2odors']
    # TODO deepcopy?
    generated_config = generated_config.copy()
    generated_config['pins2odors'] = dict(
        sorted(pins2odors.items(), key=lambda x: x[0])
    )

    # TODO should i be using safe_dump instead? (modify SafeDumper instead
    # of Dumper if so)
    # So that there are not aliases (references) within the generated YAML
    # (they make it less readable).
    # https://stackoverflow.com/questions/13518819
    yaml.Dumper.ignore_aliases = lambda *args : True

    # TODO what is default_style kwarg to pyyaml dump? docs don't seem to say...
    # TODO maybe i want to make a custom dumper that just uses this style for pin groups
    # though? right now it's pretty ugly when everything is using this style...
    #
    # Setting this to True would make lists single-line by default, which I want for
    # terminal stuff, but I don't like what this flow style does elsewhere.
    default_flow_style = False

    assert not exists(generated_yaml_fname)
    with open(generated_yaml_fname, 'w') as f:
        yaml.dump(generated_config, f, default_flow_style=default_flow_style,
            sort_keys=False
        )


# TODO change to returning Path objects?
def write_timestamped_config(
    generated_config: Union[Dict[str, Any], Sequence[Dict[str, Any]]],
    verbose: bool = True) -> str:
    """Writes config to YAML file(s) under working directory, named with current time.

    Returns name of file / directory where config YAML was written.
    """
    if type(generated_config) is dict:
        generated_yaml_fname = datetime.now().strftime('%Y%m%d_%H%M%S_stimuli.yaml')
        if verbose:
            print(f'Writing generated YAML to {generated_yaml_fname}')

        write_yaml(generated_config, generated_yaml_fname)

        if verbose:
            print()

        return generated_yaml_fname

    else:
        # TODO squeeze list to single element if only one file would be in dir?

        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        generated_config_dir = timestamp_str + '_stimuli'
        if verbose:
            print(f'Writing generated YAML under ./{generated_config_dir}/')

        assert not exists(generated_config_dir)
        os.mkdir(generated_config_dir)

        for i, yaml_dict in enumerate(generated_config):
            assert type(yaml_dict) is dict
            generated_yaml_fname = join(
                generated_config_dir, f'{timestamp_str}_stimuli_{i}.yaml'
            )
            write_yaml(yaml_dict, generated_yaml_fname)

        if verbose:
            print()

        return generated_config_dir
