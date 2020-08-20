#!/usr/bin/env python3

import os
from os.path import split, join, realpath, abspath, exists
import binascii
import time
import subprocess
import warnings
import sys
import tempfile

import serial
from google.protobuf.internal.encoder import _VarintBytes
from google.protobuf import json_format, pyext
import yaml

from olfactometer import upload

in_docker = 'OLFACTOMETER_IN_DOCKER' in os.environ

# TODO TODO could try to replace everything using this w/
# pkg_resources.find_resource, though not sure this will actually support any
# more cases as i'm using both (+ in python 3.7+ another module is recommended
# for the same function) (.whl should be the case to test)
# This will be under site-packages if pip installed (in default, non-editable
# mode at least).
this_package_dir = split(abspath(realpath(__file__)))[0]

assert exists(this_package_dir), \
    f'this_package_dir={this_package_dir} does not exist'

# TODO need to specify path to .proto file when this is installed as a script
# (probably need to put it in some findable location using setuptools...)
# (i'm just going to try 'python -m <...>' syntax for running scripts for now)

# The build process handles this in the Docker case. If the code would changes
# (which can only happen through a build) it would trigger protoc compilation as
# part of the build.
if not in_docker:
    # TODO maybe only do this if installed editable / not installed and being
    # used from within source tree? (would probably have to be a way to include
    # build in setup.py... and not sure there is)
    # TODO only do this if proto_file has changed since the python outputs have
    proto_file = join(this_package_dir, 'olf.proto')
    proto_path, _ = split(proto_file)
    p = subprocess.Popen(['protoc', f'--python_out={this_package_dir}',
        f'--proto_path={proto_path}', proto_file
    ])
    p.communicate()
    failure = bool(p.returncode)
    if failure:
        # TODO delete me
        print('proto_path:', proto_path)
        print('proto_file:', proto_file)
        print('this_package_dir:', this_package_dir)
        #
        raise RuntimeError(f'generating python code from {proto_file} failed')

# TODO is pb2 suffix indication i'm not using the version i want?
# syntax was version 3, and the generated code seems to acknowledge that...
from olfactometer import olf_pb2


if in_docker:
    # TODO TODO TODO does this bode poorly for latency of pyserial communication
    # / need to flush that? (ultimately test docker deployment [perhaps also
    # including specifically on windows, if that even works with pyserial] with
    # hardware recording the outputs to verify the timing in software)
    # TODO one test might be serial writing something to arduino which should
    # trigger a led change, immediately followed by time.sleep, and see if the
    # LED change happens any more reliably / with lower latency without docker.
    # need a read test too though, + better tests.
    # TODO TODO maybe also flush after each serial read / write here, or
    # change some of the other pyserial settings?
    # TODO some less hacky fix for print?
    _builtin_print = print
    def flush_print(*args, **kwargs):
        # Ignoring any passed values
        if 'flush' in kwargs:
            del kwargs['flush']
        _builtin_print(*args, flush=True, **kwargs)
    print = flush_print

nanopb_options_path = join(this_package_dir, 'olf.options')
with open(nanopb_options_path, 'r') as f:
    lines = [x.strip() for x in f.readlines()]
nanopb_options_lines = [x for x in lines if len(x) > 0 and not x[0] == '#']

# TODO implement preprocessing of config from intermediate (dict probably?  yaml
# and json loaders can be configured to give comprable output?) to infer keys
# that aren't really necessary (like pinGroups / pins) (and maybe allow 'pins'
# to be used in place of pinSequence? could be a mess for maintainability
# though...
# TODO maybe try nesting the PinGroup object into the other message type, and
# see if that changes the json syntax? (would have to adapt C code a bit though,
# AND might prevent nanopb from optimizing as much from the *.options)
# TODO TODO and also probably allow seconds / ms units for PulseTiming fields

def load_json(json_filelike, message=None):
    if message is None:
        message = olf_pb2.AllRequiredData()
    json_data = json_filelike.read()
    # filelike does not work here. str does.
    json_format.Parse(json_data, message)
    return message


def load_yaml(yaml_filelike, message=None):
    if message is None:
        message = olf_pb2.AllRequiredData()

    # TODO safe_load accept str / filelike or both?
    # TODO do we actually need any of the yaml 1.2(+?) features
    # available in ruamel.yaml but not in PyYAML (1.1 only)?
    json_format.ParseDict(yaml.safe_load(yaml_filelike), message)

    return message


def load(json_or_yaml_path=None):
    """Parses JSON or YAML file into an AllRequiredData message object.

    Args:
    json_or_yaml_path (str or None): path to JSON or YAML file.
        must end in .json or .yaml. If `None`, reads from `sys.stdin`

    Returns an `olf_pb2.AllRequiredData` object.
    """
    # TODO any way to pass stdin back to interactive input, after (EOF?)?
    # (for interactive stuff during trial, like pausing...) (if not, maybe
    # implement pausing as arduino tracking state and knowing when host
    # disconnects?)
    if json_or_yaml_path is None:
        # Assuming we are reading from `sys.stdin` in this case, as I have not
        # yet settled on other mechanisms for getting files into Docker.
        print('Reading config from stdin')
        stdin_str = sys.stdin.read()

        if len(stdin_str) == 0:
            assert in_docker
            raise IOError('you must use the -i flag with docker run')

        if stdin_str.lstrip()[0] == '{':
            suffix = '.json'
        else:
            suffix = '.yaml'

        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False
            ) as temp:
            json_or_yaml_path = temp.name
            temp.write(stdin_str)

    all_required_data = olf_pb2.AllRequiredData()

    with open(json_or_yaml_path, 'r') as f:
        if json_or_yaml_path.endswith('.json'):
            load_json(f, all_required_data)

        elif json_or_yaml_path.endswith('.yaml'):
            load_yaml(f, all_required_data)
        else:
            raise ValueError('file must end with either .json or .yaml')

    return all_required_data


def max_count(name):
    """Returns the int max_count field associated with name in olf.options.
    """
    field_and_sep = 'max_count:'
    for line in nanopb_options_lines:
        if line.startswith(name):
            rhs = line.split()[1]
            if rhs.startswith(field_and_sep):
                try:
                    return int(rhs[len(field_and_sep):])
                except ValueError as e:
                    # Parsing could fail if there is a comment right after int,
                    # but should just avoid making lines like that in the
                    # options file.
                    print('Fix this line in the olf.options file:')
                    print(line)
                    raise
    raise ValueError(f'no lines starting with name={name}')


# TODO TODO figure out max pulse feature size (micros overflow period, i think,
# divided by 2 [- 1?]?). check none of  [pre/post_]pulse_us / pulse_us are
# longer
def validate_settings(settings, **kwargs):
    # 0 = disabled.
    if settings.balance_pin != 0:
        validate_pin(balance_pin)

    if settings.timing_output_pin != 0:
        validate_pin(timing_output_pin)

    if settings.WhichOneof('control') == 'follow_hardware_timing':
        if not settings.follow_hardware_timing:
            raise ValueError('follow_hardware_timing must be True if using it '
                'in place of the PulseTiming option'
            )
    if settings.no_ack:
        raise ValueError('only -i command line arg should set settings.no_ack')


def validate_pin_sequence(pin_sequence, warn=True):
    # Could make the max count validation automatic, but not really worth it.
    mc = max_count('PinSequence.pin_groups')
    gc = len(pin_sequence.pin_groups)
    if gc == 0:
        raise ValueError('PinSequence should not be empty')
    elif gc > mc:
        raise ValueError('PinSequence has length longer than maximum '
            f'({gc} > {mc})'
        )
    if warn:
        glens = {len(g.pins) for g in pin_sequence.pin_groups}
        if len(glens) > 1:
            warnings.warn(f'PinSequence has unequal length groups ({glens})')


# TODO might want to require communication w/ arduino here somehow?
# or knowledge of which arduino's are using which pins?
# (basically trying to duplicated the pin_is_reserved check on the arduino side,
# on top of other basic bounds checking)
def validate_pin(pin):
    assert type(pin) is int
    if pin < 0:
        raise ValueError('pin must be positive')
    elif pin in (0, 1):
        raise ValueError('pins 0 and 1 and reserved for Serial communication')
    # TODO can the arduino mega analog input pins also be used as digital
    # outputs? do they occupy the integers just past 53?
    # Assuming an Arduino Mega, which should have 53 as the highest valid
    # digital pin number (they start at 0).
    elif pin > 53:
        raise ValueError('pin numbers >53 invalid')


def validate_pin_group(pin_group, **kwargs):
    mc = max_count('PinGroup.pins')
    gc = len(pin_group.pins)
    if gc == 0:
        raise ValueError('PinGroup should not be empty')
    elif gc > mc:
        raise ValueError(f'PinGroup has {gc} pins (> max {mc}): {pin_group}')

    if len(pin_group.pins) != len(set(pin_group.pins)):
        raise ValueError('PinGroup has duplicate pins: {pin_group}')

    for p in pin_group.pins:
        validate_pin(p)


# TODO rename to _full_name... if i end up switching to that one
# Each function in here should take either **kwargs (if no potential warnings)
# or warn=True kwarg. They should return None and may raise ValueError.
_name2validate_fn = {
    'Settings': validate_settings,
    'PinSequence': validate_pin_sequence,
    'PinGroup': validate_pin_group
}
def validate(msg, warn=True, _first_call=True):
    """Raises ValueError if msg validation fails.
    """
    if isinstance(msg, pyext._message.RepeatedCompositeContainer):
        for value in msg:
            validate(value, warn=warn, _first_call=False)
        return
    elif isinstance(msg, pyext._message.RepeatedScalarContainer):
        # Only iterating over and validating these elements to try to catch any
        # base-case types that I wasn't accounting for.
        for value in msg:
            validate(value, warn=warn, _first_call=False)
        return
    try:
        # TODO either IsInitialized or FindInitializationErrors useful?
        # latter only useful if former is False or what? see docs
        # (and are the checks that happen in parsing redundant with these?)
        # TODO i assume UnknownFields is checked at parse time by default?

        # TODO remove any of the following checks that are redundant w/ the
        # (from json) parsers
        if not msg.IsInitialized():
            raise ValueError()

        elif msg.FindInitializationErrors() != []:
            raise ValueError()

        elif len(msg.UnknownFields()) != 0:
            raise ValueError()

    except AttributeError:
        if _first_call:
            # Assuming if it were one of this top level types, it would have
            # all the methods used in the try block, and thus it wouldn't have
            # triggered the AttributeError. maybe a better way to phrase...
            raise ValueError('msg should be a message type from olf_pb2 module')

        if type(msg) not in (int, bool):
            raise ValueError(f'unexpected type {type(msg)}')
        return

    name = msg.DESCRIPTOR.name
    full_name = msg.DESCRIPTOR.full_name
    assert name == full_name, \
        f'{name} != {full_name} decide which one to use and fix code'

    if name in _name2validate_fn:
        _name2validate_fn[name](msg, warn=warn)
        # Not returning here, so that i don't have to also implement recursion
        # in PinSequence -> PinGroup

    # The first element of each tuple returned by ListFields is a
    # FieldDescriptor object, but we are using (the seemingly equivalent)
    # msg.DESCRIPTOR instead.
    for _, value in msg.ListFields():
        validate(value, warn=warn, _first_call=False)


def parse_baud_from_sketch():
    sketch = join(this_package_dir, 'firmware', 'olfactometer',
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


# TODO TODO also have python parse the "trial: <n>, pins(s): ..." messages from
# arduino (when sent?) and check that timing is at least roughly right, in the
# pulse timing case

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

    def print_bytes(bs):
        s = bs.hex()
        print(' '.join([a+b for a,b in zip(s[::2], s[1::2])]))

    def write_bytes(bs):
        assert type(bs) is bytes
        n_bytes_written = ser.write(bs)
        assert n_bytes_written == len(bs)

    def crc16_0x1021(bs):
        # This uses polynomial 0x1021 (same as what I'm using on Arduino side)
        crc = binascii.crc_hqx(varint_size + serialized, 0xFFFF)

        # TODO also check input size (...why?) / that output of crc *should* fit
        # into 2 bytes?

        # This 'big' [Endian] byte order works for comparing on Arduino side,
        # with current code there.
        crc_bytes = crc.to_bytes(2, 'big')
        assert type(crc_bytes) is bytes and len(crc_bytes) == 2
        return crc_bytes

    # TODO add unit tests where random parts of data and / or crc are changed
    # (after crc calculation, but before sending) (-> verify failure)
    crc_bytes = crc16_0x1021(varint_size + serialized)

    '''
    if verbose:
        print('size: ', end='')
        print_bytes(varint_size)
        print('serialized: ', end='')
        print_bytes(serialized)
    '''

    n_bytes = len(varint_size) + len(serialized) + 2
    if use_message_nums:
        n_bytes += 1

    if verbose:
        print(f'writing {n_bytes} bytes to arduino...', flush=True, end='')

    # TODO TODO TODO need to check we don't write more than arduino's buffer
    # size (until acked)? just 64 bytes, right? assert to fail if single
    # messages exceed? or what? can't just ack at end of message then, if i
    # really need ack's to tell python it's ok to send more of one message...
    # SEEMS SO!!!

    # TODO how to get it to fail in this case / wait for other bytes for
    # decoding? (it currently does, w/ delimited, but add unit tests for both
    # under and over size)
    #write_bytes(serialized[:12])

    write_bytes(varint_size)
    write_bytes(serialized)
    write_bytes(crc_bytes)

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
        write_bytes(curr_msg_num.to_bytes(1, 'big'))
        ser.flush()

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


# TODO TODO maybe add a block=True flag to allow (w/ =False) to return, to not
# need to start this function in a new thread or process when trying to run the
# olfactometer and other code from one python script. not needed as a command
# line arg, cause already a separate process at that point.
# (or would this just make debugging harder, w/o prints from arduino?)
def main(config_file, port='/dev/ttyACM0', fqbn=None, do_upload=False,
    ignore_ack=False, try_parse=False, verbose=False):

    if do_upload:
        # TODO save file modification time at upload and check if it has changed
        # before re-uploading with this flag... (just to save program memory
        # life...) (docker couldn't use...)

        # TODO maybe refactor back and somehow have a new section of argparser
        # filled in without flags here, indicating they are upload specific
        # flags. idiomatic way to do that? subcommand?

        # This raises a RuntimeError if the compilation / upload returns a
        # non-zero exit status, stopping further steps here, as intended.
        upload.main(port=port, fqbn=fqbn)

    if in_docker and config_file is not None:
        raise ValueError('passing filenames to docker currently not supported. '
            'instead, redirect stdin from that file. see README for examples.'
        )

    all_required_data = load(config_file)
    settings = all_required_data.settings
    pin_sequence = all_required_data.pin_sequence

    if verbose or try_parse:
        print('Config data:')
        print(all_required_data)

    warn = True
    validate(all_required_data, warn=warn)

    if try_parse:
        sys.exit()

    if ignore_ack:
        warnings.warn('ignore_ack should only be used for debugging')
        # Default is False
        settings.no_ack = True

    baud_rate = parse_baud_from_sketch()
    print(f'Baud rate (parsed from Arduino sketch): {baud_rate}')
    # TODO TODO define some class that has its own context manager that maybe
    # essentially wraps the Serial one? (just so people don't need that much
    # boilerplate, including explicit calls to pyserial, when using this in
    # other python code)
    with serial.Serial(port, baud_rate, timeout=0.1) as ser:
        print('Connected')
        # TODO how to write in such a way that we don't need this sleep?
        # any alternative besides having arduino write something?
        # Tried 0.75 and lower but none of those seemed to have any bytes
        # available on Arduino...
        time.sleep(1.0)

        write_message(ser, settings, ignore_ack=ignore_ack, verbose=verbose)

        write_message(ser, pin_sequence, ignore_ack=ignore_ack, verbose=verbose)

        if settings.follow_hardware_timing:
            print('Ready (waiting for hardware triggers)')
        else:
            print('Starting')

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

        # TODO have python exit when it gets the 'Finished'... line?

