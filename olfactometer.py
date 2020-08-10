#!/usr/bin/env python3

# TODO maybe wrap this in a shell script / other python script which uses
# protoc to generate appropriate python definitions to import, so that import
# here will have latest version?

import os
from os.path import split, join
import binascii
import argparse
import time
import subprocess

import serial
from google.protobuf.internal.encoder import _VarintBytes

# TODO need to change syntax so this script is runnable from wherever? or no?
import upload

# TODO only do this if proto_file has changed since the python outputs have...
this_script_dir = split(__file__)[0]
proto_file = join(this_script_dir, 'olf.proto')
p = subprocess.Popen(['protoc', f'--python_out={this_script_dir}', proto_file])
p.communicate()
failure = bool(p.returncode)
if failure:
    raise RuntimeError(f'generating python code from {proto_file} failed')

# TODO is pb2 suffix indication i'm not using the version i want?
# syntax was version 3, and the generated code seems to acknowledge that...

# Importing this after regenerating Python code with subprocess above.
import olf_pb2


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


# Using an 8 bit, unsigned type to represent this on the Arduino side.
MAX_MSG_NUM = 255
curr_msg_num = 0
def write_message(ser, msg, verbose=False, use_message_nums=True,
    arduino_debug_prints=True, ignore_ack=False):
    """
    Args:
    ser (serial.Serial): serial device to receive the message

    msg (protobuf generated class): must have a `SerializeToString` method

    use_message_nums (bool, default=True): matches the USE_MESSAGE_NUMS
        preprocessor flag in the sketch. will number messages so the Arduino
        side can check it is not missing any.

    arduino_debug_prints (bool, default=False): if True, reads all bytes in 
        buffer before writing message num, to try to ensure the next byte we
        get back is just the message num.
    """
    # Since we are updating it in here, this is required.
    global curr_msg_num

    serialized = msg.SerializeToString()
    assert type(serialized) is bytes

    # TODO check this calculation is still correct for stuff with "repeated"
    # things in them
    # https://www.datadoghq.com/blog/engineering/protobuf-parsing-in-python/
    size = len(serialized)
    varint_size = _VarintBytes(size)
    assert type(varint_size) is bytes

    def print_bytes(bs):
        s = bs.hex()
        print(' '.join([a+b for a,b in zip(s[::2], s[1::2])]))

    '''
    if verbose:
        print('size: ', end='')
        print_bytes(varint_size)
        print('serialized: ', end='')
        print_bytes(serialized)
    '''

    if verbose:
        print('writing to arduino...', flush=True, end='')

    # TODO factor this write -> # bytes written check out...

    # TODO TODO need to check we don't write more than arduino's buffer size
    # (until acked)? just 64 bytes, right? assert to fail if single messages
    # exceed? or what? can't just ack at end of message then, if i really need
    # ack's to tell python it's ok to send more of one message...

    n_bytes_written = ser.write(varint_size)
    assert n_bytes_written == len(varint_size)

    # TODO how to get it to fail in this case / wait for other bytes for
    # decoding? (it currently does, w/ delimited, but add unit tests for both
    # under and over size)
    #n_bytes_written = ser.write(serialized[:12])

    n_bytes_written = ser.write(serialized)
    assert n_bytes_written == size

    # This uses polynomial 0x1021 (same as what I'm using on Arduino side)
    crc = binascii.crc_hqx(varint_size + serialized, 0xFFFF)

    # This 'big' [Endian] byte order works for comparing on Arduino side,
    # with current code there.
    crc_bytes = crc.to_bytes(2, 'big')
    assert type(crc_bytes) is bytes and len(crc_bytes) == 2

    # TODO add unit tests where random parts of data and / or crc are changed
    # (after crc calculation, but before sending) (-> verify failure)

    n_bytes_written = ser.write(crc_bytes)
    assert n_bytes_written == 2

    if use_message_nums:
        # TODO maybe do this between write and flush? does that guarantee it
        # won't be flushed earlier (probably not...)? (didn't seem to work there
        # anyway... though ser.out_waiting was zero all around it...)
        # This doesn't seem sufficient to prevent other prints from the Arduino
        # from obscuring the byte we want...
        if not ignore_ack and arduino_debug_prints:
            # TODO now that this is working with this hack, maybe delete
            # ignore_ack option?

            # At 115200 baud, seems we need to sleep at least about this long
            # for the any previous debug prints to all arrive. This is with an
            # Arduino-side flush right before the Arduino read for curr_msg_num
            # below. 0.005 did not work. Tested on Ubuntu 18.04 w/ USB3 port and
            # Arduino Mega.
            # TODO figure out fix that does not involve sleeping...
            time.sleep(0.008)
            n_input_bytes_discarded = ser.in_waiting
            # TODO maybe actually read them and format as below?
            ser.reset_input_buffer()

        # TODO this is unsigned if positive? arduino agrees on value for whole 8
        # bit range?
        before_sending_msg_num = time.time()
        n_bytes_written = ser.write(curr_msg_num.to_bytes(1, 'big'))
        # TODO want to ser.flush() here too?
        ser.flush()
        assert n_bytes_written == 1

        if not ignore_ack:
            # TODO should i just block for acknowledgement here, or make some
            # non-blocking interface?

            # TODO maybe keep track of times-to-ack, and maybe save as
            # experiment data even

            # Since the read has a timeout (not changeable by parameters to
            # read, it seems), we need to loop until we get the byte we want.
            while True:
                # TODO implement some timeout where we assume, beyond that, that
                # the arduino is in an error state? or otherwise, should i have
                # the arduino send a separate message with that state? maybe
                # before discussing msg num with it?
                arduino_msg_num_byte = ser.read()
                if len(arduino_msg_num_byte) > 0:
                    break

            time_to_msgnum_ack = time.time() - before_sending_msg_num

            arduino_msg_num = int.from_bytes(arduino_msg_num_byte, 'big')
            if arduino_msg_num != curr_msg_num:
                '''
                print('\n\nMESSAGE NUM FAILURE')
                print(arduino_msg_num_byte)
                print(arduino_msg_num_byte.decode())
                print(arduino_msg_num)
                import ipdb; ipdb.set_trace()
                '''
                raise RuntimeError('arduino sent wrong message num')

        # TODO test wraparound behavior (+ w/ arduino)
        curr_msg_num = (curr_msg_num + 1) % MAX_MSG_NUM
    else:
        ser.flush()

    if verbose:
        print(' done')
        if use_message_nums and not ignore_ack:
            if arduino_debug_prints and n_input_bytes_discarded > 0:
                print(f'Discarded {n_input_bytes_discarded} bytes in input '
                    'buffer (before sending msg num)'
                )
            print(f'Time to msg num ack: {time_to_msgnum_ack:.3f}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--upload', action='store_true', default=False,
        help='also uploads Arduino code before running'
    )
    # TODO maybe add arduino config parameter to ask the arduino not to send
    # msgnum acks in this case? (which would clutter the output)
    parser.add_argument('-i', '--ignore-ack', action='store_true',
        default=False, help='ignores acknowledgement message #s arduino sends. '
        'makes viewing all debug prints easier, as no worry they will interfere'
        ' with receipt of message number.'
    )
    args = parser.parse_args()

    if args.upload:
        # TODO save file modification time at upload and check if it has changed
        # before re-uploading with this flag... (just to save program memory
        # life...)

        # TODO maybe refactor back and somehow have a new section of argparser
        # filled in without flags here, indicating they are upload specific
        # flags. idiomatic way to do that? subcommand?

        # This raises a RuntimeError if the compilation / upload returns a
        # non-zero exit status, stopping further steps here, as intended.
        upload.main()

    ignore_ack = args.ignore_ack
    verbose = True
    baud_rate = parse_baud_from_sketch()
    print(f'Baud rate (parsed from Arduino sketch): {baud_rate}')
    with serial.Serial('/dev/ttyACM0', baud_rate, timeout=0.1) as ser:
        # TODO how to write in such a way that we don't need this sleep?
        # any alternative besides having arduino write something?
        # Tried 0.75 and lower but none of those seemed to have any bytes
        # available on Arduino...
        time.sleep(1.0)

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

            # TODO do i want an option like no_ack to disable / enable debug
            # prints at runtime? or maybe just use this? or maybe neither is
            # worth...

        write_message(ser, settings, ignore_ack=ignore_ack,
            verbose=verbose
        )


        pin_sequence = olf_pb2.PinSequence()

        # TODO is the max size of this implemented in python protobuf outputs
        # too? or was that just a nanopb feature? (try to assign something
        # bigger here) (if not enforced in python, probably want to manually add
        # that validation here)

        # https://stackoverflow.com/questions/23726335
        #pin_sequence.pins.extend([4, 5, 6, 7, 8, 9, 10, 11, 12])
        #pin_sequence.pins.extend([4, 5])
        pin_sequence.pins.extend([4])

        write_message(ser, pin_sequence, ignore_ack=ignore_ack, verbose=verbose)


        while True:
            line = ser.readline()
            if len(line) > 0:
                try:
                    print(line.decode(), end='')
                # Docs say decoding errors will be a ValueError or a subclass.
                # UnicodeDecodeError, for instance, is a subclass.
                except ValueError as e:
                    print(e)
                    print(line)

    import ipdb; ipdb.set_trace()


if __name__ == '__main__':
    main()

