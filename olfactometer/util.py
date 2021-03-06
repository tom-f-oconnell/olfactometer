#!/usr/bin/env python3

import os
from os.path import split, join, realpath, abspath, exists, isdir, splitext, \
    isfile
import binascii
import time
import subprocess
import warnings
import sys
import tempfile
from datetime import datetime, timedelta
import glob
import json
import math
import argparse
from pprint import pprint
import atexit

import serial
# TODO use to make functions for printing vid/pid (or other unique ids for usb
# devices), which can be used to reference specific MFCs / arduinos in config
# (and also for listing ports corresponding to such devices).
# probably have env vars to set vid/pid (one each?), to not have to type out
# each time.
# TODO maybe also use whichever unique USB ID to configure a expected ID, so
# that if the wrong arduino is connected it can be detected?
from serial.tools import list_ports
# TODO try to find a way of accessing this type without any prefix '_'s
from google.protobuf.internal.encoder import _VarintBytes
from google.protobuf import json_format, pyext
import yaml
from alicat import FlowController

from olfactometer import upload
from olfactometer.generators import common, basic, pair_concentration_grid

in_docker = 'OLFACTOMETER_IN_DOCKER' in os.environ

# TODO TODO could try to replace everything using this w/
# pkg_resources.find_resource, though not sure this will actually support any
# more cases as i'm using both (+ in python 3.7+ another module is recommended
# for the same function) (.whl should be the case to test)
# This will be under site-packages if pip installed (in default, non-editable
# mode at least).
this_package_dir = split(abspath(realpath(__file__)))[0]

assert exists(this_package_dir), \
    f'this_package_dir={this_package_dir} does not exist'

# TODO TODO TODO (a bit hacky, but...) maybe i could atexit make a new
# connection to the same port to reset the Arduino? assuming it does reset on
# serial connection initiation, and there isn't some other call i could be
# making to signal to the arduino similarly, in a way that wouldn't require
# making a connection with no intention of using it

# TODO need to specify path to .proto file when this is installed as a script
# (probably need to put it in some findable location using setuptools...)
# (i'm just going to try 'python -m <...>' syntax for running scripts for now)

# The build process handles this in the Docker case. If the code would changes
# (which can only happen through a build) it would trigger protoc compilation as
# part of the build.
if not in_docker:
    # TODO maybe only do this if installed editable / not installed and being
    # used from within source tree? (would probably have to be a way to include
    # build in setup.py... and not sure there is)
    # TODO only do this if proto_file has changed since the python outputs have
    # TODO TODO wait, why doesn't this need to use the nanopdb_generator, or
    # otherwise reference that? doesn't it need to be symmetric w/ firmware
    # definitions generated via nanopb?
    proto_file = join(this_package_dir, 'olf.proto')
    proto_path, _ = split(proto_file)
    p = subprocess.Popen(['protoc', f'--python_out={this_package_dir}',
        f'--proto_path={proto_path}', proto_file
    ])
    p.communicate()
    failure = bool(p.returncode)
    if failure:
        raise RuntimeError(f'generating python code from {proto_file} failed')

# TODO is pb2 suffix indication i'm not using the version i want?
# syntax was version 3, and the generated code seems to acknowledge that...
from olfactometer import olf_pb2


nanopb_options_path = join(this_package_dir, 'olf.options')
with open(nanopb_options_path, 'r') as f:
    lines = [x.strip() for x in f.readlines()]
nanopb_options_lines = [x for x in lines if len(x) > 0 and not x[0] == '#']

# TODO implement preprocessing of config from intermediate (dict probably? yaml
# and json loaders can be configured to give comprable output?) to infer keys
# that aren't really necessary (like pinGroups / pins) (and maybe allow 'pins'
# to be used in place of pinSequence? could be a mess for maintainability
# though...
# TODO maybe try nesting the PinGroup object into the other message type, and
# see if that changes the json syntax? (would have to adapt C code a bit though,
# AND might prevent nanopb from optimizing as much from the *.options)
# TODO and also probably allow seconds / ms units for PulseTiming fields
# (already have some of this stuff in generator stuff, though not sure if i want
# to also expose it here...)

# TODO depending on how i check for the 'generator' tag in the config, if i'm
# still going to use that, might want to validate json and yaml equally to check
# they don't have that tag, if in docker, since what that would trigger
# currently wouldn't work in docker (since can't write files, as-is)


hardware_dir_envvar = 'OLFACTOMETER_HARDWARE_DIR'
default_hardware_envvar = 'OLFACTOMETER_DEFAULT_HARDWARE'

def load_hardware_config(hardware_config=None, required=False):
    """Returns dict loaded from YAML hardware config or None if no config.

    Args:
    hardware_config (optional str): (default=`None`) path to YAML config file,
        or prefix of one of the YAML files under `hardware_dir_envvar`.
        If `None`, will try `hardware_dir_envvar` and `default_hardware_envvar`.

    required (optional bool): (default=`False`) if `True`, will raise `IOError`,
        rather than returning `None`, if no hardware config is found.

    Raises `IOError` if some required file / directory is not found.
    """
    # TODO add command line arg to list hardware and exit or separate script to
    # do so (maybe also printing out env var values (if set) and data in each of
    # the hardware config files) (maybe [also] list all this stuff if hardware
    # specified is invalid?)

    # TODO (probably simultaneously w/ fixing json support wrt `config`)
    # refactor handling of this to also support json
    hardware_config_dir = os.environ.get(hardware_dir_envvar)

    if hardware_config_dir is not None:
        if not isdir(hardware_config_dir):
            raise IOError(f'environment variable {hardware_dir_envvar}='
                f'{hardware_config_dir} was specified, but is not an existing '
                'directory'
            )

    def find_hardware_config(h, err_prefix):
        # We are just taking the chance that this might exist when really we
        # wanted to refer to something under OLFACTOMETER_HARDWARE_DIR.
        if isfile(h):
            return h

        _hardware_config_path = None
        for f in glob.glob(join(hardware_config_dir, '*')):
            n = split(f)[1]
            if n == h:
                _hardware_config_path = f
                break

            # Using prefix is only allowed if `hardware_config_dir` is specified
            # (via the environment variable named in `hardware_dir_envvar`).
            if hardware_config_dir is not None:
                # ext includes the '.'
                prefix, ext = splitext(n)
                if prefix == h and len(ext) > 1:
                    _hardware_config_path = f
                    break

        # TODO test required logic doesn't break my old usage in check_need_...
        if required and _hardware_config_path is None:
            if hardware_config_dir is None:
                raise IOError(err_prefix + ' is neither a fullpath to a file, '
                    f'and the environment variable {hardware_dir_envvar} is not'
                    ' defined, so cannot use a prefix'
                )
            else:
                raise IOError(err_prefix + ' is neither a fullpath to a file, '
                    'nor a file / file prefix directly under '
                    f'{hardware_dir_envvar}={hardware_config_dir}'
                )

        return _hardware_config_path

    hardware_config_path = None
    if hardware_config is not None:
        hardware_config_path = find_hardware_config(hardware_config,
            f'hardware_config={hardware_config} was passed, but it'
        )
    else:
        default_hardware = os.environ.get(default_hardware_envvar)
        if default_hardware is not None:
            hardware_config_path = find_hardware_config(default_hardware,
                f'{default_hardware_envvar}={default_hardware}'
            )
            # TODO maybe raise separte IOError error here if hardware_dir_envvar
            # is not defined

    if hardware_config_path is not None:
        print('Using olfactometer hardware definition at:',
            hardware_config_path
        )
        with open(hardware_config_path, 'r') as f:
            hardware_yaml_dict = yaml.safe_load(f)
    else:
        hardware_yaml_dict = None

    return hardware_yaml_dict


def in_windows():
    return os.name == 'nt'


def check_need_to_preprocess_config(config, hardware_config=None):
    # TODO update doc to indicate directory case if i'm going to support that
    """Returns input or new pre-processed config, if it input requests it.

    If a line like 'generator: <generator-py-file-prefix>' is in the YAML file
    `olfactometer/generators/<generator-py-file-prefix>.py:make_config_dict`
    will be used to pre-process the input YAML into a YAML that can be used
    directly to control a stimulus program.

    See `load_hardware_config` for meaning of `hardware_config` argument.
    """
    # We need to save the generated YAML in this case, because otherwise we
    # would lose metadata crucial for analyzing corresponding data, and I
    # haven't yet figured out a way to do it in Docker (options seem to
    # exist, but I'd need to provide instructions, test it, etc). So for
    # now, I'm just not supporting this case. Could manually run generators
    # in advance (maybe provide instructions for that? or **maybe** have
    # that be the norm?)
    if in_docker:
        # TODO after refactoring main/run to work with w/ `dict` config input
        # (rather than just files), could probably relax this restriction, and
        # just use a `dict` in docker case (there is still the issue of not
        # being able to save generated outputs, but perhaps that error should be
        # triggered in the function that would do that)

        # We can't read it to check, because that would read to end of stdin,
        # which is the input in that case. Would need to do some other trick,
        # which would probably require some light refactoring.
        warnings.warn('not checking for need to pre-process config, because not'
            ' currently supported from Dockerized deployment'
        )
        return config

    # It should be a path to a .json/.yaml config file in this case.
    if type(config) is str:
        # TODO refactor so json case isn't left out from generator handling
        # (or just drop json support, which might make more sense...)
        if config.endswith('.json'):
            warnings.warn('not checking for need to pre-process config, '
                'because not currently support in the JSON input case'
            )
            return config

        # Not making an error here just to avoid duplicating validation in input
        # done in load(...)
        if not config.endswith('.yaml'):
            return config

        # TODO so that i don't need to worry about preventing these errors if
        # the yaml has equivalent data, just always err if one of these things
        # is set and the config tries to override it? (which errors/things?)

        with open(config, 'r') as f:
            generator_yaml_dict = yaml.safe_load(f)

    elif type(config) is dict:
        generator_yaml_dict = config

    elif config is None:
        raise NotImplementedError

    else:
        # TODO TODO refactor all this config type validation to one fn to
        # generate this [type of] error
        raise ValueError('config type not recognized')

    # TODO TODO provide way of listing available generators and certain
    # documentation about each, like required[/optional] keys, what each does,
    # as well as maybe printing docstring for each?

    # This means that the protobuf message(s) we define will cause problems if
    # it ever also would correspond to YAML/JSON with this 'generator' key at
    # the same level.
    if 'generator' not in generator_yaml_dict:
        # Intentionally not erring in the case where the default is set, because
        # that would be too annoying. Currently just silently doing nothing (in
        # here) if no generator and if the only indication we should use the
        # hardware config is the default specified in that env var.
        if hardware_config is not None:
            raise ValueError('hardware_config only valid if using a generator '
                "(specified via 'generator: <generator-name>' line in YAML "
                'config)'
            )

        return config

    hardware_yaml_dict = load_hardware_config(hardware_config)

    if hardware_yaml_dict is not None:
        # assumes all hardware specific keys can be detected at the top level
        # (so far the case, i believe, at least for expected inputs to
        # preprocessors)
        if any([k in common.hardware_specific_keys for k in generator_yaml_dict
            ]):
            # so that there is no ambiguity as to which should take precedence
            # TODO maybe actually embed path to offending config in this case
            raise ValueError('some of hardware_specific_keys='
                f'{common.hardware_specific_keys} are defined in config. '
                'this is invalid when hardware_config is specified.'
            )

        generator_yaml_dict.update(hardware_yaml_dict)
        
    generator = generator_yaml_dict['generator']

    if generator == 'basic':
        generator_fn = basic.make_config_dict

    elif generator == 'pair_concentration_grid':
        generator_fn = pair_concentration_grid.make_config_dict

    else:
        raise NotImplementedError(f"generator '{generator}' not supported")

    # TODO maybe just pprint the dict? or don't print this line at all in that
    # case?
    config_str = config if type(config) is str else 'passed dict'
    print(f"Using the '{generator}' generator configured with "
        f"{config_str}"
    )
    # Output will be either a dict or a list of dicts. In the latter case,
    # each should be written to their own YAML file.
    generated_config = generator_fn(generator_yaml_dict)

    save_generator_output = generator_yaml_dict.get(
        'save_generator_output', True
    )
    if not save_generator_output:
        if type(generated_config) is dict:
            # TODO maybe a less jargony message here?
            warnings.warn("not saving generator output (because "
                "'save_generator_output: False' in config)!"
            )
            return generated_config
        else:
            raise ValueError("save_generator_output must be True (the default) "
                'in case where generator produces a sequence of configuration '
                'files'
            )

    # TODO probably want to save the config + version of the code in the
    # case when a generator isn't used regardless (or at least have the
    # option to do so...) (not sure i do want this...)
    # TODO might want to use a zipfile to include the extra generator
    # information in that case. or just always a zipfile then for
    # consistency?

    # TODO TODO allow configuration of path these are saved at? at CLI, in
    # yaml, env var, or where? default to `generated_stimulus_configs` or
    # something, if not just zipping with other stuff, then maybe call it
    # something else?

    # TODO probably want to save generator_yaml_dict (and generator too, if
    # user defined...)? maybe as part of a zip file? or copy alongside w/
    # diff suffix or something?
    # (though aren't keys from that in generated yaml anyway? or no?)

    # TODO might want to refactor so this function can also just return the
    # file contents it just wrote (to not need to re-read them), but then
    # again, that's probably pretty trivial...

    # TODO should i be using safe_dump instead? (modify SafeDumper instead
    # of Dumper if so)
    # So that there are not aliases (references) within the generated YAML
    # (they make it less readable).
    # https://stackoverflow.com/questions/13518819
    yaml.Dumper.ignore_aliases = lambda *args : True

    # TODO what is default_style kwarg to pyyaml dump? docs don't seem to
    # say...
    # TODO maybe i want to make a custom dumper that just uses this style
    # for pin groups though? right now it's pretty ugly when everything is
    # using this style...
    # Setting this to True would make lists single-line by default, which I
    # want for terminal stuff, but I don't like what this flow style does
    # elsewhere.
    default_flow_style = False

    # TODO maybe refactor two branches of this conditional to share a bit
    # more code?
    if type(generated_config) is dict:
        yaml_dict = generated_config

        generated_yaml_fname = \
            datetime.now().strftime('%Y%m%d_%H%M%S_stimuli.yaml')

        print(f'Writing generated YAML to {generated_yaml_fname}')
        assert not exists(generated_yaml_fname)
        with open(generated_yaml_fname, 'w') as f:
            yaml.dump(yaml_dict, f, default_flow_style=default_flow_style)
        print()

        return generated_yaml_fname

    # TODO what type(s) is/are generated_config here? a list of dicts, right?
    else:
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        generated_config_dir = timestamp_str + '_stimuli'
        # TODO maybe also print each filename that is saved?
        print(f'Writing generated YAML under ./{generated_config_dir}/')
        assert not exists(generated_config_dir)
        os.mkdir(generated_config_dir)

        for i, yaml_dict in enumerate(generated_config):
            assert type(yaml_dict) is dict
            generated_yaml_fname = join(
                generated_config_dir, f'{timestamp_str}_stimuli_{i}.yaml'
            )
            assert not exists(generated_yaml_fname)
            with open(generated_yaml_fname, 'w') as f:
                yaml.dump(yaml_dict, f,
                    default_flow_style=default_flow_style
                )
        del generated_yaml_fname
        print()

        # TODO test this case (as well as previous branch of this
        # conditional)
        return generated_config_dir


def load_dict(config_dict, message=None):
    """Returns a populated protobuf message and a dict with extra metadata.
    """
    if message is None:
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
    """Parses JSON/YAML file or dict into an AllRequiredData message object.

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
            assert in_docker
            raise IOError('you must use the -i flag with docker run')

        # TODO check output of yaml dumping w/ default_flow_style=True again.
        # that might be an example of a case where YAML also would trigger this,
        # in which case i might want to do something different to detect JSON...
        if stdin_str.lstrip()[0] == '{':
            suffix = '.json'
        else:
            suffix = '.yaml'

        if in_windows():
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


def max_count(name):
    """Returns the int max_count field associated with name in olf.options.
    """
    field_and_sep = 'max_count:'
    for line in nanopb_options_lines:
        if line.startswith(name):
            rhs = line.split()[1]
            if rhs.startswith(field_and_sep):
                try:
                    return int(rhs[len(field_and_sep):])
                except ValueError as e:
                    # Parsing could fail if there is a comment right after int,
                    # but should just avoid making lines like that in the
                    # options file.
                    print('Fix this line in the olf.options file:')
                    print(line)
                    raise
    raise ValueError(f'no lines starting with name={name}')


def validate_port(port):
    """Raises ValueError if port seems invalid.
    
    Not currently intended to catch all possible invalid values, just some
    likely mistakes.
    """
    if type(port) is not str:
        raise ValueError('port not a str. did you pass it with -p?')

    # TODO TODO don't i have some code to detect port (at least in dev install
    # case?)? is that just in upload.py? not used here? i don't see anything
    # like that used to define port below...
    if port.endswith('.yaml') or port.endswith('.json'):
        raise ValueError('specify port after -p. currently this seems to be the'
            'config file path.'
        )
    
    # TODO actually check against what ports the system could have somehow?


# TODO TODO figure out max pulse feature size (micros overflow period, i think,
# divided by 2 [- 1?]?). check none of  [pre/post_]pulse_us / pulse_us are
# longer
# TODO rename 'settings' in the protobuf definition and in all references to be
# more spefific? in a way, everything in the AllRequiredData object is a
# setting... and it also might be nice to name the fn that validates
# AllRequiredData as validate_firmware_settings or something
def validate_settings(settings, **kwargs):
    """Raises ValueError if invalid settings are detected.
    """
    # 0 = disabled.
    if settings.balance_pin != 0:
        validate_pin(settings.balance_pin)

    if settings.timing_output_pin != 0:
        validate_pin(settings.timing_output_pin)

    if settings.recording_indicator_pin != 0:
        validate_pin(settings.recording_indicator_pin)

    if settings.WhichOneof('control') == 'follow_hardware_timing':
        if not settings.follow_hardware_timing:
            raise ValueError('follow_hardware_timing must be True if using it '
                'in place of the PulseTiming option'
            )
    if settings.no_ack:
        raise ValueError('only -k command line arg should set settings.no_ack')


def validate_pin_sequence(pin_sequence, warn=True):
    # Could make the max count validation automatic, but not really worth it.
    mc = max_count('PinSequence.pin_groups')
    gc = len(pin_sequence.pin_groups)
    if gc == 0:
        raise ValueError('PinSequence should not be empty')
    elif gc > mc:
        raise ValueError('PinSequence has length longer than maximum '
            f'({gc} > {mc})'
        )
    if warn:
        glens = {len(g.pins) for g in pin_sequence.pin_groups}
        if len(glens) > 1:
            warnings.warn(f'PinSequence has unequal length groups ({glens})')


# TODO might want to require communication w/ arduino here somehow?
# or knowledge of which arduino's are using which pins?
# (basically trying to duplicated the pin_is_reserved check on the arduino side,
# on top of other basic bounds checking)
def validate_pin(pin):
    """Raises ValueError in many cases where pin would fail on Arduino side.

    If an error is raised, the pin would definitely be invalid, but if no error
    is raised there are still some cases where the pin would not produce the
    intended results, as this has no knowledge of which pins are actually used
    on the Arduino, nor which version of an Arduino is being used.
    """
    assert type(pin) is int
    if pin < 0:
        raise ValueError('pin must be positive')
    elif pin in (0, 1):
        raise ValueError('pins 0 and 1 and reserved for Serial communication')
    # TODO can the arduino mega analog input pins also be used as digital
    # outputs? do they occupy the integers just past 53?
    # Assuming an Arduino Mega, which should have 53 as the highest valid
    # digital pin number (they start at 0).
    elif pin > 53:
        raise ValueError('pin numbers >53 invalid')


# TODO why do i have this taking **kwargs again?
def validate_pin_group(pin_group, **kwargs):
    """Raises ValueError if invalid pin_group is detected.
    """
    mc = max_count('PinGroup.pins')
    gc = len(pin_group.pins)
    if gc == 0:
        raise ValueError('PinGroup should not be empty')
    elif gc > mc:
        raise ValueError(f'PinGroup has {gc} pins (> max {mc}): {pin_group}')

    if len(pin_group.pins) != len(set(pin_group.pins)):
        raise ValueError('PinGroup has duplicate pins: {pin_group}')

    for p in pin_group.pins:
        validate_pin(p)


# TODO rename to _full_name... if i end up switching to that one
# Each function in here should take either **kwargs (if no potential warnings)
# or warn=True kwarg. They should return None and may raise ValueError.
_name2validate_fn = {
    'Settings': validate_settings,
    'PinSequence': validate_pin_sequence,
    'PinGroup': validate_pin_group
}
# TODO try to find a means of referencing these types that works in both the
# ubuntu / windows deployments. maybe the second syntax would work in both
# cases? test on ubuntu.
try:
    # What I had been using in the previously tested Ubuntu deployed versions.
    msg = pyext._message
    repeated_composite_container = msg.RepeatedCompositeContainer
    repeated_scalar_container = msg.RepeatedScalarContainer

# AttributeError: module 'google.protobuf.pyext' has no attribute '_message'
except AttributeError:
    from google.protobuf.internal import containers
    repeated_composite_container = containers.RepeatedCompositeFieldContainer
    repeated_scalar_container = containers.RepeatedScalarFieldContainer

def validate(msg, warn=True, _first_call=True):
    """Raises ValueError if msg validation fails.
    """
    if isinstance(msg, repeated_composite_container):
        for value in msg:
            validate(value, warn=warn, _first_call=False)
        return
    elif isinstance(msg, repeated_scalar_container):
        # Only iterating over and validating these elements to try to catch any
        # base-case types that I wasn't accounting for.
        for value in msg:
            validate(value, warn=warn, _first_call=False)
        return

    try:
        # TODO either IsInitialized or FindInitializationErrors useful?
        # latter only useful if former is False or what? see docs
        # (and are the checks that happen in parsing redundant with these?)
        # TODO i assume UnknownFields is checked at parse time by default?

        # TODO remove any of the following checks that are redundant w/ the
        # (from json) parsers
        if not msg.IsInitialized():
            raise ValueError()

        elif msg.FindInitializationErrors() != []:
            raise ValueError()

        elif len(msg.UnknownFields()) != 0:
            raise ValueError()

    except AttributeError:
        if _first_call:
            # Assuming if it were one of this top level types, it would have
            # all the methods used in the try block, and thus it wouldn't have
            # triggered the AttributeError. maybe a better way to phrase...
            raise ValueError('msg should be a message type from olf_pb2 module')

        if type(msg) not in (int, bool):
            raise ValueError(f'unexpected type {type(msg)}')
        return

    name = msg.DESCRIPTOR.name
    full_name = msg.DESCRIPTOR.full_name
    assert name == full_name, \
        f'{name} != {full_name} decide which one to use and fix code'

    if name in _name2validate_fn:
        _name2validate_fn[name](msg, warn=warn)
        # Not returning here, so that i don't have to also implement recursion
        # in PinSequence -> PinGroup

    # The first element of each tuple returned by ListFields is a
    # FieldDescriptor object, but we are using (the seemingly equivalent)
    # msg.DESCRIPTOR instead.
    for _, value in msg.ListFields():
        validate(value, warn=warn, _first_call=False)


flow_setpoints_sequence_key = 'flow_setpoints_sequence'
# TODO later, support some other IDs (maybe some USB unique IDs or something in
# alicat manufacturer data [which can in theory by queried from devices, though
# i don't think numat/alicat currently supports this via one of their provided
# functions)
required_flow_setpoint_keys = ('port', 'sccm')
def validate_flow_setpoints_sequence(flow_setpoints_sequence, warn=True):
    required_key_set = set(required_flow_setpoint_keys)

    all_seen_ports = set()
    trial_setpoint_sums = set()
    for trial_setpoints in flow_setpoints_sequence:
        curr_trial_setpoint_sum = 0.0
        for one_controller_setpoint in trial_setpoints:
            curr_key_set = set(one_controller_setpoint.keys())
            if not curr_key_set == required_key_set:
                missing_keys = required_key_set - curr_key_set
                raise ValueError(f'missing required keys {missing_keys} for at '
                    'least one entry in {flow_setpoints_sequence_key} from '
                    'configuration'
                )

            port = one_controller_setpoint['port']
            all_seen_ports.add(port)
            if type(port) is not str:
                raise ValueError(f'ports in {flow_setpoints_sequence_key} must '
                    'be of type str'
                )

            try:
                setpoint = float(one_controller_setpoint['sccm'])
            except ValueError:
                raise ValueError(f'sccm values in {flow_setpoints_sequence_key}'
                    ' must be numeric'
                )

            if setpoint < 0:
                raise ValueError(f'sccm values in {flow_setpoints_sequence_key}'
                    ' must be non-negative'
                )
            curr_trial_setpoint_sum += setpoint

        trial_setpoint_sums.add(curr_trial_setpoint_sum)

    if warn and len(trial_setpoint_sums) > 1:
        warnings.warn('setpoint sum is not the same on each trial! '
            f'unique sums: {trial_setpoint_sums}'
        )

    # For now, we are going to require that each port that is referenced is
    # referenced in the list for each trial, for simplicity of downstream code.
    for trial_setpoints in flow_setpoints_sequence:
        trial_ports = {x['port'] for x in trial_setpoints}
        if trial_ports != all_seen_ports:
            missing = all_seen_ports - trial_ports
            raise ValueError('each port must be referenced in each element '
                f'of flow_setpoints_sequence. current trial missing: {missing}'
            )

    # TODO warn if sum across flow meters at each trial ever changes across
    # trials


def validate_config_dict(config_dict, warn=True):
    """Raises ValueError if config_dict has some invalid data.

    Doesn't check firmware settings in the `AllRequiredData` object, which is
    currently handled by `validate`.
    """
    # there's other stuff that could be checked here, but just dealing w/ some
    # of the possible config problems when adding flow controller support for
    # now
    if flow_setpoints_sequence_key in config_dict:
        # TODO test this w/ actual valid input to enable follow_hardware_timing
        settings = config_dict['settings']
        if settings.get('follow_hardware_timing', False):
            # (because we don't know how long the trials will be in this case,
            # and we don't know when they will happen, so we can't change flow
            # in advance)
            raise ValueError('flow setpoints sequence can not be used in '
                'follow_hardware_timing case'
            )
        #

        flow_setpoints_sequence = config_dict[flow_setpoints_sequence_key]

        # should be equal to len(all_required_data.pin_sequence.pin_groups)
        # which was derived from the data in config_dict
        pin_groups = config_dict['pin_sequence']['pin_groups']

        f_len = len(flow_setpoints_sequence)
        p_len = len(pin_groups)
        if f_len != p_len:
            raise ValueError(f'len({flow_setpoints_sequence_key}) != len('
                f'pin_sequence.pin_groups) ({f_len} != {p_len})'
            )

        validate_flow_setpoints_sequence(flow_setpoints_sequence, warn=warn)


def parse_baud_from_sketch():
    """Returns int baud rate parsed from the firmware .ino.

    Raises ValueError if baud rate cannot be parsed.

    Used to determine which baud rate the host computer should use when trying
    to communicate with the Arduino via serial (USB).
    """
    sketch = join(this_package_dir, 'firmware', 'olfactometer',
        'olfactometer.ino'
    )
    with open(sketch, 'r') as f:
        lines = f.readlines()

    begin_prefix = 'Serial.begin('
    found_line = False
    for line in lines:
        if begin_prefix in line:
            if found_line:
                raise ValueError(f'too many {begin_prefix} lines in sketch to '
                    'parse baud rate'
                )
            found_line = True
            baud_line = line

    if not found_line:
        raise ValueError('no lines containing {begin_prefix} in sketch. could '
            'not parse baud rate'
        )

    parts = baud_line.split('(')
    assert len(parts) == 2
    parts = parts[1].split(')')
    assert len(parts) == 2
    baud_rate = int(parts[0])
    return baud_rate


# TODO TODO also have python parse the "trial: <n>, pins(s): ..." messages from
# arduino (when sent?) and check that timing is at least roughly right, in the
# pulse timing case

# Using an 8 bit, unsigned type to represent this on the Arduino side.
MAX_MSG_NUM = 255
curr_msg_num = 0
def write_message(ser, msg, verbose=False, use_message_nums=True,
    arduino_debug_prints=True, ignore_ack=False):
    """
    Args:
    ser (serial.Serial): serial device to receive the message

    msg (protobuf generated class): must have a `SerializeToString` method

    use_message_nums (bool, default=True): matches the USE_MESSAGE_NUMS
        preprocessor flag in the sketch. will number messages so the Arduino
        side can check it is not missing any.

    arduino_debug_prints (bool, default=False): if True, reads all bytes in 
        buffer before writing message num, to try to ensure the next byte we
        get back is just the message num.
    """
    # Since we are updating it in here, this is required.
    global curr_msg_num

    serialized = msg.SerializeToString()
    assert type(serialized) is bytes

    # TODO check this calculation is still correct for stuff with "repeated"
    # things in them
    # https://www.datadoghq.com/blog/engineering/protobuf-parsing-in-python/
    size = len(serialized)
    varint_size = _VarintBytes(size)

    def print_bytes(bs):
        s = bs.hex()
        print(' '.join([a+b for a,b in zip(s[::2], s[1::2])]))

    def write_bytes(bs):
        assert type(bs) is bytes
        n_bytes_written = ser.write(bs)
        assert n_bytes_written == len(bs)

    def crc16_0x1021(bs):
        # This uses polynomial 0x1021 (same as what I'm using on Arduino side)
        crc = binascii.crc_hqx(varint_size + serialized, 0xFFFF)

        # TODO also check input size (...why?) / that output of crc *should* fit
        # into 2 bytes?

        # This 'big' [Endian] byte order works for comparing on Arduino side,
        # with current code there.
        crc_bytes = crc.to_bytes(2, 'big')
        assert type(crc_bytes) is bytes and len(crc_bytes) == 2
        return crc_bytes

    # TODO add unit tests where random parts of data and / or crc are changed
    # (after crc calculation, but before sending) (-> verify failure)
    crc_bytes = crc16_0x1021(varint_size + serialized)

    '''
    if verbose:
        print('size: ', end='')
        print_bytes(varint_size)
        print('serialized: ', end='')
        print_bytes(serialized)
    '''

    n_bytes = len(varint_size) + len(serialized) + 2
    if use_message_nums:
        n_bytes += 1

    if verbose:
        print(f'writing {n_bytes} bytes to arduino...', flush=True, end='')

    # TODO TODO TODO need to check we don't write more than arduino's buffer
    # size (until acked)? just 64 bytes, right? assert to fail if single
    # messages exceed? or what? can't just ack at end of message then, if i
    # really need ack's to tell python it's ok to send more of one message...
    # SEEMS SO!!!

    # TODO how to get it to fail in this case / wait for other bytes for
    # decoding? (it currently does, w/ delimited, but add unit tests for both
    # under and over size)
    #write_bytes(serialized[:12])

    write_bytes(varint_size)
    write_bytes(serialized)
    write_bytes(crc_bytes)

    if use_message_nums:
        # TODO maybe do this between write and flush? does that guarantee it
        # won't be flushed earlier (probably not...)? (didn't seem to work there
        # anyway... though ser.out_waiting was zero all around it...)
        # This doesn't seem sufficient to prevent other prints from the Arduino
        # from obscuring the byte we want...
        if not ignore_ack and arduino_debug_prints:
            # TODO now that this is working with this hack, maybe delete
            # ignore_ack option?

            # At 115200 baud, seems we need to sleep at least about this long
            # for the any previous debug prints to all arrive. This is with an
            # Arduino-side flush right before the Arduino read for curr_msg_num
            # below. 0.005 did not work. Tested on Ubuntu 18.04 w/ USB3 port and
            # Arduino Mega.
            # TODO figure out fix that does not involve sleeping...
            time.sleep(0.008)
            n_input_bytes_discarded = ser.in_waiting
            # TODO maybe actually read them and format as below?
            ser.reset_input_buffer()

        # TODO this is unsigned if positive? arduino agrees on value for whole 8
        # bit range?
        before_sending_msg_num = time.time()
        write_bytes(curr_msg_num.to_bytes(1, 'big'))
        ser.flush()

        if not ignore_ack:
            # TODO should i just block for acknowledgement here, or make some
            # non-blocking interface?

            # TODO maybe keep track of times-to-ack, and maybe save as
            # experiment data even

            # Since the read has a timeout (not changeable by parameters to
            # read, it seems), we need to loop until we get the byte we want.
            while True:
                # TODO implement some timeout where we assume, beyond that, that
                # the arduino is in an error state? or otherwise, should i have
                # the arduino send a separate message with that state? maybe
                # before discussing msg num with it?
                arduino_msg_num_byte = ser.read()
                if len(arduino_msg_num_byte) > 0:
                    break

            time_to_msgnum_ack = time.time() - before_sending_msg_num

            arduino_msg_num = int.from_bytes(arduino_msg_num_byte, 'big')
            if arduino_msg_num != curr_msg_num:
                raise RuntimeError('arduino sent wrong message num. '
                    f'expected {curr_msg_num}, got {arduino_msg_num}.'
                )

        # TODO test wraparound behavior (+ w/ arduino)
        curr_msg_num = (curr_msg_num + 1) % MAX_MSG_NUM
    else:
        ser.flush()

    if verbose:
        print(' done')
        if use_message_nums and not ignore_ack:
            if arduino_debug_prints and n_input_bytes_discarded > 0:
                print(f'Discarded {n_input_bytes_discarded} bytes in input '
                    'buffer (before sending msg num)'
                )
            print(f'Time to msg num ack: {time_to_msgnum_ack:.3f}')


# TODO maybe add optional address (both kwargs, but require one, like [i think]
# in alicat code?)
_port2initial_get_output = dict()
def open_alicat_controller(port, save_initial_setpoints=True,
    check_gas_is_air=True, _skip_read_check=False, verbose=False):
    """Returns opened alicat.FlowController for controller on input port.

    Also registers atexit function to close connection.

    Unless all kwargs are False, queries the controller to set
    corresponding entry in `_port2initial_get_output`.
    """
    if save_initial_setpoints or check_gas_is_air:
        _skip_read_check = False

    # TODO thread through expected vid/pid or other unique usb identifiers for
    # controllers / the adapters we are using to interface with them. either in
    # env vars / hardware config / both. if using vid/pid, i measured
    # vid=5296 pid=13328 for our startech 4x rs232 adapters (on downstairs 2p
    # windows 7 machine using my tom-f-oconnell/test/alicat_test.py script).

    # Raies OSError under some conditions (maybe just via pyserial?)
    c = FlowController(port=port)
    atexit.register(c.close)
    # From some earlier testing, it seemed that first sign of incorrect opening
    # was often on first read, hence the read here without (necessarily) using
    # the values later.
    if not _skip_read_check:
        # TODO why did i all of a sudden get:
        # ValueError: could not convert string to float: 'Air' here?
        # didn't happen in .get in alicat_test.py i think...
        # i did just switch flow controllers...
        # (i think it might have been because one controller is defective or
        # something. worked after disconnecting it + it has what seems to be
        # an indication of an overpressure status, despite being unplugged.)

        # Will raise OSError if fails.
        data = c.get()

        if verbose:
            print('initial data:')
            pprint(data)

        # TODO probably delete this if i add support for MFC->gas config
        # (via c.set_gas(<str>) in numat/alicat api)
        if check_gas_is_air:
            gas = data['gas']
            if gas != 'Air':
                raise RuntimeError('gas on MFC at port {port} was configured '
                    f"to '{gas}', but was expecting 'Air'"
                )

        # TODO TODO TODO TODO if need be, to minimize loss of precision, check
        # that device units are configured correctly for how we are planning on
        # sending setpoints. again, https://github.com/numat/alicat/issues/14
        # may be relevant.

        _port2initial_get_output[port] = data

    return c


# TODO maybe initialize this w/ .get() in this open fn?
# (currently just used in set_flow_setpoints)
_port2last_flow_rate = dict()
def open_alicat_controllers(config_dict, _skip_read_check=False, verbose=False):
    """Returns a dict of str port -> opened alicat.FlowController
    """
    flow_setpoints_sequence = config_dict[flow_setpoints_sequence_key]

    port_set = set()
    port2flows = dict()
    for trial_setpoints in flow_setpoints_sequence:
        for one_controller_setpoint in trial_setpoints:
            port = one_controller_setpoint['port']
            port_set.add(port)

            sccm = one_controller_setpoint['sccm']
            if port not in port2flows:
                port2flows[port] = [sccm]
            else:
                port2flows[port].append(sccm)

    print('Opening flow controllers:')
    port2flow_controller = dict()
    sorted_ports = sorted(list(port_set))
    for port in sorted_ports:
        print(f'- {port} ...', end='', flush=True)
        c = open_alicat_controller(port, _skip_read_check=_skip_read_check,
            verbose=verbose
        )
        port2flow_controller[port] = c
        print('done', flush=True)

    # TODO maybe put behind verbose
    print('\n[min, max] requested flows (in mL/min) for each flow controller:')
    for port in sorted_ports:
        fmin = min(port2flows[port])
        fmax = max(port2flows[port])
        print(f'- {port}: [{fmin:.1f}, {fmax:.1f}]')
    print()

    # TODO TODO somehow check all flow rates (min/max over course of sequence)
    # are within device ranges
    # TODO TODO also check resolution (may need to still have access to a
    # unparsed str copy of the variable... not sure)

    return port2flow_controller


# TODO TODO maybe store data for how long each change of a setpoint took, to
# know that they all completed in a reasonable amount of time?
# (might also take some non-negligible amount of time to stabilize after change
# of setpoint, so would probably be good to have the electrical output of each
# flow meter in thorsync, if that works on our models + alongside serial usage)
_called_set_flow_setpoints = False
def set_flow_setpoints(port2flow_controller, trial_setpoints,
    check_set_flows=False, verbose=False):

    global _called_set_flow_setpoints
    if not _called_set_flow_setpoints:
        atexit.register(restore_initial_setpoints, port2flow_controller,
            verbose=verbose
        )
        _called_set_flow_setpoints = True

    if verbose:
        print('setting trial flow controller setpoints:')
    else:
        print('flows (mL/min): ', end='')
        short_strs = []

    erred = False
    for one_controller_setpoint in trial_setpoints:
        port = one_controller_setpoint['port']
        sccm = one_controller_setpoint['sccm']

        unchanged = False
        if port in _port2last_flow_rate:
            last_sccm = _port2last_flow_rate[port]
            if last_sccm == sccm:
                unchanged = True

        if verbose:
            # TODO TODO change float formatting to reflect achievable precision
            # (including both hardware and any loss of precision limitations of
            # numat/alicat api)
            cstr = f'- {port}: {sccm:.1f} mL/min'
            if unchanged:
                cstr += ' (unchanged)'
            print(cstr)
        else:
            # TODO maybe still show at least .1f if any inputs have that kind
            # of precision?
            short_strs.append(f'{port}={sccm:.0f}')

        if unchanged:
            continue

        c = port2flow_controller[port]
        # TODO TODO TODO convert units + make sure i'm calling in the way
        # to achieve the best precision
        # see: https://github.com/numat/alicat/issues/14
        # From numat/alicat docstring (which might not be infallible):
        # "in units specified at time of purchase"
        sccm = float(sccm)
        try:
            c.set_flow_rate(sccm)
        except OSError as e:
            # TODO also print full traceback
            print(e)
            erred = True
            continue

        _port2last_flow_rate[port] = sccm

        if check_set_flows:
            data = c.get()

            # TODO may need to change tolerance args because of precision limits
            if not math.isclose(data['setpoint'], sccm):
                raise RuntimeError('commanded setpoint was not reflected '
                    f'in subsequent query. set: {sccm:.1f}, got: '
                    f'{data["set_point"]:.1f}'
                )

            if verbose:
                print('setpoint check OK')

    if not verbose:
        print(','.join(short_strs))

    if erred:
        raise OSError('failed to change setpoint on one or more flow '
            'controllers'
        )


# TODO if i ever set gas (or anything beyond set points) rename to
# restore_initial_flowcontroller_settings or something + also restore those
# things here
def restore_initial_setpoints(port2flow_controller, verbose=False):
    """Restores setpoints populated on opening each controller.
    """
    if verbose:
        print('Restoring initial flow controller set points:')

    for port, c in port2flow_controller.items():
        initial_setpoint = _port2initial_get_output[port]['setpoint']

        if verbose:
            # maybe isn't always really mL/min across all our MFCs...
            print(f'- {port}: {initial_setpoint:.1f} mL/min')

        c.set_flow_rate(initial_setpoint)


# (kwarg here?)?
def format_odor(odor_dict):
    odor_str = odor_dict['name']
    if 'log10_conc' in odor_dict:
        log10_conc = odor_dict['log10_conc']

        # TODO might want to also format in which manifold for clarity in e.g.
        # pair_concentration_grid.py stuff, in (name == 'solvent'?) solvent case

        # This is my convention for indicating the solvent used for a particular
        # odor, in at least the experiments using pair_concentration_grid.py.
        if log10_conc is None:
            return f'solvent for {odor_str}'

        # TODO limit precision if float
        odor_str += ' @ {}'.format(log10_conc)

    return odor_str


def format_mixture_pins(pins2odors, trial_pins, delimiter=' AND '):
    return delimiter.join([format_odor(pins2odors[p])
        for p in trial_pins if p in pins2odors
    ])


def print_odor(odor_dict):
    print(format_odor(odor_dict))


def format_duration_s(duration_s):
    td = timedelta(seconds=duration_s)
    td_str = str(td)

    h, m, s = tuple(int(x) for x in td_str.split(':'))
    parts = [f'{h}h', f'{m}m', f'{s}s']
    if h == 0:
        if m == 0:
            parts = parts[2:]
        else:
            parts = parts[1:]

    return ''.join(parts)


def seconds_per_trial(all_required_data):
    """Returns float seconds per trial given `olf_pb2.AllRequiredData` object.

    Raises `ValueError` if timing information is not specified (e.g. if
    follow_hardware_timing is specified instead).
    """
    settings = all_required_data.settings
    if settings.WhichOneof('control') == 'follow_hardware_timing':
        raise ValueError('follow_hardware_timing case not supported')

    timing = settings.timing
    return (timing.pre_pulse_us + timing.pulse_us + timing.post_pulse_us) / 1e6


def number_of_trials(all_required_data):
    """Returns number of trials given `olf_pb2.AllRequiredData` object.
    """
    return len(all_required_data.pin_sequence.pin_groups)


def curr_trial_index(start_time_s, config_or_trial_dur, n_trials=None):
    """Returns index of current trial via start time and config.

    If current time is past end of last trial, `None` will be returned.

    Can also take float duration of a single trial in seconds in place of
    config. If passing config, should be of type `olf_pb2.AllRequiredData`.
    """
    try:
        one_trial_s = float(config_or_trial_dur)
        assert n_trials is not None, ('must pass n_trials if passing float '
            'seconds per trial, rather than full config'
        )
    except TypeError:
        one_trial_s = seconds_per_trial(config_or_trial_dur)
        n_trials = number_of_trials(config_or_trial_dur)

    since_start_s = time.time() - start_time_s
    trial_idx = math.floor(since_start_s / one_trial_s)

    return trial_idx if trial_idx < n_trials else None


def get_trial_pins(pin_sequence, trial_index):
    """Returns list of int pins for trial at given index.
    """
    return list(pin_sequence.pin_groups[trial_index].pins)


# TODO add fn that takes a pin_sequence (or pinlist_at_each_trial equivalent),
# and pins2odors, and prints it all nicely


# TODO TODO maybe add a block=True flag to allow (w/ =False) to return, to not
# need to start this function in a new thread or process when trying to run the
# olfactometer and other code from one python script. not needed as a command
# line arg, cause already a separate process at that point.
# (or would this just make debugging harder, w/o prints from arduino?)
# TODO TODO make sure version_mismatch checks that installed version is the used
# version, if/when doing things that way (e.g. catch the case where the version
# of util.py from the cwd, if cwd=~/src/olfactometer) has changes not reflected
# in the version of the installed `olf` script)
baud_rate = None
def run(config, port=None, fqbn=None, do_upload=False,
    allow_version_mismatch=False, ignore_ack=False, try_parse=False,
    timeout_s=2.0, pause_before_start=True, check_set_flows=False,
    verbose=False, _first_run=True):
    """Runs a single configuration file on the olfactometer.

    Args:
    config (str|dict|None): path to YAML or JSON file with settings
        defining the olfactometer behavior. If `None` is passed, the config is
        read from stdin.
    """
    global curr_msg_num
    global baud_rate
    # We want to reset this at the beginning of each run of a single config
    # file. If there are multiple, the Arduino sketch should reset between them.
    curr_msg_num = 0

    # TODO rename all_required_data to indicate it is the protobuf message(s)?
    all_required_data, config_dict = load(config)
    settings = all_required_data.settings
    pin_sequence = all_required_data.pin_sequence

    # TODO i thought there wasn't optional stuff? so how come it doesn't fail
    # w/o balance_pin, etc passed? (it also doesn't print them, which i might
    # expect if they just defaulted to 0...) idk...
    # (if defaults to 0, remove my reimplementation of that logic in basic
    # generator)

    # TODO especially if i print the YAML name before each in a sequence (when
    # running a sequence of YAML files), also print it here
    if verbose or try_parse:
        print('Config data used by microcontroller:')
        print(all_required_data)
        # Stuff that would be behind the 'settings' / 'pin_sequence' keys should
        # be printed in the line above.
        extra_config = {k: v for k, v in config_dict.items()
            if k not in ('settings', 'pin_sequence')
        }
        # TODO maybe print this circa check_need_to_preprocess... call, to also
        # print 'generator:', and other keys that might not make it to generator
        # output? or i guess it's fine here as long as most keys (just
        # 'generator' and maybe a couple other specific exceptions) are just
        # transferred directly to generator output (by default)....
        # (or print the stuff that doesn't make it to this, in that case, and if
        # verbose / try_parse?)
        if len(extra_config) > 0:
            print('Additional config data:')
            pprint(extra_config)

    # TODO TODO make the function named `validate` work on config_dict, and
    # rename current `validate` to something more specific, indicating it should
    # be used w/ the AllRequiredData object (the settings that get communicated
    # to the firmware)
    warn = True
    validate_config_dict(config_dict, warn=warn)
    validate(all_required_data, warn=warn)

    if check_set_flows and flow_setpoints_sequence_key not in config_dict:
        raise ValueError('check_set_flows=True only valid if '
            f'{flow_setpoints_sequence_key} is appropriately populated in '
            'config'
        )

    if try_parse:
        return

    if check_set_flows:
        warnings.warn('check_set_flows should only be used for debugging')

    if ignore_ack:
        if _first_run:
            warnings.warn('ignore_ack should only be used for debugging')

        # Default is False
        settings.no_ack = True

    port, fqbn = upload.get_port_and_fqbn(port=port, fqbn=fqbn)

    # TODO maybe factor all this first_run stuff into its own fn and call before
    # first run() call in sequence case, so the first "Config file: ..." doesn't
    # have the warnings and baud rate between it and the rest (for consistency)?
    if not _first_run:
        assert baud_rate is not None
    else:
        if allow_version_mismatch:
            warnings.warn('allow_version_mismatch should only be used for '
                'debugging!'
            )

        # TODO maybe move this function in here...
        py_version_str = upload.version_str()
        # update check not working yet
        '''
        py_version_str = upload.version_str(update_check=True,
            update_on_prompt=True
        )
        '''

        if do_upload:
            # TODO save file modification time at upload and check if it has
            # changed before re-uploading with this flag... (just to save
            # program memory life...) (docker couldn't use...)

            # TODO maybe refactor back and somehow have a new section of
            # argparser filled in without flags here, indicating they are upload
            # specific flags. idiomatic way to do that? subcommand?

            # This raises a RuntimeError if the compilation / upload returns a
            # non-zero exit status, stopping further steps here, as intended.
            upload.main(port=port, fqbn=fqbn, verbose=verbose)

        # TODO TODO also lookup latest hash on github and check that it's not in
        # any of the hashes in our history (git log), and warn / prompt about
        # update if github version is newer

        if (not allow_version_mismatch and
            py_version_str == upload.no_clean_hash_str):

            # TODO try to move this error to before upload would happen
            # (if upload is requested)
            raise ValueError('can not run with uncommitted changes without '
                'allow_version_mismatch (-a), which is only for debugging. '
                'please commit and re-upload.'
            )

        validate_port(port)

        # This is set into a global variable, so that on subsequent config files
        # in the same run of this script, it doesn't need to be parsed / printed
        # again.
        baud_rate = parse_baud_from_sketch()
        print(f'Baud rate (parsed from Arduino sketch): {baud_rate}\n')

    flow_setpoints_sequence = None
    if flow_setpoints_sequence_key in config_dict:
        port2flow_controller = open_alicat_controllers(config_dict,
            verbose=verbose
        )

        flow_setpoints_sequence = config_dict[flow_setpoints_sequence_key]

        if not verbose:
            print('Initial ', end='')

        set_flow_setpoints(port2flow_controller,
            flow_setpoints_sequence[0], verbose=verbose
        )
        print()

    n_trials = number_of_trials(all_required_data)
    if not settings.follow_hardware_timing:
        one_trial_s = seconds_per_trial(all_required_data)
        expected_duration_s = n_trials * one_trial_s

        duration_str = format_duration_s(expected_duration_s)

        expected_finish = \
            datetime.now() + timedelta(seconds=expected_duration_s)

        finish_str = expected_finish.strftime('%I:%M%p').lstrip('0')

        print(f'{n_trials} trials')
        print(f'Will take: {duration_str}, finishing at {finish_str}\n')

    # TODO (low priority) maybe only print pins that differ relative to last
    # pins2odors, in a sequence? or indicate those that are the same?
    pins2odors = None
    pins2odors_key = 'pins2odors'
    if pins2odors_key in config_dict:
        pins2odors = config_dict[pins2odors_key]

        # TODO TODO also print balances here (at least optionally) (both in
        # single / multiple manifold cases). maybe visually separated somewhat.
        print('Pins to connect odors to:')
        for p, o in pins2odors.items():
            print(f' {p}: {format_odor(o)}')

    if pause_before_start:
        # TODO or maybe somehow have this default to True if a generator is
        # being used (especially if i don't add some way to have that re-use
        # pins, or if i do and it's disabled)
        # TODO maybe warn if no pins2odors, in this case
        # TODO maybe prompt user to connect arduino if after Enter is pressed
        # here, the serial device would fail to be found in the next line
        input('Press Enter once the odors are connected')

    # TODO TODO define some class that has its own context manager that maybe
    # essentially wraps the Serial one? (just so people don't need that much
    # boilerplate, including explicit calls to pyserial, when using this in
    # other python code)
    with serial.Serial(port, baud_rate, timeout=0.1) as ser:
        print('Connected')
        connect_time_s = time.time()

        while True:
            version_line = ser.readline()
            if len(version_line) > 0:
                arduino_version_str = version_line.decode().strip()
                break

            if time.time() - connect_time_s > timeout_s:
                raise RuntimeError('arduino did not respond within '
                    f'{timeout_s:.1f} seconds. have you uploaded the code? '
                    're-run with -u if not.'
                )

        if _first_run:
            if not allow_version_mismatch:
                    if arduino_version_str == upload.no_clean_hash_str:
                        raise ValueError('arduino code came from dirty git'
                            ' state. please commit and re-upload.'
                        )
                    if py_version_str != arduino_version_str:
                        raise ValueError('version mismatch (Python: '
                            f'{py_version_str}, Arduino: {arduino_version_str}'
                            ')! please re-upload (add the -u flag)!'
                        )

            elif verbose:
                # TODO make sure this doesn't cause windows case to fail
                # (because these are not defined) if verbose=True. might need to
                # move things around a bit.
                print('Python version:', py_version_str)
                print('Arduino version:', arduino_version_str)

        write_message(ser, settings, ignore_ack=ignore_ack, verbose=verbose)

        write_message(ser, pin_sequence, ignore_ack=ignore_ack, verbose=verbose)

        # TODO maybe use:
        # if settings.WhichOneof('control') == 'follow_hardware_timing':
        # here? seems to work though...
        if settings.follow_hardware_timing:
            print('Ready (waiting for hardware triggers)')
        else:
            print('Starting')
            seen_trial_indices = set()
            last_trial_idx = None

        # TODO err in not settings.follow_hardware_timing case, if enough time
        # has passed before we get first trial status print?

        start_time_s = time.time()

        readline_times = []

        while True:
            if not settings.follow_hardware_timing:
                # Couldn't parse output of readline() below in
                # follow_hardware_timing case, because those prints come at [I
                # believe] the odor pulse offsets there, so we would at least
                # need to hardcode some delays or something.
                trial_idx = curr_trial_index(start_time_s, one_trial_s,
                    n_trials
                )

                # If there were much worry that some of the `ser.readline()`
                # calls below (the only other thing in this loop that should be
                # slow) could take long, we might want to set these flow
                # setpoints in some parallel thread/process / use non-blocking
                # IO in place of this readline() call. However, when I measured
                # these delays they seemed stable around ~0.10[1-3]s. Most are
                # right on 0.100s, but maybe slightly longer if actually reading
                # data?

                # possible that trial_idx could be returned as None very briefly
                # at the end
                if trial_idx != last_trial_idx and trial_idx is not None:
                    trial_pins = get_trial_pins(pin_sequence, trial_idx)

                    # TODO maybe also suffix w/ pins in parens if verbose

                    # TODO get rid of '(s)' and just make plural when approp
                    # TODO fix how in case where using flow controllers + no
                    # pins2odors, printing order / spacing is diff on the first one
                    # (wrt the 'trial: ...' line)
                    if pins2odors is not None:
                        # p not in pins2odors when it's an explicit balance pin
                        print(f'trial: {trial_idx + 1}/{n_trials}, odor(s):',
                            format_mixture_pins(pins2odors, trial_pins)
                        )
                        # TODO maybe try to suffix w/ coarse tqdm progress
                        # within each trial, to get an indication of when next
                        # one is up.
                        # https://stackoverflow.com/questions/62048408
                        # maybe even visually change / mark odor region/onset
                        # on progress bar?

                    # for the most part, this seemed to get printed some
                    # *roughly* 0.1-0.5s after the old print passed through from
                    # the arduino. could be consistent w/ just the ~0.1s i
                    # observed for max_readline_s
                    #print('trial_idx:', trial_idx)

                    if flow_setpoints_sequence is not None:
                        # TODO TODO TODO even if not verbose, should print
                        # something if flow is anything other than either
                        # default or initial flows when MFCs were turned on.
                        # or just always. just fit in the same line? or one
                        # line after?
                        set_flow_setpoints(
                            port2flow_controller,
                            flow_setpoints_sequence[trial_idx],
                            check_set_flows=check_set_flows,
                            verbose=verbose
                        )
                        print()

                    last_trial_idx = trial_idx
                    seen_trial_indices.add(trial_idx)

            readline_t0 = time.time()

            line = ser.readline()

            readline_t1 = time.time()
            readline_s = readline_t1 - readline_t0
            readline_times.append(readline_s)

            if len(line) > 0:
                try:
                    line = line.decode()
                    # still letting arduino do printing in this case for now,
                    # cause way i'm doing it in !follow_hardware_timing case
                    # relies on the known timing info.
                    if pins2odors is None or settings.follow_hardware_timing:
                        print(line, end='')

                    if line.strip() == 'Finished':
                        finish_time_s = time.time()
                        break

                    # TODO mayyybe could parse trial pins reported and compare
                    # to expected. a bit paranoid though...
                    # (might be useful to print odors in follow_hardware_timing
                    # case too, but not sure i care that much about that case
                    # anymore)
                    #pins = [
                    #    int(p) for p in line.split(':')[-1].strip().split(',')
                    #]

                # Docs say decoding errors will be a ValueError or a subclass.
                # UnicodeDecodeError, for instance, is a subclass.
                except ValueError as e:
                    print(e)
                    print(line)

        max_readline_s = max(readline_times)
        # Were all right around 0.1s last I measured
        if flow_setpoints_sequence is not None and max_readline_s > 0.11:
            warnings.warn('max readline time might have been long enough to '
                'cause problems setting flow rates in a timely manner '
                f'({max_readline_s:.3f}s)'
            )

        duration_s = finish_time_s - start_time_s

        # If we are just triggering off of input pulses, as in
        # follow_hardware_timing case, we don't know how long trials will be.
        if not settings.follow_hardware_timing:
            max_duration_diff_s = 0.5
            duration_diff_s = duration_s - expected_duration_s
            if abs(duration_diff_s) > max_duration_diff_s:
                warnings.warn('experiment duration differed from expectation by'
                    f'{duration_diff_s:.3f} (or communication with something '
                    'took longer than normal to finish up at the end)'
                )

            expected_seen_trials_indices = set(range(n_trials))
            if not seen_trial_indices == expected_seen_trials_indices:
                missing = expected_seen_trials_indices - seen_trial_indices
                warnings.warn('flow controller updating might have missed '
                    'some trials!!!'
                )

            # i haven't yet seen this actually None, cause for whatever reason,
            # duration_s is usually something like ~0.008s less than
            # expected_duration_s. i guess because the time it takes to intiate
            # stuff at the start, so None actually may never practically be
            # reached.
            '''
            trial_idx_after_finished = curr_trial_index(
                start_time_s, one_trial_s, n_trials
            )
            if trial_idx_after_finished is not None:
                warnings.warn('expected curr_trial_index to return None after '
                'microcontroller reports being finished'
                )
            '''


def main(config, hardware_config=None, _skip_config_preprocess_check=False,
    **kwargs):
    """
    config (str|dict|None)
    """

    # TODO TODO TODO add arg for excluding pins (e.g. for running basic.py
    # configured w/ tom_olfactometer_configs/one_odor.yaml after already hooking
    # up odors from the same generator configured w/
    # ""/glomeruli_diagnostics.yaml). accept either yaml file w/ pins2odors
    # (or just pins in pin_sequence?) or just a comma separated list of pins on
    # the command line. thread through to command line interfaces.
    # and should i have an option for just automatically finding the last
    # generated thing and excluding the pins in that? might want to set up an
    # env var for output directory first...

    if in_docker and config is not None:
        # TODO reword to be inclusive of directory case?
        raise ValueError('passing filenames to docker currently not supported. '
            'instead, redirect stdin from that file. see README for examples.'
        )

    if config is None:
        warnings.warn('setting _skip_config_preprocess_check=True as '
            'check_need_to_preprocess_config currently does not support '
            'case where config is read from stdin.'
        )
        _skip_config_preprocess_check = True

    # TODO TODO if i'm going to allow config to be either a list of files
    # or a directory with config files, make type consistent (make `config`
    # a list in nargs=1 case)? + don't check for need to preprocess if input is
    # a list (only support terminal config files in that case)
    # TODO maybe do support a sequence of config files though (also require to
    # have suffix ordering them), to generate full diagnostic -> pair ->
    # diagnostic for my pair experiments? probably not, cause # of pairs i can
    # actually do will probably vary a lot from fly-to-fly...
    # TODO add CLI flag to prevent this from saving anything (for testing)
    # (maybe have the flag also just print the YAML(s) the generator creates
    # then?)
    if not _skip_config_preprocess_check:
        # TODO TODO TODO fix so config==None (->stdin input) (used in docker
        # case) works with this too.
        config = check_need_to_preprocess_config(config,
            hardware_config=hardware_config
        )

    
    if config is None or type(config) is dict or (
        type(config) is str and isfile(config)):

        run(config, **kwargs)

    elif type(config) is str and isdir(config):
        config_files = glob.glob(join(config, '*'))

        # We expect each config file to follow this naming convention:
        # <x>_<n>.[yaml/json], where <x> can be anything (including containing
        # underscores, if you wish), and <n> is an integer used to order the
        # config files. Lower numbers will be executed first.
        order_nums = []
        for f in config_files:
            num_part = splitext(split(f)[1])[0].split('_')[-1]
            try:
                n = int(num_part)
                order_nums.append(n)
            except ValueError:
                raise ValueError(f'{config} had at least one file ({f}) that '
                    'did not have a number right before the extension, to '
                    'indicate order. exiting.'
                )
        config_files = [f for _, f in sorted(zip(order_nums, config_files),
            key=lambda x: x[0]
        )]

        first_run = True
        for i, config_file in enumerate(config_files):
            # TODO maybe (in addition to some abstractions / standards for
            # formatting odors in trials (rather than pins)) also have some
            # faculties for summarizing config files, and print that alongside /
            # in place of the file name? (e.g. the odors in the pair, for the
            # pair conc grid experiments)?
            print(f'Config file: {config_file} ({i+1}/{len(config_files)})')

            run(config_file, _first_run=first_run, **kwargs)

            if i < len(config_files) - 1:
                print()

            if first_run:
                first_run = False

    else:
        # TODO TODO does this break docker stdin based config specification? fix
        # if so.
        raise ValueError(f'config type {type(config)} not recognized. must be '
            'str path to file/directory, dict, or None to use stdin.'
        )


# TODO maybe move both of these argparse fns to cli_entry_points.py.
# one reason not to would be if i wanted to "from cli_entry_points import *"
# in __init__.py (need a line for each entrypoint for setup.py entry points to
# work)
def argparse_arduino_id_args(parser=None):
    """Returns argparse.ArgumentParser with --port and --fqbn args.

    `main_cli`, `valve_test_cli`, and `upload_cli` currently use these arguments
    to specify which arduino should be communicated with. --fqbn should only be
    needed for uploading to new types of boards?

    If parser is passed in, arguments will be added to that parser. Otherwise,
    a new parser is made first.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # TODO just detect? or still have this as an option? maybe have on default,
    # and detect by default? (might not be very easy to detect with docker,
    # at least not without using privileged mode as opposed to just passing one
    # specific port... https://stackoverflow.com/questions/24225647 )
    # maybe just use privileged though?
    parser.add_argument('-p', '--port', action='store', default=None,
        help='port the Arduino is connected to'
    )
    parser.add_argument('-f', '--fqbn', action='store', default=None,
        help='Fully Qualified Board Name, e.g.: arduino:avr:uno. corresponds to'
        ' arduino-cli -b/--fqbn. mainly for testing compilation with other '
        'boards. your connected board should be detected without needing to '
        'pass this.'
    )
    return parser


def argparse_run_args(parser=None):
    """Returns argparse.ArgumentParser with args shared by [main/valve_test]_cli

    If parser is passed in, arguments will be added to that parser. Otherwise,
    a new parser is made first.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    parser.add_argument('-u', '--upload', action='store_true', default=False,
        help='also uploads Arduino code before running'
    )
    argparse_arduino_id_args(parser)
    # TODO TODO uncomment if i restore upload.version_str to a working state
    '''
    parser.add_argument('-a', '--allow-version-mismatch', action='store_true',
        default=False, help='unless passed, git hash of arduino code will be '
        'checked against git hash of python code, and it will not let you '
        'proceed unless they match. re-upload arduino code with clean '
        '"git status" to fix mismatch without this flag.'
    )
    '''
    # TODO document OLFACTOMETER_DEFAULT_HARDWARE, and interactions with the
    # same keys already present in some YAML
    parser.add_argument('-r', '--hardware', action='store', default=None,
        help='[path to / prefix of] config specifying available valve pins and'
        'other important pins for a particular physical olfactometer. config '
        f'must be under {hardware_dir_envvar} to refer by prefix. see also '
        f'{default_hardware_envvar}.'
    )
    parser.add_argument('-y', '--no-wait', action='store_true', default=False,
        help='do not wait for user to press <Enter> before starting'
    )
    parser.add_argument('-v', '--verbose', action='store_true', default=False)

    return parser

