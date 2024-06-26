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
from copy import deepcopy

from olfactometer.generators import common


# TODO TODO add option to ignore odors from a list of other configs (+thread thru to olf
# CLI) (e.g. so that i don't do diagnostics in remy's megamat panel)
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

    # TODO add hardware config option to define priority for pins (when not all will be
    # used), and use that to avoid picking pins on the edge of each quick change
    # assembly (more strain on some of the parts. i should probably just remake them w/
    # longer tubing / diff spacing tho...)?

    available_valve_pins, pins2balances, single_manifold = common.get_available_pins(
        data, generated_config_dict
    )

    unique_odors, odors_in_order = common.get_odors(data)

    n_odors = len(unique_odors)
    if n_odors > len(available_valve_pins):

        # TODO should it be an error if this is False, but randomize_presentation_order
        # is True?
        #
        # If False, will split odors based on original order in list.
        randomly_split_odors_into_runs = data.get('randomly_split_odors_into_runs',
            True
        )
        assert randomly_split_odors_into_runs in (True, False)

        # TODO why did i impose this? i guess we might either get the same odor twice in
        # a recording? or if we are specifying it twice, it's probably because the
        # specific order or important? change error message to reflect that?
        assert n_odors == len(odors_in_order), ('multiple blocks of one odor not '
            'supported when n_odors > len(available_valve_pins)'
        )
        unique_odors = list(unique_odors)
        if randomly_split_odors_into_runs:
            random.shuffle(unique_odors)

        i = 0
        generated_config_dicts = []
        while True:
            odor_subset = unique_odors[i:(i+len(available_valve_pins))]

            # without this check, would currently get one final config with empty odors
            if len(odor_subset) == 0:
                assert len(generated_config_dicts) > 0
                return generated_config_dicts

            subset_input_config_dict = deepcopy(generator_config_yaml_dict)
            subset_input_config_dict['odors'] = odor_subset

            generated_config_dict = make_config_dict(subset_input_config_dict)
            generated_config_dicts.append(generated_config_dict)

            if len(odor_subset) < len(available_valve_pins):
                return generated_config_dicts

            i += len(available_valve_pins)

    fit_into_one_manifold_if_possible = data.get('fit_into_one_manifold_if_possible',
        True
    )
    odor_pins = None
    if fit_into_one_manifold_if_possible:
        balance_pins = set(pins2balances.values())
        pin_groups = [
            {p for p, b in pins2balances.items() if b == curr_b}
            for curr_b in balance_pins
        ]
        del balance_pins

        groups_that_could_fit_all = [g for g in pin_groups if (len(g) >= n_odors)]
        if len(groups_that_could_fit_all) > 0:
            group_to_use = random.choice(groups_that_could_fit_all)
            odor_pins = random.sample(group_to_use, n_odors)

    if odor_pins is None:
        # The means of generating the random odor vial <-> pin (valve) mapping.
        odor_pins = random.sample(available_valve_pins, n_odors)

    # The YAML dump downstream (which SHOULD include this data) should sort the
    # keys by default (just for display purposes, but still what I want).
    # TODO maybe still re-order (by making a new dict and adding in the order i
    # want), because sort_keys=True default also re-orders some other things i
    # don't want it to
    pins2odors = {p: o for p, o in zip(odor_pins, unique_odors)}

    randomize_presentation_order_key = 'randomize_presentation_order'
    # TODO refactor to some bool parse fn in common/above?
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

    consecutive_repeats = data.get('consecutive_repeats', True)

    block_shuffle_key = 'independent_block_shuffles'
    if block_shuffle_key in data:
        assert randomize_presentation_order, ('randomize_presentation_order must be '
            f'True if {block_shuffle_key} specified'
        )
        # otherwise there are no "blocks", as all presentations of an odor are kept
        # consecutive.
        assert not consecutive_repeats, (f'{block_shuffle_key} should only be '
            'specified if consecutive_repeats=False also specified'
        )
        independent_block_shuffles = data.get(block_shuffle_key, True)

    # if consecutive_repeats=False, this is number of "blocks". otherwise, it is the
    # number of consecutive presentations of each odor. in either case, it's the number
    # of times each odor will be presented.
    n_repeats = data.get('n_repeats', 1)

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

    if consecutive_repeats:
        if randomize_presentation_order:
            # Was previously using random.shuffle (which modifies in place) here, but
            # switched to random.sample to make more uniform with new code below. From
            # docs: "To shuffle an immutable sequence and return a new shuffled list,
            # use sample(x, k=len(x)) instead [of random.shuffle]."
            trial_pins_norepeats = random.sample(trial_pins_norepeats,
                k=len(trial_pins_norepeats)
            )

        trial_pins = [p for p in trial_pins_norepeats for _ in range(n_repeats)]
    else:
        trial_pins = []
        if independent_block_shuffles:
            for _ in range(n_repeats):
                curr_block_shuffle = random.sample(trial_pins_norepeats,
                    k=len(trial_pins_norepeats)
                )
                trial_pins.extend(curr_block_shuffle)
        else:
            # in this case, each block has the same (pseudo-random) order
            block_shuffle = random.sample(trial_pins_norepeats,
                k=len(trial_pins_norepeats)
            )
            for _ in range(n_repeats):
                trial_pins.extend(block_shuffle)

    trial_pinlists = [[p] for p in trial_pins]

    pinlist_at_each_trial = common.add_balance_pins(
        trial_pinlists, pins2balances
    )

    generated_config_dict['pins2odors'] = pins2odors
    common.add_pinlist(pinlist_at_each_trial, generated_config_dict)

    return generated_config_dict

