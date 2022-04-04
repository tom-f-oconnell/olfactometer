
import os
from os.path import split, join
import time
import subprocess
import warnings
from datetime import timedelta
import math
import argparse
from pathlib import Path
from typing import Dict, Any

import appdirs
# TODO use to make functions for printing vid/pid (or other unique ids for usb
# devices), which can be used to reference specific MFCs / arduinos in config
# (and also for listing ports corresponding to such devices).
# probably have env vars to set vid/pid (one each?), to not have to type out
# each time.
# TODO maybe also use whichever unique USB ID to configure a expected ID, so
# that if the wrong arduino is connected it can be detected?

from olfactometer import IN_DOCKER, THIS_PACKAGE_DIR, _DEBUG
from olfactometer.config_io import DEFAULT_HARDWARE_ENVVAR, HARDWARE_DIR_ENVVAR


# TODO rename from 'outputs' to 'python' or something, if this isn't also generating C
# side of things
def generate_protobuf_outputs():
    # TODO maybe only do this if installed editable / not installed and being
    # used from within source tree? (would probably have to be a way to include
    # build in setup.py... and not sure there is)
    # TODO only do this if proto_file has changed since the python outputs have
    # TODO TODO wait, why doesn't this need to use the nanopdb_generator, or
    # otherwise reference that? doesn't it need to be symmetric w/ firmware
    # definitions generated via nanopb?
    proto_file = join(THIS_PACKAGE_DIR, 'olf.proto')
    proto_path, _ = split(proto_file)
    p = subprocess.Popen(['protoc', f'--python_out={THIS_PACKAGE_DIR}',
        f'--proto_path={proto_path}', proto_file
    ])
    p.communicate()
    failure = bool(p.returncode)
    if failure:
        raise RuntimeError(f'generating python code from {proto_file} failed')


def in_windows():
    return os.name == 'nt'


def parse_baud_from_sketch():
    """Returns int baud rate parsed from the firmware .ino.

    Raises ValueError if baud rate cannot be parsed.

    Used to determine which baud rate the host computer should use when trying
    to communicate with the Arduino via serial (USB).
    """
    sketch = join(THIS_PACKAGE_DIR, 'firmware', 'olfactometer',
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


def format_odor(odor_dict, show_abbrevs=True):
    odor_str = odor_dict['name']

    if show_abbrevs and 'abbrev' in odor_dict:
        odor_str += f' ({odor_dict["abbrev"]})'

    if 'log10_conc' in odor_dict:
        log10_conc = odor_dict['log10_conc']

        if log10_conc == 0:
            return odor_str

        # TODO might want to also format in which manifold for clarity in e.g.
        # pair_concentration_grid.py stuff, in (name == 'solvent'?) solvent case

        # This is my convention for indicating the solvent used for a particular
        # odor, in at least the experiments using pair_concentration_grid.py.
        if log10_conc is None:
            return f'solvent for {odor_str}'

        # TODO limit precision if float
        odor_str += ' @ {}'.format(log10_conc)

    return odor_str


def format_mixture_pins(pins2odors, trial_pins, delimiter=' AND ',
    **format_odor_kwargs):

    return delimiter.join([format_odor(pins2odors[p], **format_odor_kwargs)
        for p in trial_pins if p in pins2odors
    ])


def format_duration_s(duration_s):
    td = timedelta(seconds=duration_s)
    td_str = str(td)

    h, m, s = tuple(float(x) for x in td_str.split(':'))
    parts = [f'{h:.0f}h', f'{m:.0f}m', f'{s:.0f}s']
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
    # TODO also calculate (expected) overrun of pulse_us depending on pulse train
    # settings
    return (timing.pre_pulse_us + timing.pulse_us + timing.post_pulse_us) / 1e6


def number_of_trials(all_required_data):
    """Returns number of trials given `olf_pb2.AllRequiredData` object.
    """
    return len(all_required_data.pin_sequence.pin_groups)


def time_config_will_take_s(all_required_data, print_=False):
    """Returns time (in seconds) config will take to run.

    Returns None if all_required_data.settings.follow_hardware_timing is True.
    """
    n_trials = number_of_trials(all_required_data)

    if print_:
        print(f'{n_trials} trials')

    if not all_required_data.settings.follow_hardware_timing:
        # TODO factor this out so i can calculate how long various trial structures
        # would be without needing to try to run them (or even an arduino) (+ printing
        # below)
        one_trial_s = seconds_per_trial(all_required_data)
        expected_duration_s = n_trials * one_trial_s

        duration_str = format_duration_s(expected_duration_s)

        if print_:
            print(f'Will take {duration_str} ({expected_duration_s:.0f}s)')

        return expected_duration_s

    else:
        if print_:
            print('Can not compute duration because following hardware timing')

        return None


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


def get_pins2odors(config_dict):
    """Returns dict: int -> odor or None if not in config_dict
    """
    return config_dict.get('pins2odors')


def print_pins2odors(config_dict, header=True, **format_odor_kwargs):
    pins2odors = get_pins2odors(config_dict)
    if pins2odors is None:
        return

    # TODO TODO also print balances here (at least optionally) (both in
    # single / multiple manifold cases). maybe visually separated somewhat.
    # (need to parse config_dict again for that?)
    if header:
        print('Pins to connect odors to:')

    for p, o in pins2odors.items():
        print(f' {p}: {format_odor(o, **format_odor_kwargs)}')

# TODO add fn that takes a pin_sequence (or pinlist_at_each_trial equivalent),
# and pins2odors, and prints it all nicely


def user_data_dir(mkdir=False):
    """Returns a Path to a directory for storing application state.

    Args:
        mkdir: if True, make directory (no error if already exists).
    """
    app_name = 'olf'
    app_author = 'tom-f-oconnell'
    app_data_dir = Path(appdirs.user_data_dir(app_name, app_author))

    if mkdir:
        app_data_dir.mkdir(parents=True, exist_ok=True)

    return app_data_dir


def get_last_attempted_cache_fname():
    """Returns a Path object for storing last attempted config file (for re-running)
    """
    app_data_dir = user_data_dir()
    last_attempted_cache_fname = app_data_dir / 'last_attempted_config_filename'
    return last_attempted_cache_fname


def get_last_attempted():
    """Returns relative and absolute paths to last attempted config file.

    Former is relative to where it was originally generated.

    Raises IOError if no record of past attempted config files.
    """
    if IN_DOCKER:
        raise RuntimeError('can not get last attempted config file in Docker')

    last_attempted_cache_fname = get_last_attempted_cache_fname()

    if not last_attempted_cache_fname.exists():
        raise IOError('no record of previously attempted config file!')

    text = last_attempted_cache_fname.read_text()
    lines = text.splitlines()

    assert len(lines) == 2, ('malformed file storing last attempted config '
        f'({last_attempted_cache_fname}). contents:\n{repr(text)}'
    )

    relative_path, abs_path = lines

    return relative_path, abs_path


def write_last_attempted_config_file(config_fname) -> None:
    """
    Writes relative and absolute paths to config_fname on separate lines of file
    returned by get_last_attempted_cache_fname()
    """
    if IN_DOCKER:
        warnings.warn('could not write last attempted config filename because in '
            'Docker'
        )
        return

    last_attempted_cache_fname = get_last_attempted_cache_fname(mkdir=True)

    cache_contents = f'{config_fname}\n{Path(config_fname).resolve()}'
    last_attempted_cache_fname.write_text(cache_contents)


def argparse_config_args(parser=None, *, config_path=True, hardware=True):
    if parser is None:
        parser = argparse.ArgumentParser()

    if config_path:
        parser.add_argument('config_path', type=str, nargs='?', default=None,
            help='.json/.yaml file containing all required data. see `load` '
            'function. reads config from stdin if not passed.'
        )

    if hardware:
        # TODO document OLFACTOMETER_DEFAULT_HARDWARE, and interactions with the
        # same keys already present in some YAML
        parser.add_argument('-r', '--hardware', action='store', default=None,
            dest='hardware_config',
            help='[path to / prefix of] config specifying available valve pins and'
            'other important pins for a particular physical olfactometer. config '
            f'must be under {HARDWARE_DIR_ENVVAR} to refer by prefix. see also '
            f'{DEFAULT_HARDWARE_ENVVAR}.'
        )

    return parser


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


def argparse_run_args(parser=None, *, wait_option=True, **kwargs):
    """Returns argparse.ArgumentParser with args shared by [main/valve_test]_cli

    If parser is passed in, arguments will be added to that parser. Otherwise,
    a new parser is made first.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    argparse_config_args(parser, **kwargs)

    argparse_arduino_id_args(parser)

    parser.add_argument('-u', '--upload', action='store_true', dest='do_upload',
        help='also uploads Arduino code before running'
    )

    if wait_option:
        parser.add_argument('-y', '--no-wait', action='store_false',
            dest='pause_before_start',
            help='do not wait for user to press <Enter> before starting'
        )

    parser.add_argument('-v', '--verbose', action='store_true')

    if _DEBUG:
        # TODO TODO uncomment if i restore upload.version_str to a working state
        '''
        parser.add_argument('-a', '--allow-version-mismatch', action='store_true',
            default=False, help='unless passed, git hash of arduino code will be '
            'checked against git hash of python code, and it will not let you '
            'proceed unless they match. re-upload arduino code with clean '
            '"git status" to fix mismatch without this flag.'
        )
        '''

    return parser


def add_argparse_repeat_arg(parser, default_n_repeats=3, argparse_defaults=True):
    """
    If argparse_defaults is False, do not use argparse defaults, so that None can be
    processed conditionally. Shows default_n_repeats in help messages regardless.
    """
    parser.add_argument('-n', '--n-repeats', type=int, help='how many times to pulse '
        f'each valve (default: {default_n_repeats})',
        default=default_n_repeats if argparse_defaults else None
    )
    return parser


def add_argparse_timing_args(parser, default_on_s, default_off_s,
    argparse_defaults=True):
    """
    If argparse_defaults is False, do not use argparse defaults, so that None can be
    processed conditionally. Shows default_[on|off]_s in help messages regardless.
    """
    parser.add_argument('-s', '--on-secs', type=float, help='how many seconds to '
        f'actuate each valve for (default: {default_on_s:.1f})',
        default=default_on_s if argparse_defaults else None
    )
    parser.add_argument('-o', '--off-secs', type=float, help='how many seconds between '
        f'valve actuations (default: {default_off_s:.1f})',
        default=default_off_s if argparse_defaults else None
    )
    return parser


def parse_args(parser) -> Dict[str, Any]:
    args = parser.parse_args()
    return vars(args)


def parse_config_args(parser, require_config_path=True):
    """Returns config_path, kwargs

    Assumes parser has config_path positional and --hardware arguments at least
    """
    kwargs = parse_args(parser)

    try:
        config_path = kwargs.pop('config_path')
    except KeyError:
        if require_config_path:
            raise
        else:
            config_path = None

    return config_path, kwargs

