#!/usr/bin/env python3

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

randomize_first_ramped_odor: True

# Will also do solvent x each of these concentrations
global_log10_concentrations: [-5, -4, -3]

odor_pairs:
 - pair:
   - name: ethyl hexanoate
   - name: 1-hexanol

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


# TODO factor format/print fns to some share space
def format_odor(odor_dict):
    odor_str = odor_dict['name']
    if 'log10_conc' in odor_dict:
        odor_str += ' {}'.format(odor_dict['log10_conc'])
    return odor_str

def print_odor(odor_dict):
    print(format_odor(odor_dict))
    

# TODO may end up wanting to add support for changing the concentration range
# for particular odors. probably make global parameters mutually exclusive w/
# any of those, and have each odor's range specified explicitly if any are, to
# avoid ambiguity about which numbers apply.

# TODO TODO TODO somehow enable this generator to either specify a sequence of
# configuration outputs (want to randomize order of pairs too, since we can only
# do ~1 per recording anyway, w/ # of valves we have to work with, unless maybe
# i end up actually using 2 full manifolds...)
# (or keep track of state somehow, so that each invocation picks up in the
# appropriate place. might be trickier to get that right though...)

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

    # Leaving the validation (bounds checking) to the `olfactometer` script
    pre_pulse_s = float(data['pre_pulse_s'])
    pulse_s = float(data['pulse_s'])
    post_pulse_s = float(data['post_pulse_s'])

    us_per_s = 1e6
    pre_pulse_us = int(round(pre_pulse_s * us_per_s))
    pulse_us = int(round(pulse_s * us_per_s))
    post_pulse_us = int(round(post_pulse_s * us_per_s))

    available_valve_pins = data['available_valve_pins']
    assert type(available_valve_pins) is list

    # TODO TODO assuming this flow setup (with only 1 manifold & 2 MFCs) is
    # actually reasonable at all: i can do without a balance, right? just keep
    # the solvent flow division valve open? or maybe still keep the balance
    # separate?

    global_log10_concentrations = data['global_log10_concentrations']
    n_concentrations = len(global_log10_concentrations)

    # TODO especially if some pairs have odors w/ diff solvents, maybe have the
    # grid also include (0, 0) (w/ 2 diff solvents also in panel! probably put
    # in other keys for individual odors?)
    # TODO or otherwise, maybe add one for a solvent in each case? but if it's
    # always gonna be the same solvent anyway, maybe just do one at beginning
    # and end? not sure...
    # TODO TODO and if so, always do solvent at beginning? at end? beginning
    # would be consistent w/ decision to ramp concentrations. end would probably
    # reflect about the worst-case contamination?

    odor_pairs = data['odor_pairs']

    # TODO TODO TODO update if using different valve setup
    # All I'm supporting in this super short term, before I come up with some
    # mechanism to split stuff across recordings.
    assert len(odor_pairs) == 1, \
        'automatic splitting of >1 pairs not yet implemented'

    n_vials = 2 * n_concentrations + 1

    odor1_name, odor2_name = odor_pairs[0]['pair']
    assert type(odor1_name) is str
    assert type(odor2_name) is str

    odor_vials = [{'name': 'solvent'}]
    for n in (odor1_name, odor2_name):
        odor_vials.extend([
            {'name': n, 'log10_conc': c} for c in global_log10_concentrations
        ])

    # Currently only supporting the case where the trials are all consecutive.
    n_trials = data['n_trials']

    n_vials = len(odor_vials)
    # The '+ 1' is for a solvent blank that is shared between the two odors in
    # the pair (and likely would be across pairs too).
    # (The number of vials, since each concentration gets their own. NOT the #
    # of distinct chemicals; which is 2)
    assert n_vials == 2 * n_concentrations + 1
    assert len(available_valve_pins) >= n_vials

    # TODO TODO TODO if i use essentially 2 manifolds (or groups of valves) with
    # one MFC for each, i would probably first want to randomly pick which odor
    # (and all of its concentrations) gets one side, then randomly order
    # concentrations within each valve group (because mixtures will always
    # contain one from one odor and one from the other odor, so there's no point
    # to having some concentrations of A and B on the same manifold / valve
    # group)

    # The means of generating the random odor vial <-> pin (valve) mapping.
    odor_pins = random.sample(available_valve_pins, n_vials)

    pins2odors = {p: o for p, o in zip(odor_pins, odor_vials)}

    randomize_first_ramped_odor = data['randomize_first_ramped_odor']
    assert randomize_first_ramped_odor in (True, False)

    # TODO modify so only the keys used below (in get_vial) are included, or
    # modify get_vial so the match works despite any extra keys (just converting
    # all .items() to tuple will make the matches sensitive to this extra
    # information)
    # Just for use within this generator.
    vials2pins = {tuple(o.items()): p for p, o in pins2odors.items()}
    def get_vial_tuple(name, log10_conc=None):
        if log10_conc is None:
            # TODO TODO TODO modify for case where there are two solvents
            # (two manifolds / low-flow MFCs)
            vial_dict = {'name': 'solvent'}
        else:
            assert type(log10_conc) is int or type(log10_conc) is float
            vial_dict = {'name': name, 'log10_conc': log10_conc}
        return tuple(vial_dict.items())

    solvent_pin = vials2pins[(('name','solvent'),)]
    pinlist_at_each_trial = [solvent_pin] * n_trials

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
    # rather than i <= j. reversing the variables in each loop (for j -> for i)
    # would probably have the same effect.
    index_tuple_lists = [[(i, j)] if i == j else [(i, j), (j, i)]
        for i in range(len(concentrations))
        for j in range(len(concentrations)) if j <= i
    ]
    # Flatten out the nested lists created above (which were used to order stuff
    # symmetric across the diagonal at each off-diagonal step)
    pair_conc_index_order = [x for xs in index_tuple_lists for x in xs]
    del index_tuple_lists

    # The '+ 2 * n_concentrations' is for the single-odor case (where the other
    # is zero concentration, and instead the solvent valve is switched).
    # This is number of presentations (multplied by n_trials)
    n_unique_conc_pairs = n_concentrations**2 + 2 * n_concentrations + 1
    assert len(pair_conc_index_order) == n_unique_conc_pairs

    # The order in `odor_name_order`, and thus which odor name is assigned to
    # `n1` and which to `n2` determines the order in which they ramp. `n1` ramps
    # first (though which is ramped alternates between each set of
    # concentrations).
    n1, n2 = odor_name_order

    pinlist_at_each_trial = []
    # Just building this for debugging / display purposes. Could otherwise just
    # build a list of the corresponding pin-lists.
    odorlist_at_each_trial = []

    # Doing this rather than two (nested) for-loops, because we want to do all
    # combinations of the lower concentrations before moving on to any of the
    # higher concentrations (of either odor).
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

        # TODO TODO TODO when using two symmetric odor manifolds, each with
        # their own MFC always append the balance pin for BOTH (or change
        # firmware to support multiple balance pins)

        # Converting to a set first because if p1 == p2 (should only be relevant
        # in the (0,0) case when all odors are on the same manifold, and thus
        # there is only one shared solvent vial), we just want to open that
        # single valve, with all of the flow going through it.
        pins = sorted({p1, p2})
        pinlist_at_each_trial.extend([pins] * n_trials)

        # tried using this to improve YAML output format (to avoid references to
        # the same thing), but it turned out id(...) being the same for
        # consecutive entries wasn't what the only thing that caused that type
        # of output (in this list the id(...) of all elements (sublists) are
        # unique, unlike in the version built w/ .extend, where consecutive
        # trials have the same id).
        #for _ in range(n_trials):
        #    pinlist_at_each_trial.append([pins])

        # Again, just used for troubleshooting / display in here. pins above all
        # that matter for outputs.
        curr_odors = [o1, o2] if len(pins) > 1 else [o1]
        odorlist_at_each_trial.extend([curr_odors] * n_trials)

    expected_total_n_trials = n_trials * n_unique_conc_pairs
    assert len(pinlist_at_each_trial) == expected_total_n_trials
    del expected_total_n_trials

    '''
    from pprint import pprint
    print('first ramped odor:', n1)
    print('pinlist_at_each_trial:')
    pprint(pinlist_at_each_trial)
    print('odorlist_at_each_trial:')
    pprint(odorlist_at_each_trial)
    for i, os in enumerate(odorlist_at_each_trial):
        print('trial:', i + 1)
        for o in os:
            print_odor(dict(o))
        print()
    '''

    # TODO TODO TODO change balance_pin as necessary to support
    # multiple-manifold case
    balance_pin = data['balance_pin'] if 'balance_pin' in data else 0
    timing_output_pin = \
        data['timing_output_pin'] if 'timing_output_pin' in data else 0

    generated_yaml_dict = {
        'settings': {
            'timing': {
                'pre_pulse_us': pre_pulse_us,
                'pulse_us': pulse_us,
                'post_pulse_us': post_pulse_us
            },
            'balance_pin': balance_pin,
            'timing_output_pin': timing_output_pin
        },
        'pin_sequence': {
            'pin_groups': [{'pins': pins} for pins in pinlist_at_each_trial]
        },
        'pins2odors': pins2odors
    }

    return generated_yaml_dict


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

    generated_yaml_dict = make_config_dict(yaml_dict)

    from pprint import pprint
    pprint(generated_yaml_dict)

    print('\n' + '#' * 80)
    print(yaml.dump(generated_yaml_dict))

