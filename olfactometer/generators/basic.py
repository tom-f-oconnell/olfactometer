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


def get_pin_for_odor(pins2odors, odor) -> int:
    """
    Assumes that if `odor` is not a dict, then it is an alias for an odor (which should
    currently be a str, though that is not enforced).
    """
    pin = None
    for p, pin_odor in pins2odors.items():

        # == won't behave as we want here, hence the custom equality checking fn
        if (type(odor) is dict and common.odors_equal(odor, pin_odor)) or (
            'alias' in pin_odor and pin_odor['alias'] == odor):

            pin = p
            break

    # TODO separate error message depending on whether it was an alias or odor dict that
    # wasn't found?
    assert pin is not None
    return pin


def is_co2(odor: dict) -> bool:
    return odor['name'].upper() == 'CO2'


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

    # TODO just delete single_manifold return value (the 3rd returned arg) from def of
    # common.get_available_pins? can always check set of pins2balances.values()...
    available_valve_pins, pins2balances, single_manifold = common.get_available_pins(
        data, generated_config_dict
    )
    n_manifolds = len(set(pins2balances.values()))

    # unique_odors will not include the air_mix entries, but odors_in_order will
    unique_odors, odors_in_order = common.get_odors(data)

    have_air_mixes = any(common.is_air_mix(o) for o in odors_in_order)
    if have_air_mixes:
        # each element of this should be a list of aliases
        air_mixes = [
            o[common.air_mix_key] for o in odors_in_order if common.is_air_mix(o)
        ]
        # validate_odors should have all ready checked these lists only refer to aliases
        # defined for another odor in the list
        assert all(len(mix_odors) <= n_manifolds for mix_odors in air_mixes), (
            'some air_mix entries requested more components than number of '
            f'available manifolds ({n_manifolds})'
        )

    n_odors = len(unique_odors)
    if n_odors > len(available_valve_pins):
        if have_air_mixes:
            raise NotImplementedError('air_mix entries currently only supported if '
                'odors fit into available pins/manifolds (without splitting into '
                'separate runs)'
            )

        # TODO should it be an error if this is False, but randomize_presentation_order
        # is True?
        #
        # If False, will split odors based on original order in list.
        randomly_split_odors_into_runs = data.get('randomly_split_odors_into_runs',
            True
        )
        assert randomly_split_odors_into_runs in (True, False)

        # NOTE: as-is, this would currently also fail in have_air_mixes=True case
        #
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
    # TODO doc that this defaults to False in have_air_mixes case?
    # (or warn/err in one of unset/explicitly-True cases?)
    if have_air_mixes:
        # would just be more work to support
        fit_into_one_manifold_if_possible = False

    # validate_odors (via get_odors) already validated aliases are unique
    alias2odor = {o['alias']: o for o in odors_in_order if 'alias' in o}

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


    # if this is False, we would need to open >=2 valves on one manifold to deliver a
    # mix, and we don't want to do that (b/c we don't want to rely on flow being divided
    # evenly between simultaneously open valves)
    def mix_components_on_diff_manifolds(pins2odors) -> bool:
        for air_mix in air_mixes:
            component_pins = [get_pin_for_odor(pins2odors, alias) for alias in air_mix]
            assert len(component_pins) == len(set(component_pins))

            component_balances = [pins2balances[p] for p in component_pins]
            # at least 2 components are sharing a balance (and thus sharing a manifold.
            # each manifold has its own balance.)
            if len(component_balances) > len(set(component_balances)):
                return False

        return True


    pins2odors = None
    if odor_pins is None:
        # bounding tries as easy way to fail in [A,B], [B,C], [A,C] (air_mixes) case
        # (not possible on 2 manifolds) (otherwise, should have to be really
        # unlikely for it to not work in that many tries. could hardcode this higher
        # if needed.)
        max_attempts = 500
        for i in range(max_attempts):
            # The means of generating the random odor vial <-> pin (valve) mapping.
            curr_odor_pins = random.sample(available_valve_pins, n_odors)

            pins2odors = {p: o for p, o in zip(curr_odor_pins, unique_odors)}
            if not have_air_mixes or mix_components_on_diff_manifolds(pins2odors):
                odor_pins = curr_odor_pins
                break

        if odor_pins is None:
            # (if we got really unlucky)
            raise RuntimeError('failed to generate odor_pins that keeps air_mix '
                'components on different manifolds. most likely mix combinations '
                'specified can not all be presented on this number of manifolds '
                f'({n_manifolds}). re-trying could fix if you were really unlucky.'
            )
    else:
        # The YAML dump downstream (which SHOULD include this data) should sort the
        # keys by default (just for display purposes, but still what I want).
        # TODO maybe still re-order (by making a new dict and adding in the order i
        # want), because sort_keys=True default also re-orders some other things i
        # don't want it to
        pins2odors = {p: o for p, o in zip(odor_pins, unique_odors)}

    assert pins2odors is not None

    randomize_presentation_order_key = 'randomize_presentation_order'
    # TODO refactor to some bool parse fn in common/above?
    if randomize_presentation_order_key in data:
        randomize_presentation_order = data[randomize_presentation_order_key]
        assert randomize_presentation_order in (True, False)
    else:
        # TODO why special case len(odors_in_order) == 1 anyway? won't randomization do
        # nothing there anyway? remove?
        if len(odors_in_order) > 1:
            warnings.warn(f'defaulting to {randomize_presentation_order_key}'
                '=True, since not specified in config'
            )
            randomize_presentation_order = True
        else:
            assert len(odors_in_order) == 1
            randomize_presentation_order = False

    consecutive_repeats = data.get('consecutive_repeats', True)

    block_shuffle_key = 'independent_block_shuffles'
    # TODO why do i need block_shuffle_key if i can just set `consecutive_repeat:
    # False` for `randomize_presentation_order: True`? could prob simplify
    independent_block_shuffles = data.get(block_shuffle_key, True)
    if independent_block_shuffles:
        assert randomize_presentation_order, ('randomize_presentation_order must be '
            f'True if {block_shuffle_key} specified'
        )
        # otherwise there are no "blocks", as all presentations of an odor are kept
        # consecutive.
        assert not consecutive_repeats, (f'{block_shuffle_key} should only be '
            'specified if consecutive_repeats=False also specified'
        )

    # if consecutive_repeats=False, this is number of "blocks". otherwise, it is the
    # number of consecutive presentations of each odor. in either case, it's the number
    # of times each odor will be presented.
    n_repeats = data.get('n_repeats', 1)

    # TODO refactor? also, if i make an Odor class w/ a meaningful hash, could simplify
    # this (as well as similar code in common.get_odors)
    trial_pins_norepeats = []
    for o in odors_in_order:
        if not common.is_air_mix(o):
            # TODO also want types in here to be list now, for consistency w/ air_mix
            # case below?
            trial_pins_norepeats.append(get_pin_for_odor(pins2odors, o))
        else:
            component_aliases = o[common.air_mix_key]
            # we have already checked that, when generating pins2odors above, all mix
            # components will be on diff manifolds
            component_pins = [
                get_pin_for_odor(pins2odors, alias) for alias in component_aliases
            ]
            trial_pins_norepeats.append(component_pins)

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
        # TODO better err message if YAML has `consecutive_repeats: True`, but doesn't
        # specify this (to True, i think). currently getting UnboundLocalError.
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

    # air mix entries will now already be list-of-ints in trial_pins
    trial_pinlists = [[p] if type(p) is int else p for p in trial_pins]

    pinlist_at_each_trial = common.add_balance_pins(
        trial_pinlists, pins2balances
    )

    co2_odors = [o for o in odors_in_order if is_co2(o)]
    if len(co2_odors) > 0:
        if len(co2_odors) > 1:
            # Since we only have one 'co2_pin', and don't currently support varying MFC
            # flows to get different CO2 concs (currently assuming log10_conc accurately
            # reflects air dilution between manually entered CO2 flow and currently set
            # odor + carrier flows.
            raise NotImplementedError('can only specify CO2 once')
        co2_odor = co2_odors[0]

        curr_co2_pins = [p for p, o in pins2odors.items() if is_co2(o)]
        assert len(curr_co2_pins) == 1
        curr_co2_pin = curr_co2_pins[0]

        co2_air_compensation_odor = {
            'name': 'air for co2-mixture compensation (leave disconnected)',
            'log10_conc': 0,
        }
        pins2odors[curr_co2_pin] = co2_air_compensation_odor

        assert 'co2_pin' in data, '`co2_pin: <int>` not specified in hardware YAML'
        co2_pin = data['co2_pin']
        pins2odors[co2_pin] = co2_odor

        assert not any([co2_pin in pl for pl in pinlist_at_each_trial])
        # TODO disable warning about PinSequence having unequal length groups, either
        # generally, or specifically for these cases (just warning in _DEBUG case
        # anyway, so fine to leave)
        pinlist_at_each_trial = [pl + [co2_pin] if curr_co2_pin in pl else pl
            for pl in pinlist_at_each_trial
        ]

    generated_config_dict['pins2odors'] = pins2odors
    common.add_pinlist(pinlist_at_each_trial, generated_config_dict)

    return generated_config_dict

