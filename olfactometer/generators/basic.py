"""
Takes YAML input describing a panels of odors and returns config to present
them, either in the order in the YAML or randomly. Odors are assigned to random
valves from the set of available valves (identified by the pin number driving
them).

No mixtures (across odor vials) supported in this config generation function.

Only planning on supporting the case where the number of odors in the panel can
fit into the number of valves available in the particular hardware.

Example input (the part between the ```'s, saved to a YAML file, whose filename
is passed as input to `make_config_dict` below):
```
# Since I have not yet implemented some orthogonal way of specifying the setup,
# and the corresponding wiring / available pins / etc on each.
available_valve_pins: [2, 3, 4]

balance_pin: 5

# If this is False, the odors will be presented in the order in the list below.
randomize_presentation_order: False

odors:
 - name: 2,3-butanedione
   log10_conc: -6
 - name: methyl salicylate
   log10_conc: -3

# Reformatted into settings.timing.*_us by [this] generator
pre_pulse_s: 2
pulse_s: 1
post_pulse_s: 11
```
"""
# TODO probably support a `pin` key for each odor (perhaps allowed+required iff
# an additional top-level `randomize_pins2odors: False` or something is present)
# TODO similarly, maybe allow not randomizing the balance pin, to be less
# annoying about swapping stuff out (or not randomizing beyond first expt in a
# series? probably don't want to go so far as to cache which pin(s) they are
# across runs of this though...)

import random
import warnings

from olfactometer.generators import common


def make_config_dict(generator_config_yaml_dict):
    # TODO doc the minimum expected keys of the YAML
    """
    Args:
    generator_config_yaml_dict (str): dict of parsed contents of YAML
      configuration file.

    Returns `dict` representation of YAML config for olfactometer. Also includes
    a `pins2odors` YAML dictionary which is not used by the olfactometer, but
    which is for tracking which odors certain pins corresponded to, at analysis
    time.

    Used keys in the YAML that gets parsed and input to this function (as a
    dict):
    - Used via `common.parse_common_settings`:
      - 'pre_pulse_s'
      - 'pulse_s'
      - 'post_pulse_s'
      - 'timing_output_pin' (optional)
        - Should be specified in separate hardware config.

      - 'recording_indicator_pin' (optional)
        - Should be specified in separate hardware config.

    - Used via `common.get_available_pins`:
      - Either:
        - All of the keys in `common.single_manifold_specific_keys`, OR...
        - All of the keys in `common.two_manifold_specific_keys`

        In both cases above, those parameters should be specified in separate
        hardware config.

    - Used directly in this function:
      - 'odors'
      - 'randomize_presentation_order' (optional, defaults to True)
      - 'n_repeats' (optional, defaults to 1)

    """
    data = generator_config_yaml_dict

    generated_config_dict = common.parse_common_settings(data)

    available_valve_pins, pins2balances, single_manifold = \
        common.get_available_pins(data, generated_config_dict)

    unique_odors, odors_in_order = common.get_odors(data)

    n_odors = len(unique_odors)
    assert len(available_valve_pins) >= n_odors
    # The means of generating the random odor vial <-> pin (valve) mapping.
    odor_pins = random.sample(available_valve_pins, n_odors)

    # The YAML dump downstream (which SHOULD include this data) should sort the
    # keys by default (just for display purposes, but still what I want).
    # TODO maybe still re-order (by making a new dict and adding in the order i
    # want), because sort_keys=True default also re-orders some other things i
    # don't want it to
    pins2odors = {p: o for p, o in zip(odor_pins, unique_odors)}

    randomize_presentation_order_key = 'randomize_presentation_order'
    if randomize_presentation_order_key in data:
        randomize_presentation_order = data[randomize_presentation_order_key]
        assert randomize_presentation_order in (True, False)
    else:
        if len(odors) > 1:
            warnings.warn(f'defaulting to {randomize_presentation_order_key}'
                '=True, since not specified in config'
            )
            randomize_presentation_order = True
        else:
            assert len(odors) == 1
            randomize_presentation_order = False

    n_repeats_key = 'n_repeats'
    if n_repeats_key in data:
        n_repeats = data[n_repeats_key]
        # TODO TODO maybe rename randomize_presentation_order and/or add another
        # possible value and/or add another flag for controlling whether
        # presentations of a particular odor should be kept together
        if randomize_presentation_order:
            warnings.warn('current implementation only randomizes across odors,'
                ' keeping presentations of any given odor together'
            )
    else:
        n_repeats = 1

    # TODO refactor? also, if i make an Odor class w/ a meaningful hash, could simplify
    # this (as well as similar code in common.get_odors)
    trial_pins_norepeats = []
    for o in odors_in_order:
        found_pin = False
        for p, pin_odor in pins2odors.items():
            if common.odors_equal(o, pin_odor):
                trial_pins_norepeats.append(p)
                found_pin = True
                break
        assert found_pin

    if randomize_presentation_order:
        # This re-orders odor_pins in-place (it modifies it, rather than
        # returning something modified).
        random.shuffle(trial_pins_norepeats)

    # TODO worth factoring this into a fn in common for expanding to # of
    # trials? could accept arbitrary lists?
    trial_pinlists = [[p] for p in trial_pins_norepeats for _ in range(n_repeats)]

    pinlist_at_each_trial = common.add_balance_pins(
        trial_pinlists, pins2balances
    )

    generated_config_dict['pins2odors'] = pins2odors
    common.add_pinlist(pinlist_at_each_trial, generated_config_dict)

    return generated_config_dict

