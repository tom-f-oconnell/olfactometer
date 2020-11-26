"""
Utility functions shared by one or more config generators.
"""

# TODO maybe have `olfactometer` validate that all generator outputs have a
# `pins2odors` / `odors2pins` variable with the pins all used (and not
# balance_pin or one of the other reserved pins) in the pin sequence and all
# odors at least not null or something (maybe str?)
# (or just some stuff in here?)

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
    assert timing_key not in settings_dict
    settings_dict[timing_key] = {
        'pre_pulse_us': pre_pulse_us,
        'pulse_us': pulse_us,
        'post_pulse_us': post_pulse_us
    }
    return generated_config_dict


def parse_common_settings(data, generated_config_dict=None):
    """
    Takes config dict, and adds populated values for the 'timing',
    'timing_output_pin', and 'recording_indicator_pin' to generated_config_dict.

    Returns the modified / created generated_config_dict. Creates if not passed.
    """
    if generated_config_dict is None:
        generated_config_dict = dict()

    parse_pulse_timing_s_to_us(data, generated_config_dict)

    settings_dict = generated_config_dict[settings_key]

    # TODO maybe require these are in config (explicitly set to 0 to disable if
    # you don't want to use them?) maybe 0 isn't that clear in this higher level
    # config though... (balance_pin as well perhaps)

    # The firmware should treat 0 as disabling a pin set as such.
    top = 'timing_output_pin'
    settings_dict[top] = data[top] if top in data else 0
    rec = 'recording_indicator_pin'
    settings_dict[rec] = data[rec] if rec in data else 0

    # TODO maybe also handle balance_pin here, though might make it more messy
    # since the determination of whether to use the single / double manifold
    # code might not fit here, and balance_pin parsing might fit better there.
    # might still be better to not duplicate the disabling logic... can always
    # just validate this key is only present in single manifold case in the
    # function that really disambiguates those cases (and perhaps subsequent
    # stuff that handles random pin assignment)

    return generated_config_dict


def add_pinlist(pinlist_at_each_trial, generated_config_dict) -> None:
    """Adds 'pin_sequence' key to dict, appropriately populated.

    pinlist_at_each_trial should be a list of lists, with each terminal element
    being an int corresponding to a valid pin
    """
    # TODO validation of first argument w/ appropriate error messages
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
    Returns a list of available pins,  a dict mapping them to their
    corresponding balances (if any), and a bool indicating whether there is just
    one manifold.

    May raise either AssertionError or ValueError if something about input is
    invalid.

    If `generated_config_dict` is passed, the 'settings'->'balance_pin' key will
    be filled in appropriately.
    """
    single_manifold_specific_keys = ['balance_pin', 'available_valve_pins']
    two_manifold_specific_keys = ['group1_balance_pin', 'group2_balance_pin',
        'available_group1_valve_pins', 'available_group2_valve_pins'
    ]
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
        assert type(available_valve_pins) is list

        # TODO should i support this being undefined in single manifold case?
        # (maybe all 2 way valves, for instance...)
        balance_pin = data['balance_pin']

        pins2balances = {p: balance_pin for p in available_valve_pins}

        single_manifold = True
    else:
        assert all(have_two_manifold_keys)

        available_group1_valve_pins = data['available_group1_valve_pins']
        assert type(available_group1_valve_pins) is list
        available_group2_valve_pins = data['available_group2_valve_pins']
        assert type(available_group2_valve_pins) is list

        group1_balance_pin = data['group1_balance_pin']
        group2_balance_pin = data['group2_balance_pin']

        available_valve_pins = \
            available_group1_valve_pins + available_group2_valve_pins

        pins2balances = dict()
        for p in available_group1_valve_pins:
            pins2balances[p] = group1_balance_pin
        for p in available_group2_valve_pins:
            pins2balances[p] = group2_balance_pin
 
        single_manifold = False

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
    assert len(balance_pin_set) + len(odor_pin_set) == len(all_pin_set)

    return available_valve_pins, pins2balances, single_manifold

