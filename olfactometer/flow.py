"""
Functions for controlling flows via Alicat mass flow controllers (MFCs).
"""

import atexit
import math
from pprint import pprint

from alicat import FlowController

from olfactometer.generators import common


flow_setpoints_sequence_key = 'flow_setpoints_sequence'

# TODO maybe add optional address (both kwargs, but require one, like [i think]
# in alicat code?)
_port2initial_get_output = dict()
def open_alicat_controller(port, save_initial_setpoints=True,
    check_gas_is_air=True, _skip_read_check=False, verbose=False):
    """Returns opened alicat.FlowController for controller on input port.

    Also registers atexit function to close connection and restore previous setpoints.

    Unless save_initial_setpoints and check_gas_is_air are both False, queries the
    controller to set corresponding entry in `_port2initial_get_output`.
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
    def get_mfc_id(key_prefix):
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

    carrier_mfc_id = get_mfc_id('carrier_flow_controller_')
    odor_mfc_ids = sorted([get_mfc_id(p) for p in odor_mfc_prefixes])

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

