"""
Takes YAML input describing a panels of odors and returns config to present
them, either in the order in the YAML or randomly. Odors are assigned to random
valves from the set of available valves (identified by the pin number driving
them).

I have not yet implemented support for repeated presentations of the same odor.

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

import random

from olfactometer.generators import common

# (implement either something like this, used in place of yaml loading here, or
# some OOP thing, when i extend support to a second+ generator)
#from olfactometer import parse_common_generator_config


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

    When passed a Python file, rather than directly usable configuration YAML,
    the olfactometer will expect the Python file to have a function with this
    name and this output behavior. 
    """
    data = generator_config_yaml_dict

    generated_config_dict = common.parse_common_settings(data)

    available_valve_pins, pins2balances, single_manifold = \
        common.get_available_pins(data, generated_config_dict)

    odors = data['odors']
    # TODO factor out this validation
    # Each element of odors, which is a dict, must at least have a `name`
    # describing what that odor is (e.g. the chemical name).
    assert all([('name' in o) for o in odors])
    assert type(odors) is list

    n_odors = len(odors)
    assert len(available_valve_pins) >= n_odors
    # The means of generating the random odor vial <-> pin (valve) mapping.
    odor_pins = random.sample(available_valve_pins, n_odors)

    # The YAML dump downstream (which SHOULD include this data) should sort the
    # keys by default (just for display purposes, but still what I want).
    # TODO maybe still re-order (by making a new dict and adding in the order i
    # want), because sort_keys=True default also re-orders some other things i
    # don't want it to
    pins2odors = {p: o for p, o in zip(odor_pins, odors)}

    # TODO maybe err w/ useful message if True used instead of true, and if YAML
    # parser cares (and if i'm remembering the typical behavior correctly...)
    # (& same w/ False / false)
    randomize_presentation_order = data['randomize_presentation_order']
    assert randomize_presentation_order in (True, False)

    # TODO TODO add support for multiple trials (and then probably also allow
    # them to be grouped in repeated presentations or have everything
    # randomized)
    trial_pins = odor_pins
    if randomize_presentation_order:
        # This re-orders odor_pins in-place (it modifies it, rather than
        # returning something modified).
        random.shuffle(trial_pins)

    # No mixtures supported in this config generation function
    if single_manifold:
        pinlist_at_each_trial = [[p] for p in trial_pins]
    else:
        # Since the global balance is disable in the !single_manifold case, we
        # need to explicitly tell the correct balance pin to trigger alongside
        # each odor pin.
        pinlist_at_each_trial = [[p, pins2balances[p]] for p in trial_pins]

    generated_config_dict['pins2odors'] = pins2odors
    common.add_pinlist(pinlist_at_each_trial, generated_config_dict)

    # TODO functions to allow running generators standalone (to produce output
    # either printed or at a path specified at input, for inspection)?

    return generated_config_dict


# TODO maybe some other way of implementing generators (OOP?) would make it
# easier to extend some of the builtin ones? and *maybe* that'd be desirable?
# get concrete example before serious consideration...

# TODO maybe map from (bool?) kwargs to appropriate YAML input in calls to this
# config fn, and don't actually do YAML parsing here? or some other way to
# translate from either (portions of) the input YAML (maybe just parse some and
# return unparsed stuff) or command line args to kwargs here?

# TODO in core stuff (outside generators), validation for what an odor (dict w/
# just name, log10_conc keys and correct type on RHS?) should be represented as
# (to share across generators)? or is that moving too close to trying to
# implement support for all possible trial structures?

# TODO TODO how to make configuration of input general across generators,
# including those not-yet-implemented? (i.e. do i expect all generators to take
# an input filename, and let them do with it as they want?)
# or should i just use linux shell to compose generators with olfactometer?
# i'm almost sure there would be some big downsides to the shell approach...
# TODO if always taking filename input, maybe print which one used and copy its
# contents as part of metadata output in olfactometer code that invokes the
# generators?
# TODO if further requiring it to always be YAML, maybe check it's valid YAML
# outside of the individual generators? tradeoff between flexibility and
# consistent expectations i guess. though if i'm allowing arbitrary generators
# (outside of this source control...) maybe i would need to copy the python as
# well anyway, and then maybe all the config could just be in python, editing
# the generator as necessary? i do kind of like further seperation of code and
# config, even if this one part of the config is code itself, but it could be
# written by less people than the number who use it by just making their own
# YAML inputs...
# TODO maybe support passing any unparsed YAML input params through to
# olfactometer YAML? or put them under a separate YAML dict to make that
# explicit? maybe could then check between those and remainder, all are parsed
# either here or in downstream YAML parsing? not sure...
# (would all require input *is* a YAML)

# TODO add 'abbrev'/'abbreviation' key to shared odor representation support?
# (alongside 'name' and 'log10_conc')
# TODO maybe also just permit arbitrary extra metadata keys on the odors, for
# example to specify target glomeruli for a panel of private (diagnostic) odors?

# TODO maybe take a 'generator: <x>' YAML arg (to olfactometer, not a generator)
# to specify the generator, and use this to assume rest of YAML should be passed
# to that *built-in* generator, rather than specifying the path to a custom
# generator

