#!/usr/bin/env python3

import yaml

from olfactometer import olf_pb2

# TODO probably refactor to use tmp files or strs / stringio objects, and delete
# this file + move its non-io parts into test.py

def write_test_files():
    '''
    settings = olf_pb2.Settings()
    settings.timing.pre_pulse_us = int(2e6)
    settings.timing.pulse_us = int(1e6)
    settings.timing.post_pulse_us = int(10e6)
    '''
    #'''
    settings = olf_pb2.Settings()
    # TODO add validation in python wrapper class to prevent this from being
    # false if pulse_timing not specified
    settings.follow_hardware_timing = True
    #'''
    settings.enable_timing_output = True
    if ignore_ack:
        # Default is False
        settings.no_ack = True


    pin_sequence = olf_pb2.PinSequence()

    # TODO is the max size of this implemented in python protobuf outputs
    # too? or was that just a nanopb feature? (try to assign something
    # bigger here) (if not enforced in python, probably want to manually add
    # that validation here)

    # https://stackoverflow.com/questions/23726335
    #pin_sequence.pins.extend([4, 5, 6, 7, 8, 9, 10, 11, 12])
    pin_sequence.pins.extend([4, 5])
    #pin_sequence.pins.extend([4])
    #pin_sequence.pins.extend([2,2,2,3,3,3,4,4,4,5,5,5,6,6,6,7,7,7,8,8,8,
    #    9,9,9,10,10,10,11,11,11
    #])


    all_required_data = olf_pb2.AllRequiredData()
    # Apparently this CopyFrom syntax is required instead of assignment.
    # Not sure the reasoning behind that though...
    # https://stackoverflow.com/questions/18376190
    all_required_data.settings.CopyFrom(settings)
    all_required_data.pin_sequence.CopyFrom(pin_sequence)

    if verbose:
        ddict = json_format.MessageToDict(all_required_data)
        from pprint import pprint
        print(all_required_data)
        pprint(ddict)

    jstr = json_format.MessageToJson(all_required_data)
    with open('fh.json', 'w') as f:
        print(jstr, file=f)
    if verbose:
        print(jstr)

    # `sort_keys` available in at least PyYAML>=5.1
    ystr = yaml.dump(ddict, sort_keys=False)
    with open('fh.yaml', 'w') as f:
        print(ystr, file=f)
    if verbose:
        print(ystr)


def main():
    write_test_files(verbose=True)


if __name__ == '__main__':
    main()

