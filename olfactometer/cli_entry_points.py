#!/usr/bin/env python3

import argparse

from olfactometer.util import (argparse_run_args, argparse_arduino_id_args,
    load_hardware_config, main
)
from olfactometer.generators import common
from olfactometer.upload import main as upload_main
from olfactometer.upload import version_str as _version_str


def main_cli():
    parser = argparse_run_args()

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
    parser.add_argument('config_path', type=str, nargs='?', default=None,
        help='.json/.yaml file containing all required data. see `load` '
        'function. reads config from stdin if not passed.'
    )
    # TODO TODO add an arg to shorten all valve OFF periods to a fixed value /
    # value scaled from original / value derived by subtracting from original
    # (something like --shorten-offs-by/--override-off-secs), for testing
    # stimulus programs quickly. warn that it should only be used for testing.
    args = parser.parse_args()

    # TODO maybe add arg to specify generated YAML w/ pins2odors to use?
    # (for subsequent generation of a subset of odors, for testing?)
    # or maybe just make some easier way of quickly doing an experiment (how to
    # specify timing information?) w/ one odor

    do_upload = args.upload
    port = args.port
    fqbn = args.fqbn
    # TODO uncomment if i resolve version_str issue
    #allow_version_mismatch = args.allow_version_mismatch
    try_parse = args.try_parse
    ignore_ack = args.ignore_ack
    hardware_config = args.hardware
    pause_before_start = not args.no_wait
    verbose = args.verbose
    config_path = args.config_path

    main(config_path, port=port, fqbn=fqbn, do_upload=do_upload,
        # TODO add back if i resolve version_str issue
        #allow_version_mismatch=allow_version_mismatch,
        ignore_ack=ignore_ack, try_parse=try_parse,
        hardware_config=hardware_config, pause_before_start=pause_before_start,
        verbose=verbose
    )
    

def valve_test_cli():
    parser = argparse_run_args()

    default_n_repeats = 3
    bal_default_n_repeats = 1
    parser.add_argument('-n', '--n-repeats', type=int, default=None,
        help='how many times to pulse each valve (default: '
        f'{default_n_repeats})'
    )
    default_on_s = 0.5
    default_off_s = 0.5
    bal_default_on_s = 2.0
    bal_default_off_s = 0.5
    parser.add_argument('-s', '--on-secs', type=float, default=None,
        help='how many seconds to actuate each valve for (default: '
        f'{default_on_s:.1f})'
    )
    # TODO check that my code works if pre_pulse_us is 0, or whether i need to
    # set it to some small value, and enforce that this is > that small value
    # (or if post_pulse_us works as 0 but pre_pulse_us doesn't, swap the usage
    # of the two here)
    # TODO or just set one of [pre/post]... to a very small value
    parser.add_argument('-o', '--off-secs', type=float, default=None,
        help='how many seconds between valve actuations (default: '
        f'{default_off_s:.1f})'
    )
    parser.add_argument('-b', '--balance', action='store_true',
        help='use balance valves as during odor presentation. otherwise, '
        'they are pulsed just like any other valve, for listening for '
        'valve clicks. use this option to test flow (e.g. with outputs bubbling'
        ' through water). default on/off times are '
        f'{bal_default_on_s:.1f}/{bal_default_off_s} in this case. default '
        f'n_repeats becomes {default_n_repeats}.'
    )
    '''
    parser.add_argument('-i', '--pins', type=str, default=None,
        help='if passed, will use this subset of pins from available_valve_pins'
        ' in the hardware definition'
    )
    '''
    args = parser.parse_args()

    do_upload = args.upload
    port = args.port
    fqbn = args.fqbn
    # TODO uncomment if i resolve version_str issue
    #allow_version_mismatch = args.allow_version_mismatch
    hardware_config = args.hardware
    pause_before_start = not args.no_wait
    verbose = args.verbose

    n_repeats = args.n_repeats
    on_secs = args.on_secs
    off_secs = args.off_secs
    # Balance pins are currently part of required (enforced by
    # `get_available_pins`) hardware definition, so we don't need to worry about
    # checking they are defined, in the case where this is true.
    use_balances = args.balance

    if n_repeats is None:
        if not use_balances:
            n_repeats = default_n_repeats
        else:
            n_repeats = bal_default_n_repeats

    # TODO see note by off-secs definition above
    pre_pulse_s = 0.0

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

    config_data = load_hardware_config(hardware_config, required=True)
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

    if not use_balances:
        trial_pins = available_valve_pins + list(set(pins2balances.values()))
    else:
        # Not going to have test trials dedicated to balance pins in the
        # use_balances case.
        trial_pins = available_valve_pins

    # Easier to monitor test if pins are used in order.
    trial_pins = sorted(trial_pins)

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

    main(generated_config_dict, port=port, fqbn=fqbn, do_upload=do_upload,
        hardware_config=None, pause_before_start=pause_before_start,
        verbose=verbose, _skip_config_preprocess_check=True
        # TODO add back if i resolve version_str issue
        #, allow_version_mismatch=allow_version_mismatch
    )


def upload_cli():
    parser = argparse.ArgumentParser()

    argparse_arduino_id_args(parser)

    parser.add_argument('-d', '--dry-run', action='store_true', default=False,
        help='do not actually upload. just compile.'
    )
    parser.add_argument('-s', '--show-properties', action='store_true',
        default=False, help='shows arduino-cli compilation "build properties" '
        'and exits (without compiling or uploading)'
    )
    parser.add_argument('-b', '--build-root', action='store', default=None,
        help='directory to create Arduino sketch and libraries under, '
        'for inspection during troubleshooting. default is a temporary '
        'directory.'
    )
    parser.add_argument('-g', '--arduino-debug-prints', action='store_true',
        default=False, help='compile Arduino code with DEBUG_PRINTS defined. '
        'Arduino will print more stuff over USB and its code size will increase'
        ' slightly.'
    )
    parser.add_argument('-n', '--no-symlink', action='store_true',
        default=False, help='copy files instead of symlinking them, when '
        'preparing Arduino sketch and libraries for compilation. ignored on '
        'Windows, where files are always copied rather than symlinked.'
    )
    parser.add_argument('-v', '--verbose', action='store_true', default=False,
        help='make arduino-cli compilation verbose'
    )
    args = parser.parse_args()

    upload_main(
        port=args.port,
        fqbn=args.fqbn,
        dry_run=args.dry_run,
        show_properties=args.show_properties,
        arduino_debug_prints=args.arduino_debug_prints,
        build_root=args.build_root,
        verbose=args.verbose
    )


def version_str():
    print(_version_str())

