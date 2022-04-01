"""
Validation, primarily of config and hardware state.
"""

from os.path import join
import warnings

from google.protobuf import pyext

from olfactometer import THIS_PACKAGE_DIR, _DEBUG
from olfactometer.flow import flow_setpoints_sequence_key


nanopb_options_path = join(THIS_PACKAGE_DIR, 'olf.options')
with open(nanopb_options_path, 'r') as f:
    lines = [x.strip() for x in f.readlines()]
nanopb_options_lines = [x for x in lines if len(x) > 0 and not x[0] == '#']

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


def validate_port(port):
    """Raises ValueError if port seems invalid.

    Not currently intended to catch all possible invalid values, just some
    likely mistakes.
    """
    if type(port) is not str:
        raise ValueError('port not a str. did you pass it with -p?')

    # TODO TODO don't i have some code to detect port (at least in dev install
    # case?)? is that just in upload.py? not used here? i don't see anything
    # like that used to define port below...
    if port.endswith('.yaml') or port.endswith('.json'):
        raise ValueError('specify port after -p. currently this seems to be the'
            'config file path.'
        )

    # TODO actually check against what ports the system could have somehow?


# TODO TODO figure out max pulse feature size (micros overflow period, i think,
# divided by 2 [- 1?]?). check none of  [pre/post_]pulse_us / pulse_us are
# longer
# TODO rename 'settings' in the protobuf definition and in all references to be
# more spefific? in a way, everything in the AllRequiredData object is a
# setting... and it also might be nice to name the fn that validates
# AllRequiredData as validate_firmware_settings or something
def validate_settings(settings, **kwargs):
    """Raises ValueError if invalid settings are detected.
    """
    # 0 = disabled.
    if settings.balance_pin != 0:
        validate_pin(settings.balance_pin)

    if settings.timing_output_pin != 0:
        validate_pin(settings.timing_output_pin)

    if settings.recording_indicator_pin != 0:
        validate_pin(settings.recording_indicator_pin)

    if settings.WhichOneof('control') == 'follow_hardware_timing':
        if not settings.follow_hardware_timing:
            raise ValueError('follow_hardware_timing must be True if using it '
                'in place of the PulseTiming option'
            )
    if settings.no_ack:
        raise ValueError('only -k command line arg should set settings.no_ack')


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

    if _DEBUG and warn:
        glens = {len(g.pins) for g in pin_sequence.pin_groups}
        if len(glens) > 1:
            warnings.warn(f'PinSequence has unequal length groups ({glens})')


# TODO might want to require communication w/ arduino here somehow?
# or knowledge of which arduino's are using which pins?
# (basically trying to duplicated the pin_is_reserved check on the arduino side,
# on top of other basic bounds checking)
def validate_pin(pin):
    """Raises ValueError in many cases where pin would fail on Arduino side.

    If an error is raised, the pin would definitely be invalid, but if no error
    is raised there are still some cases where the pin would not produce the
    intended results, as this has no knowledge of which pins are actually used
    on the Arduino, nor which version of an Arduino is being used.
    """
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


# TODO why do i have this taking **kwargs again?
def validate_pin_group(pin_group, **kwargs):
    """Raises ValueError if invalid pin_group is detected.
    """
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
# TODO try to find a means of referencing these types that works in both the
# ubuntu / windows deployments. maybe the second syntax would work in both
# cases? test on ubuntu.
try:
    # What I had been using in the previously tested Ubuntu deployed versions.
    msg = pyext._message
    repeated_composite_container = msg.RepeatedCompositeContainer
    repeated_scalar_container = msg.RepeatedScalarContainer

# AttributeError: module 'google.protobuf.pyext' has no attribute '_message'
except AttributeError:
    from google.protobuf.internal import containers
    repeated_composite_container = containers.RepeatedCompositeFieldContainer
    repeated_scalar_container = containers.RepeatedScalarFieldContainer

def validate_protobuf(msg, warn=True, _first_call=True):
    """Raises ValueError if msg validation fails.
    """
    if isinstance(msg, repeated_composite_container):
        for value in msg:
            validate_protobuf(value, warn=warn, _first_call=False)
        return
    elif isinstance(msg, repeated_scalar_container):
        # Only iterating over and validating these elements to try to catch any
        # base-case types that I wasn't accounting for.
        for value in msg:
            validate_protobuf(value, warn=warn, _first_call=False)
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
        validate_protobuf(value, warn=warn, _first_call=False)


def validate_flow_setpoints_sequence(flow_setpoints_sequence, warn=True):

    all_seen_ports = set()
    all_seen_addresses = set()

    trial_setpoint_sums = set()

    for trial_setpoints in flow_setpoints_sequence:

        curr_trial_setpoint_sum = 0.0
        for one_controller_setpoint in trial_setpoints:

            # TODO am i actually setting flows in terms of sccm (thats a unit of mass
            # flow, right?) does it depend on hardware settings? as i commented
            # elsewhere, is it possible to set flows in volumetric units?
            if 'sccm' not in one_controller_setpoint:
                raise ValueError('sccm must be set for each trial, for each flow '
                    'controller'
                )

            if ('port' not in one_controller_setpoint and
                'address' not in one_controller_setpoint):
                raise ValueError('port or address must be set for each trial, for each'
                    'flow controller. always use one or the other.'
                )

            if 'port' in one_controller_setpoint:
                port = one_controller_setpoint['port']
                all_seen_ports.add(port)
                if type(port) is not str:
                    raise ValueError(f'ports in {flow_setpoints_sequence_key} '
                        'must be of type str'
                    )

            if 'address' in one_controller_setpoint:
                address = one_controller_setpoint['address']
                all_seen_addresses.add(address)
                if type(address) is not str:
                    raise ValueError(f'addresses in {flow_setpoints_sequence_key} '
                        'must be of type str'
                    )

            try:
                setpoint = float(one_controller_setpoint['sccm'])
            except ValueError:
                raise ValueError(f'sccm values in {flow_setpoints_sequence_key}'
                    ' must be numeric'
                )

            if setpoint < 0:
                raise ValueError(f'sccm values in {flow_setpoints_sequence_key}'
                    ' must be non-negative'
                )
            curr_trial_setpoint_sum += setpoint

        trial_setpoint_sums.add(curr_trial_setpoint_sum)

    if len(all_seen_ports) > 0 and len(all_seen_addresses) > 0:
        raise ValueError('only use either ports or addresses to reference flow '
            'controllers'
        )

    # False if using ports.
    using_addresses = len(all_seen_addresses) > 0

    if warn and len(trial_setpoint_sums) > 1:
        warnings.warn('setpoint sum is not the same on each trial! '
            f'unique sums: {trial_setpoint_sums}'
        )

    # For now, we are going to require that each port/address that is referenced is
    # referenced in the list for each trial, for simplicity of downstream code.
    for trial_setpoints in flow_setpoints_sequence:

        if using_addresses:
            trial_addresses = {x['address'] for x in trial_setpoints}
            if trial_addresses != all_seen_addresses:
                missing = all_seen_addresses - trial_addresses
                raise ValueError('each address must be referenced in each element '
                    f'of flow_setpoints_sequence. current trial missing: {missing}'
                )
        else:
            trial_ports = {x['port'] for x in trial_setpoints}
            if trial_ports != all_seen_ports:
                missing = all_seen_ports - trial_ports
                raise ValueError('each port must be referenced in each element '
                    f'of flow_setpoints_sequence. current trial missing: {missing}'
                )


def validate_config_dict(config_dict, warn=True):
    """Raises ValueError if config_dict has some invalid data.

    Doesn't check firmware settings in the `AllRequiredData` object, which is
    currently handled by `validate`.
    """
    # there's other stuff that could be checked here, but just dealing w/ some
    # of the possible config problems when adding flow controller support for
    # now
    if flow_setpoints_sequence_key in config_dict:
        # TODO test this w/ actual valid input to enable follow_hardware_timing
        settings = config_dict['settings']
        if settings.get('follow_hardware_timing', False):
            # (because we don't know how long the trials will be in this case,
            # and we don't know when they will happen, so we can't change flow
            # in advance)
            raise ValueError('flow setpoints sequence can not be used in '
                'follow_hardware_timing case'
            )
        #

        flow_setpoints_sequence = config_dict[flow_setpoints_sequence_key]

        # should be equal to len(all_required_data.pin_sequence.pin_groups)
        # which was derived from the data in config_dict
        pin_groups = config_dict['pin_sequence']['pin_groups']

        f_len = len(flow_setpoints_sequence)
        p_len = len(pin_groups)
        if f_len != p_len:
            raise ValueError(f'len({flow_setpoints_sequence_key}) != len('
                f'pin_sequence.pin_groups) ({f_len} != {p_len})'
            )

        validate_flow_setpoints_sequence(flow_setpoints_sequence, warn=warn)

