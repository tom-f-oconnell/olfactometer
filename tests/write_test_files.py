#!/usr/bin/env python3

from pprint import pprint
import json

import yaml
from inflection import underscore
from google.protobuf import json_format

from olfactometer import olf_pb2

# TODO probably refactor to use tmp files or strs / stringio objects, and delete
# this file + move its non-io parts into test.py


# TODO are there cases where we'll need to snakecase anything other than dict
# keys?
def snakecase_keys(d):
    if type(d) is not dict:
        return d
    return {underscore(k): snakecase_keys(v) for k, v in d.items()}


def write_test_files(verbose=False):
    '''
    settings = olf_pb2.Settings()
    settings.timing.pre_pulse_us = int(2e6)
    settings.timing.pulse_us = int(1e6)
    settings.timing.post_pulse_us = int(10e6)
    '''
    settings = olf_pb2.Settings()
    settings.follow_hardware_timing = True
    settings.enable_timing_output = True
    # Default is False
    #settings.no_ack = True

    pg1 = olf_pb2.PinGroup()
    pg2 = olf_pb2.PinGroup()
    pg3 = olf_pb2.PinGroup()

    # https://stackoverflow.com/questions/23726335
    pg1.pins.extend([4, 5, 6, 7, 8, 9, 10, 11, 12])
    pg2.pins.extend([4, 5])
    pg3.pins.extend([4])

    #pg1.pins.extend([2,2,2,3,3,3,4,4,4,5,5,5,6,6,6,7,7,7,8,8,8,
    #    9,9,9,10,10,10,11,11,11
    #])

    pin_sequence = olf_pb2.PinSequence()
    pin_sequence.pin_groups.extend([pg1, pg2, pg3])

    all_required_data = olf_pb2.AllRequiredData()
    # Apparently this CopyFrom syntax is required instead of assignment.
    # Not sure the reasoning behind that though...
    # https://stackoverflow.com/questions/18376190
    all_required_data.settings.CopyFrom(settings)
    all_required_data.pin_sequence.CopyFrom(pin_sequence)

    ddict = json_format.MessageToDict(all_required_data)
    if verbose:
        print('Original str representation:')
        print(all_required_data)
        print('Dictionary representation:')
        pprint(ddict)

    jstr = json_format.MessageToJson(all_required_data)
    with open('fh.json', 'w') as f:
        print(jstr, file=f)
    if verbose:
        print('JSON:')
        print(jstr)

    # `sort_keys` available in at least PyYAML>=5.1
    ystr = yaml.dump(ddict, sort_keys=False)
    with open('fh.yaml', 'w') as f:
        print(ystr, file=f)
    if verbose:
        print('YAML:')
        print(ystr)

    us_ddict = snakecase_keys(ddict)
    if verbose:
        print('Snakecase-keys dictionary representation:')
        pprint(us_ddict)

    jstr_us = json.dumps(us_ddict)
    with open('fh_underscore.json', 'w') as f:
        print(jstr_us, file=f)
    if verbose:
        print('Snakecase-keys JSON:')
        print(jstr_us)

    ystr_us = yaml.dump(us_ddict, sort_keys=False)
    with open('fh_underscore.yaml', 'w') as f:
        print(ystr_us, file=f)
    if verbose:
        print('Snakecase-keys YAML:')
        print(ystr_us)


def main():
    write_test_files(verbose=True)


if __name__ == '__main__':
    main()

