"""
Takes YAML input describing a panels of odors and returns config to present
them, either in the order in the YAML or randomly. Odors are assigned to random
valves from the set of available valves (identified by the pin number driving
them).

As with the basic.py generator, still only planning on supporting the case where
the number of odors in the panel can fit into the number of valves available in
the particular hardware.

Example input (the part between the ```'s, saved to a YAML file, whose filename
is passed as input to `make_config_dict` below):
```
available_valve_pins: [2, 3, 4]

# currently unsupported in this generator. maybe decide i want to re-add it, or
# some other parameters controlling randomization.
#randomize_presentation_order: False

n_trials: 3

randomize_pair_order: True
randomize_first_ramped_odor: True

# Will also do solvent x each of these concentrations
global_log10_concentrations: [-5, -4, -3]

odor_pairs:
 - pair:
   - ethyl hexanoate
   - 1-hexanol
 - pair:
   - limonene
   - linalool

# Reformatted into settings.timing.*_us by [this] generator
pre_pulse_s: 2
pulse_s: 1
post_pulse_s: 11
```
"""
# TODO probably move this whole generator to my tom_olfactometer_configs at
# some point... it's pretty niche. unless it has enough use just as an
# example...

import random
from copy import deepcopy
import warnings

from olfactometer.generators import common


# TODO may end up wanting to add support for changing the concentration range
# for particular odors. probably make global parameters mutually exclusive w/
# any of those, and have each odor's range specified explicitly if any are, to
# avoid ambiguity about which numbers apply.

# TODO left pad ints up to max num digits used (for case where multple YAMLs are
# written, and each has a number in their name), so printing out sorted by name
# lists them in order

# TODO and maybe also print how many trials / time for that file? (move this
# todo to write_sequence or something)

def make_config_dict(generator_config_yaml_dict):
    """
    Args:
    generator_config_yaml_dict (str): dict of parsed contents of YAML
      configuration file.

    Returns `dict` representation of YAML config for olfactometer. Also includes
    a `pins2odors` YAML dictionary which is not used by the olfactometer, but
    which is for tracking which odors certain pins corresponded to, at analysis
    time.

    When passed a Python file, rather than directly usable configuration YAML,
    the olfactometer will expect the Python file to have a function with this
    name and this output behavior. 
    """
    data = generator_config_yaml_dict

    # TODO think about docs and maybe changes to interfaces to make more of this
    # stuff for-free if people were to implement their own generators
    common_generated_config_dict = common.parse_common_settings(data)

    global_log10_concentrations = data['global_log10_concentrations']
    n_concentrations = len(global_log10_concentrations)

    # Currently only supporting the case where the trials are all consecutive.
    n_trials = data['n_trials']

    odor_pairs = data['odor_pairs']

    # TODO maybe also support including multiple pairs in one recording,
    # if we have enough available pins (on each manifold)

    # TODO TODO better error message if config seems to be expecting separate
    # hardware config, but it's not set up correctly (and thus one of the
    # asserts about having some of the required keys fails in here)
    available_valve_pins, pins2balances, single_manifold = \
        common.get_available_pins(data, common_generated_config_dict)

    if not single_manifold:
        randomize_pairs_to_manifolds = data['randomize_pairs_to_manifolds']

        # don't want to worry about cases with more manifolds for now
        assert len(set(pins2balances.values())) == 2

        # TODO could maybe refactor stuff below to operate directly on outputs
        # and depend less on single_manifold to branch...
        # now i'm just re-extracting these from the config data, just as
        # get_available_pins is doing
        available_group1_valve_pins = data['available_group1_valve_pins']
        available_group2_valve_pins = data['available_group2_valve_pins']
        group1_balance_pin = data['group1_balance_pin']
        group2_balance_pin = data['group2_balance_pin']
    else:
        if 'randomize_pairs_to_manifolds' in data:
            warnings.warn('randomize_pairs_to_manifolds specified in config, '
                'but olfactometer only has one manifold. ignoring.'
            )

    randomize_pair_order = data['randomize_pair_order']
    if randomize_pair_order:
        random.shuffle(odor_pairs)

    # TODO refactor so loop body is just a function call?
    generated_config_dicts = []
    for pair in odor_pairs:
        generated_config_dict = deepcopy(common_generated_config_dict)

        odor1_name, odor2_name = pair['pair']
        assert type(odor1_name) is str
        assert type(odor2_name) is str

        if single_manifold:
            # This solvent is not the usual balance (though there is that too).
            # When delivering only a single component, the valve for this also
            # opens, to try to have the flow divide evenly, so that the total
            # flow for the component remains the same as when it's presented
            # with other odors.
            # Doing it this way, with just one additional solvent vial, assumes
            # all solvents are the same (assuming we care about this
            # background).
            # NOTE: as long as there is are trial[s] included that present just
            # this solvent by itself, the lengths of the pin lists in the
            # pin_sequence will be uneven, and that warning will get triggered
            # at run time, but it can be ignored
            odor_vials = [{'name': 'solvent'}]

            for n in (odor1_name, odor2_name):
                odor_vials.extend([{'name': n, 'log10_conc': c}
                    for c in global_log10_concentrations
                ])
            n_vials = len(odor_vials)
            # The '+ 1' is for a solvent blank that is shared between the two
            # odors in the pair (and likely would be across pairs too).
            # (The number of vials, since each concentration gets their own. NOT
            # the # of distinct chemicals; which is 2)
            assert n_vials == 2 * n_concentrations + 1
            assert len(available_valve_pins) >= n_vials
            # The means of generating random odor vial <-> pin (valve) mapping.
            odor_pins = random.sample(available_valve_pins, n_vials)
        else:
            # We first want to randomly pick which odor (and all of its
            # concentrations) gets one valve group (manifold), then randomly
            # order concentrations within each valve group (because mixtures
            # will always contain one concentraion of one odor and one of the
            # other odor, so there's no point to having some concentrations of A
            # and B on the same manifold / valve group)
            # Odor name at 0th index = manifold 1 (valve group 1)
            # Odor name at 1st index = manifold 2 (valve group 2)
            manifold_odors = [odor1_name, odor2_name]
            if randomize_pairs_to_manifolds:
                random.shuffle(manifold_odors)

            odor_vials = []
            odor_pins = []
            for n, available_group_valve_pins in zip(manifold_odors,
                (available_group1_valve_pins, available_group2_valve_pins)):

                assert len(available_group_valve_pins) >= n_concentrations + 1

                group_vials = [{'name': n, 'log10_conc': c}
                    for c in (None,) + tuple(global_log10_concentrations)
                ]
                odor_vials.extend(group_vials)

                odor_pins.extend(random.sample(available_group_valve_pins,
                    len(group_vials)
                ))

            assert len(odor_vials) == len(odor_pins)
            # + 2 here because there MUST be a separate solvent on each manifold
            assert len(odor_vials) == 2 * n_concentrations + 2

        pins2odors = {p: o for p, o in zip(odor_pins, odor_vials)}

        randomize_first_ramped_odor = data['randomize_first_ramped_odor']
        assert randomize_first_ramped_odor in (True, False)

        # TODO modify so only the keys used below (in get_vial) are included, or
        # modify get_vial so the match works despite any extra keys (just
        # converting all .items() to tuple will make the matches sensitive to
        # this extra information)
        # Just for use within this generator.
        vials2pins = {tuple(o.items()): p for p, o in pins2odors.items()}
        def get_vial_tuple(name, log10_conc=None):
            if single_manifold and log10_conc is None:
                vial_dict = {'name': 'solvent'}
            else:
                assert (type(log10_conc) is int or type(log10_conc) is float
                    or (not single_manifold and log10_conc is None)
                )
                vial_dict = {'name': name, 'log10_conc': log10_conc}
            return tuple(vial_dict.items())

        if randomize_first_ramped_odor:
            if random.choice((True, False)):
                odor_name_order = (odor1_name, odor2_name)
            else:
                odor_name_order = (odor2_name, odor1_name)
        else:
            odor_name_order = (odor1_name, odor2_name)
        # To avoid confusion with n1 and n2 below
        # (i.e. n1 != odor1_name, at least not always).
        del odor1_name, odor2_name

        concentrations = (None,) + tuple(sorted(global_log10_concentrations))

        # seems to follow the the column order i want if i use this inequality,
        # rather than i <= j. reversing the variables in each loop (for j -> for
        # i) would probably have the same effect.
        index_tuple_lists = [[(i, j)] if i == j else [(i, j), (j, i)]
            for i in range(len(concentrations))
            for j in range(len(concentrations)) if j <= i
        ]
        # Flatten out the nested lists created above (which were used to order
        # stuff symmetric across the diagonal at each off-diagonal step)
        pair_conc_index_order = [x for xs in index_tuple_lists for x in xs]
        del index_tuple_lists

        # The '+ 2 * n_concentrations' is for the single-odor case (where the
        # other is zero concentration, and instead the solvent valve is
        # switched).  This is number of presentations (multplied by n_trials)
        n_unique_conc_pairs = n_concentrations**2 + 2 * n_concentrations + 1
        assert len(pair_conc_index_order) == n_unique_conc_pairs

        # The order in `odor_name_order`, and thus which odor name is assigned
        # to `n1` and which to `n2` determines the order in which they ramp.
        # `n1` ramps first (though which is ramped alternates between each set
        # of concentrations).
        n1, n2 = odor_name_order

        pinlist_at_each_trial = []
        # Just building this for debugging / display purposes. Could otherwise
        # just build a list of the corresponding pin-lists.
        odorlist_at_each_trial = []

        # Doing this rather than two (nested) for-loops, because we want to do
        # all combinations of the lower concentrations before moving on to any
        # of the higher concentrations (of either odor).
        for conc_idx1, conc_idx2 in pair_conc_index_order:
            c1 = concentrations[conc_idx1]
            c2 = concentrations[conc_idx2]

            o1 = get_vial_tuple(n1, c1)
            o2 = get_vial_tuple(n2, c2)

            # This technically would still fail if (somehow) the order of the
            # dictionary items is different in get_vial_tuple than it was when
            # constructing vials2pins above. Probably won't happen though.
            p1 = vials2pins[o1]
            p2 = vials2pins[o2]

            # Converting to a set first because if p1 == p2 (should only be
            # relevant in the (0,0) case when all odors are on the same
            # manifold, and thus there is only one shared solvent vial), we just
            # want to open that single valve, with all of the flow going through
            # it.
            pins = sorted({p1, p2})
            if not single_manifold:
                # TODO TODO TODO actually, do i need two solvent vials in the
                # two manifold case? maybe then i really don't need ANY solvent
                # vials (since i can exactly halve the flow by only opening a
                # valve in one of the two manifolds) (maybe i want to keep the
                # noise level, etc the same too though?)

                assert len(pins) == 2, ('there should be distinct solvent '
                    'vials in the two manifold case'
                )
                # Because there is always going to be one valve opening on each
                # of the two manifolds, and we will need to close the normally
                # open valve on each of those manifolds along with that.
                # Handled differently than "balance_pin" in the single manifold
                # case because the firmware specifically supports the case where
                # there is a single balance pin, but it doesn't support two.
                pins.extend([group1_balance_pin, group2_balance_pin])

            pinlist_at_each_trial.extend([pins] * n_trials)

            # Again, just used for troubleshooting / display in here. pins above
            # all that matter for outputs.
            curr_odors = [o1, o2] if len(pins) > 1 else [o1]
            odorlist_at_each_trial.extend([curr_odors] * n_trials)

        expected_total_n_trials = n_trials * n_unique_conc_pairs
        assert len(pinlist_at_each_trial) == expected_total_n_trials
        del expected_total_n_trials

        generated_config_dict['pins2odors'] = pins2odors
        common.add_pinlist(pinlist_at_each_trial, generated_config_dict)

        generated_config_dicts.append(generated_config_dict)

    # TODO check log10_conc: None (-> 'null' in YAML) gets parsed correctly back
    # to None during a round trip

    # TODO want to squeeze output if list is only length 1?
    return generated_config_dicts


# TODO delete / change to something that takes arbitrary input for testing /
# standalone use. latter only would make sense if not centralizing the
# standalone generator use support (building on assumption they all return YAML
# dicts, etc)
if __name__ == '__main__':
    import yaml

    generator_config_yaml_fname = \
        '/home/tom/src/tom_olfactometer_configs/pair_concentration_grid.yaml'
    with open(generator_config_yaml_fname, 'r') as f:
        yaml_dict = yaml.safe_load(f)

    generated_config_dict = make_config_dict(yaml_dict)

    from pprint import pprint
    pprint(generated_config_dict)

    if type(generated_config_dict) is dict:
        print('\n' + '#' * 80)
        print(yaml.dump(generated_config_dict))
    else:
        for yaml_dict in generated_config_dict:
            assert type(yaml_dict) is dict
            print('\n' + '#' * 80)
            print(yaml.dump(yaml_dict))


