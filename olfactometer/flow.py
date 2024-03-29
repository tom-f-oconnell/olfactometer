"""
Functions for controlling flows via Alicat mass flow controllers (MFCs).
"""

import atexit
import math
from pprint import pprint
import time
import warnings

from alicat import FlowController
from serial.tools import list_ports
import yaml

from olfactometer import util, _DEBUG
from olfactometer.generators import common


# TODO use alicat mock.py contents to allow testing (if _DEBUG) flow stuff w/o flow
# controllers connected

# Hardware config doesn't specify ports/addresses for flow controllers.
class FlowHardwareNotConfigured(Exception):
    pass

# Configured but not found at specified port/address.
#
# TODO rename to something like PortNotFoundForAddress?
# (or actually use the error in cases where they can't be opened based on ports too)
class FlowHardwareNotFound(IOError):
    pass

require_flow_controllers_key = 'require_flow_controllers'
flow_setpoints_sequence_key = 'flow_setpoints_sequence'

# TODO specify whether they should be integer or str (former i think?)
#
# Must be set to iterable of tuples of (vendor ID, product ID) (for USB-to-serial
# adapters that you know *only* could have MFCs or *NON-sensitive* equipment).
#
# We only search whitelisted interfaces so we don't send serial data to other equipment
# (like the expensive laser) which could do something unexpected given the same input.
# TODO update hardware config validation to also check these are in the right format
# (and that they are in the range for USB ids too, ideally)
safe_usb_ids_key = 'safe_usb_ids_to_check_for_mfcs'

# This cost is incurrent 6 times in checking whether a FlowMeter is connected
# (two <flowmeter>.get() calls, w/ currently-unchangeable 2 retries for each)
# Default is 1s. 0.1s is about twice what I've seen a single get call take (in some
# limited testing).
# NOTE: requires my fork of alicat library to be able to pass this to
# FlowMeter.__init__. This dependency should be handled by setup.py.
read_timeout_s = 0.1

_address2port = dict()
_whitelist_ports = set()
def find_port_for_controller_address(address, safe_usb_ids_to_check_for_mfcs=None,
    unsafe=False, _last_port=None):
    """
    Raises FlowHardwareNotFound if no flow controller can be found with this address.
    """
    # TODO just raise FlowHardwareNotConfigured probably (as if ID for a manifold's flow
    # controller was left out of hardware config)
    if safe_usb_ids_to_check_for_mfcs is None and not unsafe:
        # TODO mention that unsafe=True can be set? or just delete if not?
        # if former, thread thru fns that call this...
        raise ValueError('flow.safe_usb_ids_to_check_for_mfcs must be set in order to '
            'reference flow controllers by address (rather than by port). adding a list'
            f" like '{safe_usb_ids_key}: [[<vendor ID #1>, <product ID #1>]'"
            ", ... ]' to your hardware config YAML, and this should be set for you"
        )

    if address in _address2port:
        return _address2port[address]

    if _DEBUG:
        print(f'searching for MFC with address {address}')

    ports = sorted(list_ports.comports())

    if _last_port is not None:

        last_port_obj = None
        other_port_objs = []
        for p in ports:
            if p.device == _last_port:
                last_port_obj = p
            else:
                other_port_objs.append(p)

        if last_port_obj is not None:
            # Just re-ordering to try the last known port first, if it's provided.
            ports = [last_port_obj] + other_port_objs

    for port in ports:
        if port.device in _address2port.values():
            continue

        if _DEBUG:
            print(f'trying port {port.device}')

        if not (port.vid, port.pid) in safe_usb_ids_to_check_for_mfcs:
            if _DEBUG:
                print(f'vid={port.vid} pid={port.pid} not in whitelist. skipping.')

            continue

        _whitelist_ports.add(port.device)

        # NOTE: this also requires my alicat fork for the timeout kwarg
        if not FlowController.is_connected(port.device, address=address,
            timeout=read_timeout_s):

            continue

        if _DEBUG:
            print('found')

        _address2port[address] = port.device
        return port.device

    raise FlowHardwareNotFound(f'no (whitelisted) port found for MFC address {address}')


_mfc_id2initial_get_output = dict()
def open_alicat_controller(mfc_id=None, *, port=None, address=None, id_type=None,
    save_initial_setpoints=True, check_gas_is_air=True, verbose=False,
    safe_usb_ids_to_check_for_mfcs=None, _skip_read_check=False, _last_port=None
    ) -> FlowController:
    """Returns opened alicat.FlowController for controller on input port/address.

    Also registers atexit function to close connection and restore previous setpoints.

    Unless save_initial_setpoints and check_gas_is_air are both False, queries the
    controller to set corresponding entry in `_mfc_id2initial_get_output`.

    Raises:
        FlowHardwareNotFound (see `find_port_for_controller_address`)
    """
    if save_initial_setpoints or check_gas_is_air:
        _skip_read_check = False

    if sum([x is not None for x in [mfc_id, port, address]]) != 1:
        raise ValueError('specify exactly one of mfc_id, port, or address. mfc_id '
            'will select between port/address behavior based on id_type'
        )

    if mfc_id is not None:
        if id_type == 'address':
            address = mfc_id

        elif id_type == 'port':
            port = mfc_id
        else:
            raise ValueError("id_type must be either 'address' or 'port' when mfc_id "
                "is used (rather than address or port keyword arguments)"
            )

    elif address is not None:
        assert id_type is None
        id_type = 'address'
        mfc_id = address

    elif port is not None:
        assert id_type is None
        id_type = 'port'
        mfc_id = port

    # Raises OSError under some conditions (maybe just via pyserial?)
    if id_type == 'address':
        try:
            port = find_port_for_controller_address(address,
                safe_usb_ids_to_check_for_mfcs=safe_usb_ids_to_check_for_mfcs,
                _last_port=_last_port
            )
        except FlowHardwareNotFound:
            raise

        # TODO also handle an IOError here? similar questions to below. or are we
        # essentially guaranteed to be able to open it, having passed the
        # find_port_for_controller_address call above?
        c = FlowController(port=port, address=address, timeout=read_timeout_s)

    elif id_type == 'port':
        # TODO TODO what happens if something else is connected to this port?
        # what about if nothing is? can have failure of either map to the same
        # FlowHardwareNotFound error? or should i have a separate error for that?
        # maybe i should only support addresses rather than ports, esp if i can't tell
        # if things are connected in that case?
        c = FlowController(port=port, timeout=read_timeout_s)

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
                id_str = address if id_type == 'address' else f'on {port}'
                raise RuntimeError(f'gas on MFC {id_str} was configured '
                    f"to '{gas}', but was expecting 'Air'"
                )

        # TODO TODO TODO if need be, to minimize loss of precision, check
        # that device units are configured correctly for how we are planning on
        # sending setpoints. again, https://github.com/numat/alicat/issues/14
        # may be relevant.

        _mfc_id2initial_get_output[mfc_id] = data

    return c


def _are_flows_constant(mfc_id2flows):
    """True if each MFC only has one flow for the whole experiment, False otherwise.
    """
    for one_mfc_trial_flows in mfc_id2flows.values():
        if not all([x == one_mfc_trial_flows[0] for x in one_mfc_trial_flows]):
            return False
    return True


def _last_address2port_cache_fname(mkdir=False):
    return util.user_data_dir(mkdir=mkdir) / 'last_address2port.yaml'


def handle_flow_control_requirement(config_dict, err, warn_msg: str) -> None:
    require_flow_controllers = config_dict.get(require_flow_controllers_key)
    assert require_flow_controllers in (True, False, None)

    if require_flow_controllers == True:
        # TODO add bit to error message saying it's because
        # require_flow_controllers=True that it is an error rather than being
        # ignored/warning
        raise err

    elif require_flow_controllers is None:
        # TODO replace w/ logging.warning (here and all other warnings calls)?
        warnings.warn(f'{str(err)}\n{warn_msg}\n(set require_flow_controllers=False '
            'to silence)'
        )

    elif require_flow_controllers == False:
        pass


def open_alicat_controllers(config_dict, _skip_read_check=False, verbose=False):
    """Returns a dict of str port/address -> opened alicat.FlowController

    Raises:
        FlowHardwareNotFound (see `find_port_for_controller_address`)
    """
    safe_usb_ids_to_check_for_mfcs = None
    # TODO require this is here? thread unsafe= kwarg thru (from inner find_* call)?
    if safe_usb_ids_key in config_dict:
        safe_vid_pid_pairs = config_dict[safe_usb_ids_key]

        # TODO move to hardware config validation (or just general flow validation? now
        # i want to also allow these in generator output YAMLs...)
        for pair in safe_vid_pid_pairs:
            assert len(pair) == 2
            for x in pair:
                assert type(x) is int

        safe_usb_ids_to_check_for_mfcs = {tuple(p) for p in safe_vid_pid_pairs}

        if _DEBUG:
            # TODO just skip vid=None, pid=None (seems to exist for /dev/ttyS0 on my
            # linux install, at least)
            print('USB (vid, pid) whitelist, to allow searching for MFCs:')
            pprint(safe_usb_ids_to_check_for_mfcs)

    # TODO move into find_port_for_controller_address (set a "private" global cache
    # var)?
    cache_fname = _last_address2port_cache_fname(mkdir=True)
    last_address2port = None
    if cache_fname.exists():
        with open(cache_fname, 'r') as f:
            last_address2port = yaml.safe_load(f)
            assert type(last_address2port) is dict

        if _DEBUG:
            print(f'address->port read from cache at {cache_fname}:')
            pprint(last_address2port)

    flow_setpoints_sequence = config_dict[flow_setpoints_sequence_key]

    # olf.run will have called validate_flow_setpoints_sequence on the input already
    # (via validate_config_dict), so we can assume that it is either all addresses or
    # all ports, and that all trials have data for all MFCs (among other things).
    first_flow_setpoint_dict = flow_setpoints_sequence[0][0]

    if 'address' in first_flow_setpoint_dict:
        id_type = 'address'

    elif 'port' in first_flow_setpoint_dict:
        id_type = 'port'
    else:
        raise ValueError("first flow controller settings missing 'address' or 'port'")

    mfc_id_set = set()
    mfc_id2flows = dict()
    for trial_setpoints in flow_setpoints_sequence:
        for one_controller_setpoint in trial_setpoints:
            mfc_id = one_controller_setpoint[id_type]
            mfc_id_set.add(mfc_id)

            sccm = one_controller_setpoint['sccm']
            if mfc_id not in mfc_id2flows:
                mfc_id2flows[mfc_id] = [sccm]
            else:
                mfc_id2flows[mfc_id].append(sccm)

    # Checking we can find the ports of all flow controller addresses before we try
    # opening any, so that we can decide not to err if require_flow_controllers=False
    if id_type == 'address':
        for address in mfc_id_set:
            last_port = None
            if last_address2port is not None:
                last_port = last_address2port[address]

            try:
                port = find_port_for_controller_address(address,
                    safe_usb_ids_to_check_for_mfcs=safe_usb_ids_to_check_for_mfcs,
                    _last_port=last_port
                )

            except FlowHardwareNotFound:
                raise

    if _DEBUG:
        start_s = time.time()

    print('Opening flow controllers:')
    mfc_id2flow_controller = dict()
    sorted_mfc_ids = sorted(list(mfc_id_set))

    for mfc_id in sorted_mfc_ids:
        last_port = None
        # TODO rename to address2last_port (and elsewhere)?
        if id_type == 'address' and last_address2port is not None:
            last_port = last_address2port[mfc_id]

        print(f'- {mfc_id} ...', end='', flush=True)

        try:
            c = open_alicat_controller(mfc_id, id_type=id_type, verbose=verbose,
                safe_usb_ids_to_check_for_mfcs=safe_usb_ids_to_check_for_mfcs,
                _skip_read_check=_skip_read_check, _last_port=last_port
            )

        # TODO TODO if i end up using a different error type when unable to open/find
        # MFCs, in the case where id_type='port', make sure to handle that error too
        except FlowHardwareNotFound:
            print()
            # (relying on atexit close calls established in open_alicat_controller to
            # close any controllers already opened successfully)
            raise

        mfc_id2flow_controller[mfc_id] = c
        print('done', flush=True)

    with open(cache_fname, 'w') as f:
        # _address2port populated in the open_alicat_controller calls above
        yaml.safe_dump(_address2port, f)

    if _DEBUG:
        took_s = time.time() - start_s
        print(f'opening flow controllers took {took_s:.2f}s')

        whitelist_ports_without_mfcs = \
            set(_whitelist_ports) - set(_address2port.values())

        print('ports with whitelisted (vid, pid) pairs WITHOUT a flow controller with '
            'one of the requested addresses:'
        )
        pprint(whitelist_ports_without_mfcs)

    # TODO factor out
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

    # TODO TODO refactor opening logic to not have this function also doing double
    # duty in this way that doesn't make too much sense
    return mfc_id2flow_controller, are_flows_constant


# TODO TODO maybe store data for how long each change of a setpoint took, to
# know that they all completed in a reasonable amount of time?
# (might also take some non-negligible amount of time to stabilize after change
# of setpoint, so would probably be good to have the electrical output of each
# flow meter in thorsync, if that works on our models + alongside serial usage)
_called_set_flow_setpoints = False
_mfc_id2last_flow_rate = dict()
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

    id_type = None
    erred = False
    for one_controller_setpoint in trial_setpoints:

        if id_type is None:
            if 'address' in one_controller_setpoint:
                id_type = 'address'
            elif 'port' in one_controller_setpoint:
                id_type = 'port'

        assert id_type is not None,  'prior validation should have caught'

        mfc_id = one_controller_setpoint[id_type]
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

        # TODO TODO shouldn't i need to wait some amount of time for it to achieve the
        # setpoint? what value is appropriate?
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

def generate_flow_setpoint_sequence(input_config_dict, hardware_dict, generated_config):

    # used to just return input here, but trying to generate this twice should indicate
    # code issue
    assert flow_setpoints_sequence_key not in generated_config, (
        'trying to generate flow config twice'
    )

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
    _using_addresses = None
    def _get_mfc_id(key_prefix):
        nonlocal _using_addresses
        already_found = False
        mfc_id = None
        for id_type in ('address', 'port'):

            key = f'{key_prefix}{id_type}'
            if key in hardware_dict:
                assert not already_found, 'multiple flow controller ID types specified'
                already_found = True
                if id_type == 'address':
                    assert _using_addresses != False, 'multiple MFC id types!'
                    _using_addresses = True
                else:
                    assert _using_addresses != True, 'multiple MFC id types!'
                    _using_addresses = False

                mfc_id = hardware_dict[key]

        if mfc_id is None:
            # TODO mention path to hardware config? i suppose i don't have access to
            # that here...
            # TODO mention which group it should be associated with (or at least show
            # how keys should be named?)
            raise FlowHardwareNotConfigured('flow controller ID not found at either '
                f'{key_prefix}[address|port] in hardware config, but flow setpoints '
                'were configured!'
            )

        return mfc_id

    require_flow_controllers = input_config_dict.get(require_flow_controllers_key)

    carrier_mfc_id = _get_mfc_id('carrier_flow_controller_')
    odor_mfc_ids = sorted([_get_mfc_id(p) for p in odor_mfc_prefixes])

    # _using_addresses only defined after all the _get_mfc_id calls in previous 2 lines
    if _using_addresses:
        if safe_usb_ids_key not in hardware_dict:
            # TODO could also thread unsafe= thru and mention that option, but might
            # also want to unsupport that...
            raise FlowHardwareNotConfigured('flow controllers referenced by addresses '
                '(the IDs set in the physical Alicat config; rather than raw ports), '
                f'but {safe_usb_ids_key} not in hardware config YAML. will not search '
                'ports without this specified!'
            )

    assert _using_addresses is not None
    id_type = 'address' if _using_addresses else 'port'

    def _n_trials(config_dict):
        return len(config_dict['pin_sequence']['pin_groups'])

    def one_experiment_config_with_flow_sequence(config_dict):
        n_trials = _n_trials(config_dict)

        flow_setpoints_sequence = [
            [{id_type: carrier_mfc_id, 'sccm': carrier_flow_sccm}] +
            [{id_type: mfc_id, 'sccm': odor_flow_sccm} for mfc_id in odor_mfc_ids]
            for _ in range(n_trials)
        ]
        # TODO deepcopy instead?
        config_dict = config_dict.copy()

        if require_flow_controllers is not None:
            config_dict[require_flow_controllers_key] = require_flow_controllers

        if safe_usb_ids_key in hardware_dict:
            config_dict[safe_usb_ids_key] = hardware_dict[safe_usb_ids_key]

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

