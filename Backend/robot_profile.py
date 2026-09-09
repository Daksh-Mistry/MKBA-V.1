"""The existing MKBA V1 wiring, without claiming physical calibration."""

PROFILE_ID = 'mkba-v1'
DRIVE = {'forward': (1, 1), 'backward': (-1, -1), 'left': (-1, 1), 'right': (1, -1), 'stop': (0, 0)}
LOOK = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1), 'center': (0, 0), 'stop': (0, 0)}
# PI/hardware/sensors.py uses pull-up active-low IR and already inverts flame.
IR_BLOCKED_VALUE = 0


def unavailable_hardware():
    return {name: {'state': 'unknown', 'available': False, 'reason': 'Waiting for Pi hardware status'}
            for name in ('motors', 'servos', 'pump', 'sensors')}


def validate_hardware(value, *, simulated=False):
    """Keep individual failures explicit; GPIO initialization is not load detection."""
    if not isinstance(value, dict):
        raise ValueError('Pi hardware status must be an object')
    result = {}
    states = {'available', 'unavailable', 'disabled', 'partial', 'simulated'}
    for name in ('motors', 'servos', 'pump', 'sensors'):
        part = value.get(name)
        if not isinstance(part, dict) or part.get('state') not in states or type(part.get('available')) is not bool:
            raise ValueError(f'Invalid Pi {name} availability')
        if part['state'] == 'simulated' and not simulated:
            raise ValueError('Real Pi reported a simulated hardware component')
        if name != 'sensors' and part['available'] != (part['state'] in {'available', 'simulated'}):
            raise ValueError(f'Conflicting Pi {name} availability')
        result[name] = {key: part[key] for key in ('state', 'available', 'reason', 'presence') if key in part}
        if part.get('reason') is not None and not isinstance(part['reason'], str):
            raise ValueError(f'Invalid Pi {name} reason')
        if name == 'sensors' and isinstance(part.get('channels'), dict):
            result[name]['channels'] = {}
            for group in ('ir_array', 'flame_array'):
                channels = part['channels'].get(group)
                if not isinstance(channels, list) or len(channels) != 4:
                    raise ValueError('Pi sensor status requires four channels per group')
                result[name]['channels'][group] = []
                for channel in channels:
                    if not isinstance(channel, dict) or type(channel.get('available')) is not bool:
                        raise ValueError('Invalid Pi sensor channel status')
                    result[name]['channels'][group].append({key: channel[key] for key in
                        ('state', 'available', 'reason', 'gpio', 'value', 'samples', 'changes', 'read_errors', 'evidence')
                        if key in channel})
    return result
