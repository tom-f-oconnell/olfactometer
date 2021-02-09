"""
Utility functions shared by one or more config generators.
"""

from olfactometer import util

# TODO maybe have `olfactometer` validate that all generator outputs have a
# `pins2odors` / `odors2pins` variable with the pins all used (and not
# balance_pin or one of the other reserved pins) in the pin sequence and all
# odors at least not null or something (maybe str?)
# (or just some stuff in here?)

def validate_pinlist(pinlist):
    assert type(pinlist) is list
    for p in pinlist:
        util.validate_pin(p)


def validate_pinlist_list(pinlist_at_each_trial):
    assert type(pinlist_at_each_trial) is list
    for pinlist in pinlist_at_each_trial:
        validate_pinlist(pinlist)


# TODO odor[list] validate fn? maybe in util?
# TODO fn to validate hardware config? (including that there are no unexpected
# variables, at least optionally) (maybe again in util though)


settings_key = 'settings'
# TODO maybe modify this fn to modify a passed config_dict to add the relevant
# keys directly
def parse_pulse_timing_s_to_us(data, generated_config_dict=None):
    """Takes config dict, adds pre_pulse_us, pulse_us, post_pulse_us to 2nd arg.

    Returns the modified / created generated_config_dict. Creates if not passed.

    Expects 'pre_pulse_s', 'pulse_s', and 'post_pulse_s' as keys in the config
    dict, with numeric values.

    Type of the values for the added keys will be int.
    """
    if generated_config_dict is None:
        generated_config_dict = dict()

    # Leaving the validation (bounds checking) to the `olfactometer` script
    pre_pulse_s = float(data['pre_pulse_s'])
    pulse_s = float(data['pulse_s'])
    post_pulse_s = float(data['post_pulse_s'])
    # TODO TODO TODO if my software has max(/ >=0 min) limits for any of the
    # above (alone or in combination), validate the bounds here
    # (maybe factor into some function that can be used externally without other
    # operations here?)

    us_per_s = 1e6
    pre_pulse_us = int(round(pre_pulse_s * us_per_s))
    pulse_us = int(round(pulse_s * us_per_s))
    post_pulse_us = int(round(post_pulse_s * us_per_s))

    if settings_key not in generated_config_dict:
        generated_config_dict[settings_key] = dict()

    settings_dict = generated_config_dict[settings_key]
    timing_key = 'timing'
    # only this function should be adding the timing information, and if it's
    # already there, it wouldn't make sense to call this function anyway
    assert timing_key not in settings_dict, (f'{timing_key} already in data['
        f'{settings_key}], when this call was supposed to add it'
    )
    settings_dict[timing_key] = {
        'pre_pulse_us': pre_pulse_us,
        'pulse_us': pulse_us,
        'post_pulse_us': post_pulse_us
    }
    return generated_config_dict


single_manifold_specific_keys = ['balance_pin', 'available_valve_pins']
two_manifold_specific_keys = ['group1_balance_pin', 'group2_balance_pin',
    'available_group1_valve_pins', 'available_group2_valve_pins'
]
_top = 'timing_output_pin'
_rec = 'recording_indicator_pin'

# These keys should all be top-level in config that is intended to be
# preprocessed.
hardware_specific_keys = (
    single_manifold_specific_keys + two_manifold_specific_keys + [_top, _rec]
)

def validate_nonvalve_pins(data, nonvalve_pin_keys=(_top, _rec)):
    """
    Raises `AssertionError` if any of `nonvalve_pin_keys` are present in `data`
    and fail `util.validate_pin` check.

    Returns set of all non-valve pin numbers discovered in this process, for
    further checking (e.g. that they don't overlap with valve pin numbers).
    """
    nonvalve_pins = set()
    for k in nonvalve_pin_keys:
        if k in data:
            p = data[k]
            util.validate_pin(p)
            nonvalve_pins.add(p)

    return nonvalve_pins


def parse_common_settings(data, generated_config_dict=None):
    """
    Takes config dict, and adds populated values for the 'timing',
    'timing_output_pin', and 'recording_indicator_pin' to generated_config_dict.

    Returns the modified / created generated_config_dict. Creates if not passed.
    """
    validate_nonvalve_pins(data)

    if generated_config_dict is None:
        generated_config_dict = dict()

    parse_pulse_timing_s_to_us(data, generated_config_dict)

    settings_dict = generated_config_dict[settings_key]

    # TODO maybe require these are in config (explicitly set to 0 to disable if
    # you don't want to use them?) maybe 0 isn't that clear in this higher level
    # config though... (balance_pin as well perhaps)

    # The firmware should treat 0 as disabling a pin set as such.
    settings_dict[_top] = data[_top] if _top in data else 0
    settings_dict[_rec] = data[_rec] if _rec in data else 0

    # TODO maybe also handle balance_pin here, though might make it more messy
    # since the determination of whether to use the single / double manifold
    # code might not fit here, and balance_pin parsing might fit better there.
    # might still be better to not duplicate the disabling logic... can always
    # just validate this key is only present in single manifold case in the
    # function that really disambiguates those cases (and perhaps subsequent
    # stuff that handles random pin assignment)
    # (need to update at least util.valve_test_cli if i make this change)

    return generated_config_dict


def add_balance_pins(pinlist_at_each_trial, pins2balances):
    """Returns pinlist like input, but with balance pins added to each list.

    In single manifold case, the 'balance_pin' which should already be part of
    generated config will handle the balances, as the firmware is aware of how
    to handle balances in this case.
    """
    validate_pinlist_list(pinlist_at_each_trial)

    balance_pin_set = set(pins2balances.values())
    for pinlist in pinlist_at_each_trial:
        for p in pinlist:
            assert p not in balance_pin_set, \
                f'pin list already contained balance pin {p}'

    single_manifold = (len(balance_pin_set) == 1)
    # TODO TODO TODO i think now, it's actually expecting input to be a list of
    # pins, not a list of pinlists. fix!!! (or maybe make tolerant of either,
    # for convenience?)
    if single_manifold:
        # Here the balance is handled by the 'balance_pin' setting, so it
        # doesn't need to explicitly be included in each pin list. The firmware
        # doesn't have a notion of multiple manifolds / balance though, so we
        # need to handle the balances exlicitly in that case.
        return pinlist_at_each_trial
    else:
        # Since the global balance is disabled in the !single_manifold case, we
        # need to explicitly tell the correct balance pin to trigger alongside
        # each odor pin.
        pinlist_at_each_trial = [plist + [pins2balances[p] for p in plist]
            for plist in pinlist_at_each_trial
        ]

    return pinlist_at_each_trial


def add_pinlist(pinlist_at_each_trial, generated_config_dict) -> None:
    """Adds 'pin_sequence' key to dict, appropriately populated.

    pinlist_at_each_trial should be a list of lists, with each terminal element
    being an int corresponding to a valid pin
    """
    validate_pinlist_list(pinlist_at_each_trial)
    generated_config_dict['pin_sequence'] = {
        'pin_groups': [{'pins': pins} for pins in pinlist_at_each_trial]
    }


# TODO maybe generalize how valve groups are implemented to just putting
# available_valve_pins / balance_pin under a YAML / JSON iterable, with perhaps
# an optional `name` key to give something to print when telling the user what
# to connect to what (include in functions shared by all generators though,
# probably)
def get_available_pins(data, generated_config_dict=None):
    """
    Returns a list of available pins, a dict mapping them to their
    corresponding balances (if any), and a bool indicating whether there is just
    one manifold.

    Excepts `data` to contain all of either `single_manifold_specific_keys` OR
    `two_manifold_specific_keys`.

    May raise either `AssertionError` or `ValueError` if something about input
    is invalid.

    If `generated_config_dict` is passed, the 'settings'->'balance_pin' key will
    be filled in appropriately.
    """
    have_single_manifold_keys = [
        k in data for k in single_manifold_specific_keys
    ]
    have_two_manifold_keys = [
        k in data for k in two_manifold_specific_keys
    ]
    # TODO maybe just delete this code manually setting it to the default...
    # could probably just let the default do its job...
    # TODO check that it's actually disabled in this case
    balance_pin = 0
    if any(have_single_manifold_keys):
        assert all(have_single_manifold_keys)
        assert not any(have_two_manifold_keys)

        available_valve_pins = data['available_valve_pins']
        validate_pinlist(available_valve_pins)

        # TODO should i support this being undefined in single manifold case?
        # (maybe all 2 way valves, for instance...)
        balance_pin = data['balance_pin']
        util.validate_pin(balance_pin)

        pins2balances = {p: balance_pin for p in available_valve_pins}

        single_manifold = True
    else:
        assert all(have_two_manifold_keys)

        available_group1_valve_pins = data['available_group1_valve_pins']
        available_group2_valve_pins = data['available_group2_valve_pins']
        validate_pinlist(available_group1_valve_pins)
        validate_pinlist(available_group2_valve_pins)

        group1_balance_pin = data['group1_balance_pin']
        group2_balance_pin = data['group2_balance_pin']
        util.validate_pin(group1_balance_pin)
        util.validate_pin(group2_balance_pin)

        available_valve_pins = \
            available_group1_valve_pins + available_group2_valve_pins

        pins2balances = dict()
        for p in available_group1_valve_pins:
            pins2balances[p] = group1_balance_pin
        for p in available_group2_valve_pins:
            pins2balances[p] = group2_balance_pin
 
        single_manifold = False

    # May remove later. Just to check that other functions using pins2balances
    # (which they may want to derive something like single_manifold from)
    # wouldn't be inconsistent w/ stuff that uses single_manifold passed from
    # here.
    assert single_manifold == (len(set(pins2balances.values())) == 1)

    if generated_config_dict is not None:
        if settings_key not in generated_config_dict:
            generated_config_dict[settings_key] = dict()

        settings_dict = generated_config_dict[settings_key]
        settings_dict['balance_pin'] = balance_pin

    # Leaving the remaining validation that pin numbers are valid to the
    # functions in olfactometer/util.py
    odor_pin_set = set(available_valve_pins)
    balance_pin_set = set(pins2balances.values())
    all_pin_set = odor_pin_set | balance_pin_set
    assert len(balance_pin_set) + len(odor_pin_set) == len(all_pin_set), \
        'overlap between balance and odor pins'

    return available_valve_pins, pins2balances, single_manifold


# TODO maybe add kwarg for specific keys to ignore, and then use this (passing
# timing keys, 'generator', etc) in util, to validate generator inputs?
# TODO or maybe refactor so that, in combination, all the util functions that
# preprocess these variables do the appropriate validation? i feel like there
# might not (currently) exist one such function that has access to all of the
# necessary data at once though, which might be necessary for e.g. the non-valve
# / valve overlap check
def validate_hardware_dict(hardware_dict, allow_unknown_keys=False):
    """Raises [Assertion/Value]Error if dict from hardware YAML is invalid.

    If `allow_unknown_keys` is `True` (`False` by default), no error will be
    raised if the only problem is that `hardware_dict` has unrecognized keys.
    """
    available_valve_pins, pins2balances, _ = get_available_pins(hardware_dict)
    valve_pin_set = set(available_valve_pins) | set(pins2balances.values())

    nonvalve_pins = validate_nonvalve_pins(hardware_dict)
    nonvalve_pin_set = set(nonvalve_pins)

    all_pin_set = valve_pin_set | nonvalve_pin_set
    assert len(valve_pin_set) + len(nonvalve_pin_set) == len(all_pin_set), (
        'overlap between valve pins (including those for balances) and non-'
        'valve pins'
    )

    if not allow_unknown_keys:
        unknown_keys = set(hardware_dict.keys()) - set(hardware_specific_keys)
        if len(unknown_keys) > 0:
            raise ValueError(
                f'hardware config had unknown keys: {unknown_keys}'
            )

