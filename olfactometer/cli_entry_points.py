#!/usr/bin/env python3

"""
Every function in this file should be a CLI entrypoint (referenced in setup.py)
"""

import argparse

import pyperclip

from olfactometer import util
from olfactometer.util import main, _DEBUG
from olfactometer.generators import common
from olfactometer.upload import main as upload_main
from olfactometer.upload import version_str as _version_str


def main_cli(config_path=None):
    """
    Args:
        config_path: None or path to config file to run
    """
    parser = util.argparse_run_args(config_path=True if config_path is None else False)

    parser.add_argument('-c', '--check-set-flows', action='store_true',
        default=False, help='query flow controllers after each change in '
        'setpoints to see the change seems to have been applied. only for '
        'debugging experiments involving flow controllers. does NOT check '
        'ACHIEVED flow rates.'
    )

    if _DEBUG:
        parser.add_argument('-t', '--try-parse', action='store_true', default=False,
            help='exit after attempting to parse config. no need for a connected '
            'Arduino.'
        )
        parser.add_argument('-k', '--ignore-ack', action='store_true',
            default=False, help='ignores acknowledgement message #s arduino sends. '
            'makes viewing all debug prints FROM THE FIRMWARE easier, as it '
            'prevents the prints from interfering with receipt of the message '
            'numbers.'
        )
        parser.add_argument('-s', '--speed-factor', type=float,
            help='speeds up stimulus program by this factor to test faster'
        )

    # TODO maybe add arg to specify generated YAML w/ pins2odors to use?
    # (for subsequent generation of a subset of odors, for testing?)
    # or maybe just make some easier way of quickly doing an experiment (how to
    # specify timing information?) w/ one odor

    cli_config_path, kwargs = util.parse_config_args(parser,
        require_config_path=True if config_path is None else False
    )

    if config_path is None:
        config_path = cli_config_path

    main(config_path, **kwargs)


def get_last_attempted_cli(copy=True):
    config_path, abs_config_path = util.get_last_attempted()

    print(f'Last attempted config: {config_path}', end='')
    if copy:
        pyperclip.copy(config_path)
        print(' (copied to clipboard)')
    else:
        print()

    print(f'Absolute path: {abs_config_path}')

    return config_path, abs_config_path


def retry_last_attempted_cli():
    config_path, abs_config_path = get_last_attempted_cli(copy=False)
    print()
    # i was originally wanted to use abs path here, to be able to run from anywhere, but
    # it makes what gets copied to clipboard / printed inconsistent w/ what we'd have on
    # first run
    main_cli(config_path=config_path)


def valve_test_cli():
    parser = util.argparse_run_args(config_path=False)

    default_n_repeats = 3
    bal_default_n_repeats = 1
    util.add_argparse_repeat_arg(parser, default_n_repeats, argparse_defaults=False)

    default_on_s = 0.5
    default_off_s = 0.5
    bal_default_on_s = 2.0
    bal_default_off_s = 0.5
    util.add_argparse_timing_args(parser, default_on_s, default_off_s,
        # So that we can select have different defaults if -b is passed.
        argparse_defaults=False
    )

    # TODO check that my code works if pre_pulse_us is 0, or whether i need to
    # set it to some small value, and enforce that this is > that small value
    # (or if post_pulse_us works as 0 but pre_pulse_us doesn't, swap the usage
    # of the two here)
    # TODO or just set one of [pre/post]... to a very small value

    # Balance pins are currently part of required (enforced by
    # `get_available_pins`) hardware definition, so we don't need to worry about
    # checking they are defined, in the case where this is true.
    parser.add_argument('-b', '--balance', action='store_true', dest='use_balances',
        help='use balance valves as during odor presentation. otherwise, '
        'they are pulsed just like any other valve, for listening for '
        'valve clicks. use this option to test flow (e.g. with outputs bubbling'
        ' through water). default on/off times are '
        f'{bal_default_on_s:.1f}/{bal_default_off_s} in this case. default '
        f'n_repeats becomes {default_n_repeats}.'
    )

    # TODO maybe it should support -b somehow? right now it can't really, cause
    # not using hardware def at all here
    parser.add_argument('-i', '--pins', type=str, dest='cli_pins', help='if passed, '
        'will use these pins (comma separated) rather than hardware definition. tested '
        'in order passed.'
    )

    kwargs = util.parse_args(parser)

    hardware_config = kwargs.pop('hardware_config')
    on_secs = kwargs.pop('on_secs')
    off_secs = kwargs.pop('off_secs')
    n_repeats = kwargs.pop('n_repeats')
    use_balances = kwargs.pop('use_balances')
    cli_pins = kwargs.pop('cli_pins')

    if cli_pins is not None:
        if use_balances:
            raise NotImplementedError('--pins and --balance can not currently '
                'be used together'
            )

        cli_pins = [int(p) for p in cli_pins.split(',')]

    if n_repeats is None:
        if not use_balances:
            n_repeats = default_n_repeats
        else:
            n_repeats = bal_default_n_repeats

    if on_secs is None:
        if not use_balances:
            pulse_s = default_on_s
        else:
            pulse_s = bal_default_on_s
    else:
        pulse_s = on_secs

    if off_secs is None:
        if not use_balances:
            post_pulse_s = default_off_s
        else:
            post_pulse_s = bal_default_off_s
    else:
        post_pulse_s = off_secs

    config_data = util.load_hardware_config(hardware_config, required=True)
    common.validate_hardware_dict(config_data)

    # This is currently what *would* set 'balance_pin', if optional
    # `generated_config_dict` arg were passed, so we don't need to worry about
    # stripping it from the output of `common.parse_common_settings`.
    available_valve_pins, pins2balances, single_manifold = \
        common.get_available_pins(config_data)

    timing_dict = {
        'pre_pulse_s': 0.0,
        'pulse_s': pulse_s,
        'post_pulse_s': post_pulse_s,
    }
    config_data.update(timing_dict)

    generated_config_dict = common.parse_common_settings(config_data)

    if cli_pins is None:
        if not use_balances:
            trial_pins = (
                available_valve_pins + list(set(pins2balances.values()))
            )
        else:
            # Not going to have test trials dedicated to balance pins in the
            # use_balances case.
            trial_pins = available_valve_pins

        # Easier to monitor test if pins are used in order.
        trial_pins = sorted(trial_pins)

    else:
        trial_pins = cli_pins

    pinlist_at_each_trial = [[p] for p in trial_pins for _ in range(n_repeats)]
    del trial_pins

    if use_balances:
        # This does nothing in single_manifold case.
        pinlist_at_each_trial = common.add_balance_pins(
            pinlist_at_each_trial, pins2balances
        )
        if single_manifold:
            # Normally `common.get_available_pins` would set this, but doing
            # this (same as what it does) rather than calling it twice.
            balance_pin = list(set(pins2balances.values()))[0]
            settings_dict = generated_config_dict[common.settings_key]
            settings_dict['balance_pin'] = balance_pin
            del balance_pin, settings_dict

    common.add_pinlist(pinlist_at_each_trial, generated_config_dict)

    main(generated_config_dict, _skip_config_preprocess_check=True, **kwargs)


def one_valve_cli():
    parser = util.argparse_run_args(config_path=False)

    # TODO check that it's among odor pins in hardware definition (i.e. also check it's
    # not a balance)
    parser.add_argument('pin', type=int, help='pin controlling the valve connected to '
        'our test odor'
    )

    default_n_repeats = 2
    util.add_argparse_repeat_arg(parser, default_n_repeats)

    default_on_s = 1.0
    default_off_s = 10.0
    util.add_argparse_timing_args(parser, default_on_s, default_off_s)

    default_pre_s = 0.0
    parser.add_argument('-e', '--pre-secs', type=float, help='seconds to wait from '
        f'recording start to first valve onset (default: {default_pre_s:.1f})',
        default=default_pre_s
    )

    kwargs = util.parse_args(parser)

    hardware_config = kwargs.pop('hardware_config')

    pin = kwargs.pop('pin')
    assert pin is not None

    pre_pulse_s = kwargs.pop('pre_secs')
    pulse_s = kwargs.pop('on_secs')
    post_pulse_s = kwargs.pop('off_secs')
    n_repeats = kwargs.pop('n_repeats')

    config_data = util.load_hardware_config(hardware_config, required=True)
    common.validate_hardware_dict(config_data)

    # This is currently what *would* set 'balance_pin', if optional
    # `generated_config_dict` arg were passed, so we don't need to worry about
    # stripping it from the output of `common.parse_common_settings`.
    available_valve_pins, pins2balances, single_manifold = \
        common.get_available_pins(config_data)

    timing_dict = {
        'pre_pulse_s': pre_pulse_s,
        'pulse_s': pulse_s,
        'post_pulse_s': post_pulse_s,
    }
    config_data.update(timing_dict)

    generated_config_dict = common.parse_common_settings(config_data)

    if pin not in available_valve_pins:
        raise ValueError(f'pin {pin} not among odor pins {available_valve_pins} in '
            'current hardware definition'
        )

    pinlist_at_each_trial = [[pin] for _ in range(n_repeats)]

    # This does nothing in single_manifold case.
    pinlist_at_each_trial = common.add_balance_pins(
        pinlist_at_each_trial, pins2balances
    )
    if single_manifold:
        # Normally `common.get_available_pins` would set this, but doing
        # this (same as what it does) rather than calling it twice.
        balance_pin = list(set(pins2balances.values()))[0]
        settings_dict = generated_config_dict[common.settings_key]
        settings_dict['balance_pin'] = balance_pin
        del balance_pin, settings_dict

    common.add_pinlist(pinlist_at_each_trial, generated_config_dict)

    main(generated_config_dict, _skip_config_preprocess_check=True, **kwargs)


# TODO try to refactor this + valve_test_cli + one_valve_cli to share a bit more code
def flush_cli():
    parser = util.argparse_run_args(config_path=False, wait_option=False)

    default_n_repeats = 3
    util.add_argparse_repeat_arg(parser, default_n_repeats)

    default_on_s = 10.0
    default_off_s = 0.2
    util.add_argparse_timing_args(parser, default_on_s, default_off_s)

    kwargs = util.parse_args(parser)

    hardware_config = kwargs.pop('hardware_config')
    pulse_s = kwargs.pop('on_secs')
    post_pulse_s = kwargs.pop('off_secs')
    n_repeats = kwargs.pop('n_repeats')

    config_data = util.load_hardware_config(hardware_config, required=True)
    common.validate_hardware_dict(config_data)

    # This is currently what *would* set 'balance_pin', if optional
    # `generated_config_dict` arg were passed, so we don't need to worry about
    # stripping it from the output of `common.parse_common_settings`.
    available_valve_pins, pins2balances, single_manifold = \
        common.get_available_pins(config_data)

    timing_dict = {
        'pre_pulse_s': 0.0,
        'pulse_s': pulse_s,
        'post_pulse_s': post_pulse_s,
    }
    config_data.update(timing_dict)

    generated_config_dict = common.parse_common_settings(config_data)

    trial_pins = sorted(available_valve_pins)

    pinlist_at_each_trial = [[p] for p in trial_pins for _ in range(n_repeats)]
    del trial_pins

    # This does nothing in single_manifold case.
    pinlist_at_each_trial = common.add_balance_pins(
        pinlist_at_each_trial, pins2balances
    )
    if single_manifold:
        # Normally `common.get_available_pins` would set this, but doing
        # this (same as what it does) rather than calling it twice.
        balance_pin = list(set(pins2balances.values()))[0]
        settings_dict = generated_config_dict[common.settings_key]
        settings_dict['balance_pin'] = balance_pin
        del balance_pin, settings_dict

    common.add_pinlist(pinlist_at_each_trial, generated_config_dict)

    main(generated_config_dict, _skip_config_preprocess_check=True, **kwargs)


def upload_cli():
    parser = argparse.ArgumentParser()

    util.argparse_arduino_id_args(parser)

    parser.add_argument('-d', '--dry-run', action='store_true',
        help='do not actually upload. just compile.'
    )
    parser.add_argument('-s', '--show-properties', action='store_true',
        default=False, help='shows arduino-cli compilation "build properties" '
        'and exits (without compiling or uploading)'
    )
    parser.add_argument('-b', '--build-root', action='store', help='directory to create'
        ' Arduino sketch and libraries under, for inspection during troubleshooting. '
        'default is a temporary directory.'
    )
    parser.add_argument('-g', '--arduino-debug-prints', action='store_true',
        default=False, help='compile Arduino code with DEBUG_PRINTS defined. '
        'Arduino will print more stuff over USB and its code size will increase'
        ' slightly.'
    )
    parser.add_argument('-n', '--no-symlink', action='store_true',
        help='copy files instead of symlinking them, when preparing Arduino sketch and'
        'libraries for compilation. ignored on Windows, where files are always copied'
        ' rather than symlinked.'
    )
    parser.add_argument('-v', '--verbose', action='store_true',
        help='make arduino-cli compilation verbose'
    )
    kwargs = util.parse_args(parser)

    upload_main(**kwargs)


def print_config_time_cli():
    parser = util.argparse_config_args()
    parser.add_argument('-v', '--verbose', action='store_true')

    config_path, kwargs = util.parse_config_args(parser)

    n_config = 0
    total_s = 0

    for single_run_config in util.config_iter(config_path, **kwargs):

        all_required_data, config_dict = util.load(single_run_config)

        time_s = util.time_config_will_take_s(all_required_data, print_=True)
        total_s += time_s

        n_config += 1

    if n_config > 1:
        print(f'\nTotal: {util.format_duration_s(total_s)}')


def show_pins2odors_cli():
    parser = util.argparse_config_args(hardware=False)

    parser.add_argument('-v', '--verbose', action='store_true')

    config_path, kwargs = util.parse_config_args(parser)

    for single_run_config in util.config_iter(config_path,
        _skip_config_preprocess_check=True, **kwargs):

        _, config_dict = util.load(single_run_config)

        if 'generator' in config_dict:
            raise ValueError('Do not use this (directly) with config that use '
                'generators. Instead, pass generator output or manually created config.'
            )

        util.print_pins2odors(config_dict)


def version_str():
    print(_version_str())

