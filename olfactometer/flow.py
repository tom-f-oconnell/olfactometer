"""
Functions for controlling flows via Alicat mass flow controllers (MFCs).
"""

import atexit
import math
from pprint import pprint

from alicat import FlowController


flow_setpoints_sequence_key = 'flow_setpoints_sequence'

# TODO maybe add optional address (both kwargs, but require one, like [i think]
# in alicat code?)
_port2initial_get_output = dict()
def open_alicat_controller(port, save_initial_setpoints=True,
    check_gas_is_air=True, _skip_read_check=False, verbose=False):
    """Returns opened alicat.FlowController for controller on input port.

    Also registers atexit function to close connection.

    Unless all kwargs are False, queries the controller to set
    corresponding entry in `_port2initial_get_output`.
    """
    if save_initial_setpoints or check_gas_is_air:
        _skip_read_check = False

    # TODO thread through expected vid/pid or other unique usb identifiers for
    # controllers / the adapters we are using to interface with them. either in
    # env vars / hardware config / both. if using vid/pid, i measured
    # vid=5296 pid=13328 for our startech 4x rs232 adapters (on downstairs 2p
    # windows 7 machine using my tom-f-oconnell/test/alicat_test.py script).

    # Raies OSError under some conditions (maybe just via pyserial?)
    c = FlowController(port=port)
    atexit.register(c.close)
    # From some earlier testing, it seemed that first sign of incorrect opening
    # was often on first read, hence the read here without (necessarily) using
    # the values later.
    if not _skip_read_check:
        # TODO why did i all of a sudden get:
        # ValueError: could not convert string to float: 'Air' here?
        # didn't happen in .get in alicat_test.py i think...
        # i did just switch flow controllers...
        # (i think it might have been because one controller is defective or
        # something. worked after disconnecting it + it has what seems to be
        # an indication of an overpressure status, despite being unplugged.)

        # Will raise OSError if fails.
        data = c.get()

        if verbose:
            print('initial data:')
            pprint(data)

        # TODO probably delete this if i add support for MFC->gas config
        # (via c.set_gas(<str>) in numat/alicat api)
        if check_gas_is_air:
            gas = data['gas']
            if gas != 'Air':
                raise RuntimeError('gas on MFC at port {port} was configured '
                    f"to '{gas}', but was expecting 'Air'"
                )

        # TODO TODO TODO TODO if need be, to minimize loss of precision, check
        # that device units are configured correctly for how we are planning on
        # sending setpoints. again, https://github.com/numat/alicat/issues/14
        # may be relevant.

        _port2initial_get_output[port] = data

    return c


# TODO maybe initialize this w/ .get() in this open fn?
# (currently just used in set_flow_setpoints)
# TODO refactor into a class if i'm gonna have ~global state like this?
_port2last_flow_rate = dict()
def open_alicat_controllers(config_dict, _skip_read_check=False, verbose=False):
    """Returns a dict of str port -> opened alicat.FlowController
    """
    flow_setpoints_sequence = config_dict[flow_setpoints_sequence_key]

    port_set = set()
    port2flows = dict()
    for trial_setpoints in flow_setpoints_sequence:
        for one_controller_setpoint in trial_setpoints:
            port = one_controller_setpoint['port']
            port_set.add(port)

            sccm = one_controller_setpoint['sccm']
            if port not in port2flows:
                port2flows[port] = [sccm]
            else:
                port2flows[port].append(sccm)

    print('Opening flow controllers:')
    port2flow_controller = dict()
    sorted_ports = sorted(list(port_set))
    for port in sorted_ports:
        print(f'- {port} ...', end='', flush=True)
        c = open_alicat_controller(port, _skip_read_check=_skip_read_check,
            verbose=verbose
        )
        port2flow_controller[port] = c
        print('done', flush=True)

    # TODO maybe put behind verbose
    print('\n[min, max] requested flows (in mL/min) for each flow controller:')
    for port in sorted_ports:
        fmin = min(port2flows[port])
        fmax = max(port2flows[port])
        print(f'- {port}: [{fmin:.1f}, {fmax:.1f}]')
    print()

    # TODO TODO somehow check all flow rates (min/max over course of sequence)
    # are within device ranges
    # TODO TODO also check resolution (may need to still have access to a
    # unparsed str copy of the variable... not sure)

    return port2flow_controller


# TODO TODO maybe store data for how long each change of a setpoint took, to
# know that they all completed in a reasonable amount of time?
# (might also take some non-negligible amount of time to stabilize after change
# of setpoint, so would probably be good to have the electrical output of each
# flow meter in thorsync, if that works on our models + alongside serial usage)
_called_set_flow_setpoints = False
def set_flow_setpoints(port2flow_controller, trial_setpoints,
    check_set_flows=False, verbose=False):

    global _called_set_flow_setpoints
    if not _called_set_flow_setpoints:
        atexit.register(restore_initial_setpoints, port2flow_controller,
            verbose=verbose
        )
        _called_set_flow_setpoints = True

    if verbose:
        print('setting trial flow controller setpoints:')
    else:
        print('flows (mL/min): ', end='')
        short_strs = []

    erred = False
    for one_controller_setpoint in trial_setpoints:
        port = one_controller_setpoint['port']
        sccm = one_controller_setpoint['sccm']

        unchanged = False
        if port in _port2last_flow_rate:
            last_sccm = _port2last_flow_rate[port]
            if last_sccm == sccm:
                unchanged = True

        if verbose:
            # TODO TODO change float formatting to reflect achievable precision
            # (including both hardware and any loss of precision limitations of
            # numat/alicat api)
            cstr = f'- {port}: {sccm:.1f} mL/min'
            if unchanged:
                cstr += ' (unchanged)'
            print(cstr)
        else:
            # TODO maybe still show at least .1f if any inputs have that kind
            # of precision?
            short_strs.append(f'{port}={sccm:.0f}')

        if unchanged:
            continue

        c = port2flow_controller[port]
        # TODO TODO TODO convert units + make sure i'm calling in the way
        # to achieve the best precision
        # see: https://github.com/numat/alicat/issues/14
        # From numat/alicat docstring (which might not be infallible):
        # "in units specified at time of purchase"
        sccm = float(sccm)
        try:
            c.set_flow_rate(sccm)
        except OSError as e:
            # TODO also print full traceback
            print(e)
            erred = True
            continue

        _port2last_flow_rate[port] = sccm

        if check_set_flows:
            data = c.get()

            # TODO may need to change tolerance args because of precision limits
            if not math.isclose(data['setpoint'], sccm):
                raise RuntimeError('commanded setpoint was not reflected '
                    f'in subsequent query. set: {sccm:.1f}, got: '
                    f'{data["set_point"]:.1f}'
                )

            if verbose:
                print('setpoint check OK')

    if not verbose:
        print(','.join(short_strs))

    if erred:
        raise OSError('failed to change setpoint on one or more flow '
            'controllers'
        )


# TODO if i ever set gas (or anything beyond set points) rename to
# restore_initial_flowcontroller_settings or something + also restore those
# things here
def restore_initial_setpoints(port2flow_controller, verbose=False):
    """Restores setpoints populated on opening each controller.
    """
    if verbose:
        print('Restoring initial flow controller set points:')

    for port, c in port2flow_controller.items():
        initial_setpoint = _port2initial_get_output[port]['setpoint']

        if verbose:
            # maybe isn't always really mL/min across all our MFCs...
            print(f'- {port}: {initial_setpoint:.1f} mL/min')

        c.set_flow_rate(initial_setpoint)

