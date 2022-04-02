"""
Functions for controlling flows via Alicat mass flow controllers (MFCs).
"""

import atexit
import math
from pprint import pprint

from alicat import FlowController
from serial.tools import list_ports

from olfactometer import _DEBUG
from olfactometer.generators import common


flow_setpoints_sequence_key = 'flow_setpoints_sequence'
using_addresses = None

safe_usb_ids_key = 'safe_usb_ids_to_check_for_mfcs'
# TODO specify whether they should be integer or str (former i think?)
#
# Must be set to iterable of tuples of (vendor ID, product ID) (for USB-to-serial
# adapters that you know *only* could have MFCs or *NON-sensitive* equipment).
#
# We only search whitelisted interfaces so we don't send serial data to other equipment
# (like the expensive laser) which could do something unexpected given the same input.
# TODO update hardware config validation to also check these are in the right format
# (and that they are in the range for USB ids too, ideally)
# NOTE: currently this is set in olf (but only if generators used...)
safe_usb_ids_to_check_for_mfcs = None

_address2port = dict()
_whitelist_ports = set()
# TODO cache com port each was found on last to user data, and check those first,
# to save time
def find_port_for_controller_address(address, unsafe=False):

    if safe_usb_ids_to_check_for_mfcs is None and not unsafe:
        raise ValueError('flow.safe_usb_ids_to_check_for_mfcs must be set in order to '
            'reference flow controllers by address (rather than by port). adding a list'
            " like 'safe_usb_ids_to_check_for_mfcs: [[<vendor ID #1>, <product ID #1>]'"
            ", ... ]' to your hardware config YAML, and this should be set for you"
        )

    if address in _address2port:
        return _address2port[address]

    if _DEBUG:
        print(f'searching for MFC with address {address}')

    for port in sorted(list_ports.comports()):

        if port.device in _address2port.values():
            continue

        if _DEBUG:
            print(f'trying port {port.device}')

        if not (port.vid, port.pid) in safe_usb_ids_to_check_for_mfcs:
            if _DEBUG:
                print(f'vid={port.vid} pid={port.pid} not in whitelist. skipping.')

            continue

        _whitelist_ports.add(port.device)

        if not FlowController.is_connected(port.device, address=address):
            continue

        if _DEBUG:
            print('found')

        _address2port[address] = port.device
        return port.device

    raise IOError(f'no (whitelisted) port found for MFC address {address}')


_mfc_id2initial_get_output = dict()
def open_alicat_controller(mfc_id=None, *, port=None, address=None,
    save_initial_setpoints=True, check_gas_is_air=True, _skip_read_check=False,
    verbose=False):
    """Returns opened alicat.FlowController for controller on input port/address.

    Also registers atexit function to close connection and restore previous setpoints.

    Unless save_initial_setpoints and check_gas_is_air are both False, queries the
    controller to set corresponding entry in `_mfc_id2initial_get_output`.
    """
    if save_initial_setpoints or check_gas_is_air:
        _skip_read_check = False

    if sum([x is not None for x in [mfc_id, port, address]]) != 1:
        raise ValueError('specify exactly one of mfc_id, port, or address. mfc_id '
            'will select between port/address behavior based on flow.using_addresses'
        )

    if mfc_id is not None:
        if using_addresses is None:
            raise RuntimeError('flow.using_addresses must be set True/False')

        _using_addresses = using_addresses
        if _using_addresses:
            address = mfc_id
        else:
            port = mfc_id

    elif port is None:
        _using_addresses = True
    else:
        _using_addresses = False

    # TODO thread through expected vid/pid or other unique usb identifiers for
    # controllers / the adapters we are using to interface with them. either in
    # env vars / hardware config / both. if using vid/pid, i measured
    # vid=5296 pid=13328 for our startech 4x rs232 adapters (on downstairs 2p
    # windows 7 machine using my tom-f-oconnell/test/alicat_test.py script).

    # Raises OSError under some conditions (maybe just via pyserial?)
    if _using_addresses:
        port = find_port_for_controller_address(address)
        c = FlowController(port=port, address=address)
    else:
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
                id_str = address if using_addresses else f'on {port}'
                raise RuntimeError(f'gas on MFC {id_str} was configured '
                    f"to '{gas}', but was expecting 'Air'"
                )

        # TODO TODO TODO TODO if need be, to minimize loss of precision, check
        # that device units are configured correctly for how we are planning on
        # sending setpoints. again, https://github.com/numat/alicat/issues/14
        # may be relevant.

        _mfc_id2initial_get_output[mfc_id] = data

    return c


def get_mfc_id(mfc_trial_dict):
    """Takes dict w/ config for one MFC at one trial to either port/address.

    Requires that using_addresses is either True/False (set by open_alicat_controllers)
    """
    if using_addresses is None:
        raise RuntimeError('flow.using_addresses must be set True/False')

    elif using_addresses:
        return mfc_trial_dict['address']
    else:
        return mfc_trial_dict['port']


def _are_flows_constant(mfc_id2flows):
    """True if each MFC only has one flow for the whole experiment, False otherwise.
    """
    for one_mfc_trial_flows in mfc_id2flows.values():
        if not all([x == one_mfc_trial_flows[0] for x in one_mfc_trial_flows]):
            return False
    return True


# TODO refactor into a class if i'm gonna have ~global state like this?
_mfc_id2last_flow_rate = dict()
def open_alicat_controllers(config_dict, _skip_read_check=False, verbose=False):
    """Returns a dict of str port/address -> opened alicat.FlowController
    """
    global using_addresses

    flow_setpoints_sequence = config_dict[flow_setpoints_sequence_key]

    # olf.run will have called validate_flow_setpoints_sequence on the input already
    # (via validate_config_dict), so we can assume that it is either all addresses or
    # all ports, and that all trials have data for all MFCs (among other things).
    using_addresses = 'address' in flow_setpoints_sequence[0][0]

    mfc_id_set = set()
    mfc_id2flows = dict()
    for trial_setpoints in flow_setpoints_sequence:
        for one_controller_setpoint in trial_setpoints:
            mfc_id = get_mfc_id(one_controller_setpoint)
            mfc_id_set.add(mfc_id)

            sccm = one_controller_setpoint['sccm']
            if mfc_id not in mfc_id2flows:
                mfc_id2flows[mfc_id] = [sccm]
            else:
                mfc_id2flows[mfc_id].append(sccm)

    print('Opening flow controllers:')
    mfc_id2flow_controller = dict()
    sorted_mfc_ids = sorted(list(mfc_id_set))
    for mfc_id in sorted_mfc_ids:
        print(f'- {mfc_id} ...', end='', flush=True)
        c = open_alicat_controller(mfc_id, _skip_read_check=_skip_read_check,
            verbose=verbose
        )
        mfc_id2flow_controller[mfc_id] = c
        print('done', flush=True)

    are_flows_constant = _are_flows_constant(mfc_id2flows)
    if not are_flows_constant:
        # TODO maybe put behind verbose
        print('\n[min, max] requested flows (in mL/min) for each flow controller:')
        for mfc_id in sorted_mfc_ids:
            fmin = min(mfc_id2flows[mfc_id])
            fmax = max(mfc_id2flows[mfc_id])
            print(f'- {mfc_id}: [{fmin:.1f}, {fmax:.1f}]')
        print()

    # TODO TODO somehow check all flow rates (min/max over course of sequence)
    # are within device ranges
    # TODO TODO also check resolution (may need to still have access to a
    # unparsed str copy of the variable... not sure)

    if _DEBUG:
        whitelist_ports_without_mfcs = \
            set(_whitelist_ports) - set(_address2port.values())

        print('ports with whitelisted (vid, pid) pairs WITHOUT a flow controller with '
            'one of the requested addresses:'
        )
        pprint(whitelist_ports_without_mfcs)

    # TODO probably refactor opening logic to not have this function also doing double
    # duty in this way that doesn't make too much sense
    return mfc_id2flow_controller, are_flows_constant


# TODO TODO maybe store data for how long each change of a setpoint took, to
# know that they all completed in a reasonable amount of time?
# (might also take some non-negligible amount of time to stabilize after change
# of setpoint, so would probably be good to have the electrical output of each
# flow meter in thorsync, if that works on our models + alongside serial usage)
_called_set_flow_setpoints = False
def set_flow_setpoints(mfc_id2flow_controller, trial_setpoints,
    check_set_flows=False, silent=False, verbose=False):
    """
    Args:
        silent: if True, overrides verbose and nothing is printed at all
    """

    global _called_set_flow_setpoints
    if not _called_set_flow_setpoints:
        atexit.register(restore_initial_setpoints, mfc_id2flow_controller,
            verbose=verbose
        )
        _called_set_flow_setpoints = True

    if not silent:
        if verbose:
            print('setting trial flow controller setpoints:')
        else:
            print('flows (mL/min): ', end='')
            short_strs = []

    erred = False
    for one_controller_setpoint in trial_setpoints:

        mfc_id = get_mfc_id(one_controller_setpoint)
        sccm = one_controller_setpoint['sccm']

        unchanged = False
        if mfc_id in _mfc_id2last_flow_rate:
            last_sccm = _mfc_id2last_flow_rate[mfc_id]
            if last_sccm == sccm:
                unchanged = True

        if not silent:
            if verbose:
                # TODO TODO change float formatting to reflect achievable precision
                # (including both hardware and any loss of precision limitations of
                # numat/alicat api)
                cstr = f'- {mfc_id}: {sccm:.1f} mL/min'
                if unchanged:
                    cstr += ' (unchanged)'
                print(cstr)
            else:
                # TODO maybe still show at least .1f if any inputs have that kind
                # of precision?
                short_strs.append(f'{mfc_id}={sccm:.0f}')

        if unchanged:
            continue

        c = mfc_id2flow_controller[mfc_id]
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

        _mfc_id2last_flow_rate[mfc_id] = sccm

        # TODO TODO TODO shouldn't i need to wait some amount of time for it to achieve
        # the setpoint? what value is appropriate?
        if check_set_flows:
            data = c.get()

            # TODO may need to change tolerance args because of precision limits
            if not math.isclose(data['setpoint'], sccm):
                raise RuntimeError('commanded setpoint was not reflected '
                    f'in subsequent query. set: {sccm:.1f}, got: '
                    f'{data["set_point"]:.1f}'
                )

            if not silent and verbose:
                print('setpoint check OK')

    if not silent and not verbose:
        print(','.join(short_strs))

    if erred:
        raise OSError('failed to change setpoint on one or more flow '
            'controllers'
        )


# TODO if i ever set gas (or anything beyond set points) rename to
# restore_initial_flowcontroller_settings or something + also restore those
# things here
def restore_initial_setpoints(mfc_id2flow_controller, verbose=False):
    """Restores setpoints populated on opening each controller.
    """
    if verbose:
        print('Restoring initial flow controller set points:')

    for mfc_id, c in mfc_id2flow_controller.items():
        initial_setpoint = _mfc_id2initial_get_output[mfc_id]['setpoint']

        if verbose:
            # maybe isn't always really mL/min across all our MFCs...
            print(f'- {mfc_id}: {initial_setpoint:.1f} mL/min')

        c.set_flow_rate(initial_setpoint)


total_flow_key = 'total_flow_ml_per_min'
odor_flow_key = 'odor_flow_ml_per_min'

class FlowHardwareNotConfiguredError(Exception):
    pass

def generate_flow_setpoint_sequence(input_config_dict, hardware_dict, generated_config):

    def _n_trials(config_dict):
        return len(config_dict['pin_sequence']['pin_groups'])

    # Already has what we would add
    if flow_setpoints_sequence_key in generated_config:
        return generated_config

    # No experiment-wide flow specified
    if not ((total_flow_key in input_config_dict) or
        (odor_flow_key in input_config_dict)):

        return generated_config

    if total_flow_key not in input_config_dict:
        raise ValueError(f'{total_flow_key} must be set if {odor_flow_key} is')

    if odor_flow_key not in input_config_dict:
        raise ValueError(f'{odor_flow_key} must be set if {total_flow_key} is')

    _, _, is_single_manifold = common.get_available_pins(hardware_dict)

    # TODO TODO TODO either rename key to indicate units are (mass, right?) sccm not
    # volumetric ml/min, or convert / interact w/ alicat appropriately
    odor_flow_sccm = input_config_dict[odor_flow_key]
    total_flow_sccm = input_config_dict[total_flow_key]

    if is_single_manifold:
        odor_mfc_prefixes = ('odor_flow_controller_',)
        carrier_flow_sccm = total_flow_sccm - odor_flow_sccm

    # Then it must be a dual manifold, given what my hardware config options currently
    # allow. No higher number of manifolds is currently supported.
    else:
        odor_mfc_prefixes = (f'group{n}_flow_controller_' for n in (1, 2))
        carrier_flow_sccm = total_flow_sccm - 2 * odor_flow_sccm

    # TODO include validation for these in hardware validation (currently in
    # generators.common), including:
    # - making sure if any are specified, all are, and either for a single or dual
    #   manifold setup
    # - forbidding mismatch of ports/addresses
    # - warning if using ports rather than addresses
    # TODO refactor
    using_addresses = None
    def _get_mfc_id(key_prefix):
        nonlocal using_addresses
        already_found = False
        mfc_id = None
        for id_type in ('address', 'port'):

            key = f'{key_prefix}{id_type}'
            if key in hardware_dict:
                assert not already_found, 'multiple flow controller ID types specified'
                already_found = True
                if id_type == 'address':
                    assert using_addresses in (None, True), 'multiple MFC id types!'
                    using_addresses = True
                else:
                    assert using_addresses in (None, False), 'multiple MFC id types!'
                    using_addresses = False

                mfc_id = hardware_dict[key]

        if mfc_id is None:
            raise FlowHardwareNotConfiguredError('flow controller ID not found at '
                f'either {key_prefix}[address|port] in hardware config, but flows '
                'setpoints were configured!'
            )

        return mfc_id

    carrier_mfc_id = _get_mfc_id('carrier_flow_controller_')
    odor_mfc_ids = sorted([_get_mfc_id(p) for p in odor_mfc_prefixes])

    assert using_addresses is not None

    id_type = 'address' if using_addresses else 'port'

    def one_experiment_config_with_flow_sequence(config_dict):
        n_trials = _n_trials(config_dict)

        flow_setpoints_sequence = [
            [{id_type: carrier_mfc_id, 'sccm': carrier_flow_sccm}] +
            [{id_type: mfc_id, 'sccm': odor_flow_sccm} for mfc_id in odor_mfc_ids]
            for _ in range(n_trials)
        ]
        config_dict = config_dict.copy()
        config_dict[flow_setpoints_sequence_key] = flow_setpoints_sequence
        return config_dict

    # TODO should probably refactor this ~squeezing of config, or just always have
    # things as a sequence, sometimes just length 1

    # Config only represents one experiment, not a sequence of them
    if isinstance(generated_config, dict):
        return one_experiment_config_with_flow_sequence(generated_config)

    # Should be an iterable containing configurations for a sequence of experiments
    else:
        return [one_experiment_config_with_flow_sequence(d) for d in generated_config]

