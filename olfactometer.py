#!/usr/bin/env python3

# TODO maybe wrap this in a shell script / other python script which uses
# protoc to generate appropriate python definitions to import, so that import
# here will have latest version?

import os
from os.path import split, join
import binascii
import time

import serial
from google.protobuf.internal.encoder import _VarintBytes

# TODO is pb2 suffix indication i'm not using the version i want?
# syntax was version 3, and the generated code seems to acknowledge that...
import olf_pb2


this_script_dir = split(__file__)[0]


def parse_baud_from_sketch():
    sketch = join(this_script_dir, 'firmware', 'olfactometer',
        'olfactometer.ino'
    )
    with open(sketch, 'r') as f:
        lines = f.readlines()

    begin_prefix = 'Serial.begin('
    found_line = False
    for line in lines:
        if begin_prefix in line:
            if found_line:
                raise ValueError(f'too many {begin_prefix} lines in sketch to '
                    'parse baud rate'
                )
            found_line = True
            baud_line = line

    if not found_line:
        raise ValueError('no lines containing {begin_prefix} in sketch. could '
            'not parse baud rate'
        )

    parts = baud_line.split('(')
    assert len(parts) == 2
    parts = parts[1].split(')')
    assert len(parts) == 2
    baud_rate = int(parts[0])
    return baud_rate


def write_message(ser, msg):
    """
    Args:
    ser (serial.Serial)
    msg (protobuf generated class)
    """
    serialized = msg.SerializeToString()
    assert type(serialized) is bytes

    # https://www.datadoghq.com/blog/engineering/protobuf-parsing-in-python/
    size = len(serialized)
    varint_size = _VarintBytes(size)
    assert type(varint_size) is bytes

    def print_bytes(bs):
        s = bs.hex()
        print(' '.join([a+b for a,b in zip(s[::2], s[1::2])]))

    '''
    print('size:', end='')
    print_bytes(varint_size)
    print('serialized: ', end='')
    print_bytes(serialized)
    '''

    print('writing to arduino...', flush=True, end='')

    n_bytes_written = ser.write(varint_size)
    assert n_bytes_written == len(varint_size)

    # TODO how to get it to fail in this case / wait for other bytes for
    # decoding?
    #n_bytes_written = ser.write(serialized[:12])

    n_bytes_written = ser.write(serialized)
    assert n_bytes_written == size

    # This uses polynomial 0x1021 (same as what I'm using on Arduino side)
    crc = binascii.crc_hqx(varint_size + serialized, 0xFFFF)
    # TODO is big easiest for comparing to arduino vals?
    crc_bytes = crc.to_bytes(2, 'big')
    assert type(crc_bytes) is bytes and len(crc_bytes) == 2

    n_bytes_written = ser.write(crc_bytes)
    assert n_bytes_written == 2

    ser.flush()
    print(' done')


def main():
    baud_rate = parse_baud_from_sketch()
    with serial.Serial('/dev/ttyACM0', baud_rate, timeout=0.1) as ser:
        # TODO how to write in such a way that we don't need this sleep?
        # any alternative besides having arduino write something?
        # Tried 0.75 and lower but none of those seemed to have any bytes
        # available on Arduino...
        time.sleep(1.0)

        pulse_timing = olf_pb2.PulseTiming()
        pulse_timing.pre_pulse_us = int(2e6)
        pulse_timing.pulse_us = int(1e6)
        pulse_timing.post_pulse_us = int(10e6)

        write_message(ser, pulse_timing)

        while True:
            line = ser.readline()
            if len(line) > 0:
                #print(line.decode(), end='')
                print(line)

    import ipdb; ipdb.set_trace()


if __name__ == '__main__':
    main()

