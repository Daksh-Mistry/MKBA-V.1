"""Single command authority: leases, arbitration, bounded gestures and auto state."""
from __future__ import annotations

import asyncio
import contextlib
import math
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from uuid import uuid4

from .auto_policy import AutoPolicy
from .sensors import SensorProcessor
from .robot_profile import DRIVE, LOOK, PROFILE_ID, unavailable_hardware, validate_hardware

IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$')


def number(value, name, low, high):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number between {low} and {high}')
    return value


def choice(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f'Invalid {name}')
    return value


@dataclass
class ClientSession:
    send: object
    heartbeat: float
    seq: int = -1
    requests: OrderedDict = field(default_factory=OrderedDict)
    history: list = field(default_factory=list)
    chat_busy: bool = False


class RobotController:
    def __init__(self, settings, *, pi=None, ml=None, clock=time.monotonic):
        from .pi_client import PiClient
        from .ml_client import MLClient
        self.settings, self.clock = settings, clock
        self.pi = pi if pi is not None else PiClient(settings)
        self.ml = ml if ml is not None else MLClient(settings)
        self.lock = asyncio.Lock()
        self.sessions = {}
        self.owner = None
        self.mode = 'manual'
        self.stopped = True
        self.stop_reason = 'Startup: claim control and explicitly resume'
        self.generation = 0
        self.pi_connected = self.pi_watchdog = self.pi_simulation = False
        self.pi_speech = False
        self.pi_safety = {}
        self.pi_trip_count = 0
        self.pi_fault = False
        self.partial_hardware = False
        self.hardware = unavailable_hardware()
        self.alignment_confirmed = False
        self.pi_at = None
        self.servos = {'pan': None, 'tilt': None}
        self.pump = None
        self.sensors = SensorProcessor(settings.ir_blocked_value)
        self.ml_connected = self.ml_ready = False
        self.ml_error = None
        self.ml_session = None
        self.ml_started_at = None
        self.vision_pending = None
        self.vision_wait_stop = None
        self.ml_workers_stopped = False
        self.model_id = settings.model_id
        self.capture_epoch = None
        self.frame_seq = -1
        self.latest_result = None
        self.result_at = None
        self.auto = AutoPolicy(settings)
        self.drive = None
        self.drive_until = None
        self.last_drive_send = 0.0
        self.pump_until = None
        self.last_pump_off = -1000.0
        self.last_servo = -1000.0
        self.last_pi_heartbeat = self.last_ml_heartbeat = self.last_publish = -1000.0
        self.last_error = None
        self.action_ids = OrderedDict()
        self.tasks = set()
        self.ticker = None
        self.closing = False

    async def start(self):
        await self.pi.start(self.on_pi)
        await self.ml.start(self.on_ml)
        self.ticker = asyncio.create_task(self._tick_loop(), name='backend-control-timer')

    async def close(self):
        self.closing = True
        if self.ticker:
            self.ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.ticker
        async with self.lock:
            await self._stop('Backend shutdown')
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.ml.close()
        await self.pi.close()

    def _background(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def connect(self, send):
        async with self.lock:
            if len(self.sessions) >= 32:
                raise ValueError('Maximum viewer connections reached')
            sid = str(uuid4())
            self.sessions[sid] = ClientSession(send, self.clock())
            self._emit(sid, {'type': 'hello', 'session_id': sid, 'protocol_version': 1})
            self._emit(sid, self.snapshot())
            return sid

    async def disconnect(self, sid):
        async with self.lock:
            self.sessions.pop(sid, None)
            if self.owner == sid:
                await self._stop('Operator disconnected')
                self.owner = None

    def _emit(self, sid, event):
        session = self.sessions.get(sid)
        if session:
            try:
                session.send(event)
            except Exception:
                pass  # The transport closes a slow/failed viewer separately.

    def _broadcast(self, event):
        for sid in list(self.sessions):
            self._emit(sid, event)

    def _result(self, sid, rid, status, message):
        self._emit(sid, {'type': 'command_result', 'request_id': rid, 'status': status, 'message': message})

    def _fresh_pi(self):
        return self.pi_connected and self.pi_at is not None and self.clock() - self.pi_at <= self.settings.telemetry_timeout

    def _owner_required(self, sid):
        if self.owner != sid:
            raise ValueError('Claim control before changing the robot')
        if self.clock() - self.sessions[sid].heartbeat > self.settings.owner_timeout:
            raise ValueError('Operator heartbeat expired; claim control again')

    def _ready(self, sid, *, manual=True):
        self._owner_required(sid)
        if self.stopped:
            raise ValueError('Robot is stopped; explicitly resume first')
        if manual and self.mode != 'manual':
            raise ValueError('Switch to manual mode first')
        self._pi_ready()

    def _pi_ready(self):
        if not self._fresh_pi():
            raise ValueError('Fresh Pi status is required')
        if not self.pi_watchdog:
            raise ValueError('Pi watchdog capability is required')
        if self.pi_fault:
            raise ValueError('Pi reports a hardware fault; inspect Pi logs before restarting it')
        if self.pi_simulation and not self.settings.allow_simulation:
            raise ValueError('Pi is simulated; explicitly enable simulation in backend settings')

    def _motion_ready(self):
        self._component_ready('motors')
        if not self.sensors.clear(self.clock(), self.settings.telemetry_timeout):
            if self.sensors.require_signal_evidence and not all(self.sensors.signal_observed):
                raise ValueError('IR signals are not yet verified: trigger and release each of the four sensors; a steady GPIO input cannot prove a sensor is attached')
            raise ValueError('All four IR readings must be fresh and clear')

    def _component_ready(self, name):
        part = self.hardware[name]
        if not part['available']:
            raise ValueError(f"{name.capitalize()} unavailable: {part.get('reason') or part['state']}")

    def _auto_ready(self):
        self._component_ready('servos')
        self._component_ready('pump')
        if not (self.alignment_confirmed or self.settings.auto_calibrated):
            raise ValueError('Confirm the camera/nozzle operating check in the UI before automatic spraying')
        if not self.sensors.clear(self.clock(), self.settings.telemetry_timeout):
            raise ValueError('Auto requires four clear IR inputs with observed signal changes')
        if not self._fresh_detection():
            raise ValueError('Start vision and wait for fresh ML results before resuming auto')

    def readiness(self):
        result = {'profile': PROFILE_ID, 'alignment_confirmed': self.alignment_confirmed or self.settings.auto_calibrated}
        for name, check in (('resume', lambda: None), ('drive', self._motion_ready), ('servo', lambda: self._component_ready('servos')),
                            ('pump', lambda: self._component_ready('pump')), ('auto', self._auto_ready)):
            try:
                self._pi_ready()
                check()
                result[name] = {'available': True, 'reason': None}
            except ValueError as error:
                result[name] = {'available': False, 'reason': str(error)}
        return result

    async def _send_pi(self, data):
        if not self.pi_connected:
            raise ValueError('Pi is disconnected')
        try:
            await self.pi.send(data)
        except Exception:
            self.pi_connected = False
            self.stopped = True
            self.drive = self.drive_until = self.pump_until = None
            self.generation += 1
            self.last_error = 'Pi command could not be delivered; local watchdog will stop outputs'
            raise ValueError(self.last_error) from None

    async def _stop(self, reason):
        self.stopped = True
        self.stop_reason = reason
        self.generation += 1
        self.drive = self.drive_until = self.pump_until = None
        self.last_pump_off = self.clock()
        if self.auto.phase not in {'complete', 'blocked'}:
            self.auto.phase = 'paused'
        if self.pi_connected:
            with contextlib.suppress(ValueError):
                await self._send_pi({'type': 'system', 'command': 'stop'})
        self._broadcast({'type': 'event', 'code': 'stopped', 'message': reason})

    async def _override(self):
        """Invalidate pending chat actions; terminate earlier timed outputs."""
        self.generation += 1
        if self.drive is not None:
            self.drive = self.drive_until = None
            await self._send_pi({'type': 'drive', 'left': 0, 'right': 0, 'speed': 0})
        if self.pump_until is not None or self.pump:
            self.pump_until = None
            self.last_pump_off = self.clock()
            await self._send_pi({'type': 'pump', 'on': False})

    async def _drive(self, direction, speed, duration):
        self._motion_ready()
        left, right = DRIVE[direction]
        self.drive = {'type': 'drive', 'left': left, 'right': right, 'speed': speed}
        self.drive_until = self.clock() + duration
        self.last_drive_send = self.clock()
        await self._send_pi(self.drive)

    async def _servo(self, pan, tilt):
        self._component_ready('servos')
        now = self.clock()
        if now - self.last_servo < 0.15:
            raise ValueError('Wait before the next face movement')
        self.last_servo = now
        await self._send_pi({'type': 'servo', 'pan': pan, 'tilt': tilt})

    async def _pump(self, duration):
        self._component_ready('pump')
        if self.pump_until is not None or self.pump:
            raise ValueError('Pump burst already in progress')
        if self.clock() - self.last_pump_off < 3:
            raise ValueError('Pump cooldown is three seconds')
        # Explicit off rearms the Pi maximum-on lease without extending a burst.
        await self._send_pi({'type': 'pump', 'on': False})
        await self._send_pi({'type': 'pump', 'on': True})
        self.pump_until = self.clock() + min(duration, 1.0)

    async def _vision(self, start, model_id=None):
        self.vision_pending = None
        if self.ml_session:
            previous = self.ml_session
            self.vision_wait_stop = previous
            self.ml_workers_stopped = False
            self.ml_session = None
            self.ml_ready = False
            self.latest_result = self.result_at = None
            with contextlib.suppress(Exception):
                await self.ml.send({'type': 'session.stop', 'session_id': previous})
        if not start:
            return
        if not self.ml_connected:
            raise ValueError('ML service is disconnected')
        self.model_id = model_id or self.model_id
        self.vision_pending = self.clock()
        if self.ml_workers_stopped and self.vision_wait_stop is None:
            await self._begin_vision()

    async def _begin_vision(self):
        self.vision_pending = None
        self.ml_session = str(uuid4())
        self.ml_started_at = self.clock()
        self.capture_epoch = None
        self.frame_seq = -1
        self.ml_error = None
        try:
            await self.ml.send({'type': 'session.start', 'session_id': self.ml_session, 'model_id': self.model_id})
        except Exception:
            self.ml_session = None
            raise ValueError('Could not start the ML session') from None

    async def handle(self, sid, data):
        async with self.lock:
            rid = data.get('request_id') if isinstance(data, dict) else None
            try:
                session = self.sessions.get(sid)
                if not session:
                    return
                if not isinstance(data, dict) or not isinstance(rid, str) or not IDENTIFIER.fullmatch(rid):
                    raise ValueError('A valid request_id is required')
                seq = data.get('seq')
                if type(seq) is not int or seq < 0 or seq <= session.seq:
                    raise ValueError('seq must increase on this connection')
                session.seq = seq
                if rid in session.requests:
                    raise ValueError('Duplicate request_id; commands are never replayed')
                session.requests[rid] = True
                while len(session.requests) > 512:
                    session.requests.popitem(last=False)
                kind = data.get('type')
                fields = {
                    'heartbeat': set(), 'control': {'command'}, 'drive': {'direction', 'speed'},
                    'servo': {'direction', 'degrees'}, 'pump': {'on', 'duration_ms'},
                    'mode': {'value'}, 'system': {'command'}, 'vision': {'command', 'model_id'},
                    'chat': {'message', 'speak'}, 'speech': {'command'}, 'view.status': {'playing'},
                    'readiness': {'command'},
                }
                if not isinstance(kind, str) or kind not in fields or set(data) - (fields.get(kind, set()) | {'type', 'seq', 'request_id'}):
                    raise ValueError('Unknown message type or fields')
                if kind == 'heartbeat':
                    session.heartbeat = self.clock()
                    self._emit(sid, {'type': 'heartbeat_ack', 'request_id': rid})
                    return
                if kind == 'view.status':
                    if type(data.get('playing')) is not bool:
                        raise ValueError('playing must be a boolean')
                    self._result(sid, rid, 'accepted', 'Viewer state received; it does not establish ML freshness')
                    return
                if kind == 'readiness':
                    choice(data.get('command'), 'operating check', {'confirm_alignment'})
                    self._owner_required(sid)
                    if not self.stopped:
                        raise ValueError('Stop the robot before confirming its operating check')
                    self._pi_ready()
                    self._component_ready('servos')
                    self._component_ready('pump')
                    self.alignment_confirmed = True
                    self._result(sid, rid, 'completed', 'Camera/nozzle operating check recorded for this Pi connection')
                    return
                if kind == 'system':
                    command = choice(data.get('command'), 'system command', {'stop', 'shutdown'})
                    if command == 'stop':
                        await self._stop('Stop requested by viewer')
                    else:
                        self._owner_required(sid)
                        await self._stop('Pi script shutdown requested')
                        await self._send_pi({'type': 'system', 'command': 'shutdown'})
                    self._result(sid, rid, 'sent_to_pi' if self.pi_connected else 'accepted',
                                 'Stop state set; physical execution requires Pi telemetry' if command == 'stop' else 'Pi script shutdown sent')
                    return
                if kind == 'control':
                    command = choice(data.get('command'), 'control command', {'claim', 'release', 'resume'})
                    if command == 'claim':
                        if self.owner not in (None, sid):
                            raise ValueError('Another operator owns control')
                        self.owner = sid
                        session.heartbeat = self.clock()
                    elif command == 'release':
                        self._owner_required(sid)
                        await self._stop('Control released')
                        self.owner = None
                    else:
                        self._owner_required(sid)
                        self._pi_ready()
                        if self.mode == 'auto':
                            self._auto_ready()
                            self.auto.reset()
                            self.auto.phase = 'observe'
                        self.stopped = False
                        self.stop_reason = None
                        self.generation += 1
                    self._result(sid, rid, 'completed', f'Control {command} accepted')
                    return
                if kind == 'chat':
                    message, speak = data.get('message'), data.get('speak', False)
                    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000 or type(speak) is not bool:
                        raise ValueError('Chat requires message text up to 2000 characters and a boolean speak flag')
                    # Stop does not depend on a live model, chat slot or provider.
                    if re.fullmatch(r'(?:please )?(?:can you |could you )?(?:please )?stop(?: please)?[.!?]?', ' '.join(message.lower().split())):
                        await self._stop('Stop requested in chat')
                        self._emit(sid, {'type': 'chat.reply', 'request_id': rid,
                                        'text': ('I sent the stop request. Check my status to confirm the hardware response.'
                                                 if self.pi_connected else
                                                 'I set the backend to stopped, but the Pi is disconnected; delivery is not confirmed.'),
                                        'action_status': 'sent_to_pi' if self.pi_connected else 'blocked',
                                        'speech_status': 'not_requested'})
                        return
                    if session.chat_busy or sum(s.chat_busy for s in self.sessions.values()) >= 4:
                        raise ValueError('Chat is busy; wait for the current reply')
                    session.chat_busy = True
                    self._background(self._chat(sid, rid, message.strip(), speak, self.generation))
                    self._result(sid, rid, 'accepted', 'Chat request accepted')
                    return
                if kind == 'speech':
                    choice(data.get('command'), 'speech command', {'stop'})
                    self._background(self._speech_stop(sid, rid))
                    return
                self._owner_required(sid)
                if kind == 'mode':
                    value = choice(data.get('value'), 'mode', {'manual', 'auto'})
                    await self._stop('Mode changed; explicitly resume')
                    self.mode = value
                    self.auto.reset()
                    await self._send_pi({'type': 'mode', 'value': value})
                    if value == 'auto' and not self.ml_session:
                        await self._vision(True)
                elif kind == 'vision':
                    command = choice(data.get('command'), 'vision command', {'start', 'stop'})
                    model_id = data.get('model_id')
                    if model_id is not None and (not isinstance(model_id, str) or not IDENTIFIER.fullmatch(model_id)):
                        raise ValueError('Invalid model_id')
                    if not self.stopped:
                        await self._stop('Vision configuration changed; explicitly resume')
                    await self._vision(command == 'start', model_id)
                elif kind == 'drive':
                    direction = choice(data.get('direction'), 'drive direction', DRIVE)
                    speed = number(data.get('speed', 0.2), 'speed', 0, self.settings.maximum_speed)
                    if direction == 'stop' or speed == 0:
                        self._component_ready('motors')
                        await self._override()
                        await self._send_pi({'type': 'drive', 'left': 0, 'right': 0, 'speed': 0})
                    else:
                        self._ready(sid)
                        await self._override()
                        await self._drive(direction, speed, self.settings.drive_input_timeout)
                elif kind == 'servo':
                    self._ready(sid)
                    direction = choice(data.get('direction'), 'face direction', LOOK)
                    degrees = number(data.get('degrees', 5), 'degrees', 1, 10)
                    await self._override()
                    pan, tilt = LOOK[direction]
                    await self._servo(pan * degrees, tilt * degrees)
                elif kind == 'pump':
                    if type(data.get('on')) is not bool:
                        raise ValueError('on must be a JSON boolean')
                    duration = number(data.get('duration_ms', 800), 'duration_ms', 100, 1000) / 1000
                    if data['on']:
                        self._ready(sid)
                        if self.pump_until is not None or self.pump:
                            raise ValueError('Pump burst already in progress')
                        await self._override()
                        await self._pump(duration)
                    else:
                        self._component_ready('pump')
                        self.generation += 1
                        self.pump_until = None
                        self.last_pump_off = self.clock()
                        await self._send_pi({'type': 'pump', 'on': False})
                self._result(sid, rid, 'sent_to_pi' if kind != 'vision' else 'accepted',
                             'Command sent; hardware execution is reported separately by Pi status' if kind != 'vision' else 'Vision request sent to ML')
            except ValueError as error:
                self._result(sid, rid, 'rejected', str(error))

    def _fresh_detection(self):
        return self.ml_connected and self.ml_ready and self.latest_result is not None and self.result_at is not None and (
            self.clock() - self.result_at + self.latest_result['frame_age_at_send_ms'] / 1000 <= self.settings.detection_timeout)

    async def on_pi(self, event):
        async with self.lock:
            kind = event.get('type')
            if kind == 'connection':
                self.pi_connected = event.get('connected') is True
                self.pi_watchdog = False
                self.pi_at = None
                self.pi_trip_count = 0
                self.pi_safety = {}
                self.pi_fault = False
                self.partial_hardware = False
                self.hardware = unavailable_hardware()
                self.alignment_confirmed = False
                self.servos = {'pan': None, 'tilt': None}
                self.pump = None
                self.pi_speech = False
                self.sensors = SensorProcessor(self.settings.ir_blocked_value)
                if self.pi_connected:
                    await self._stop('Pi connected; explicitly resume')
                else:
                    await self._stop('Pi disconnected')
                    self.last_error = event.get('code', 'pi_disconnected')
            elif kind == 'hello':
                caps = event.get('capabilities', {})
                if not isinstance(caps, dict):
                    self.pi_at = None
                    await self._stop('Malformed Pi capabilities')
                    return
                self.pi_watchdog = caps.get('watchdog') is True
                self.pi_simulation = caps.get('simulation') is True
                self.pi_speech = caps.get('speech') is True
                self.partial_hardware = caps.get('partial_hardware') is True
                self.sensors.require_signal_evidence = self.partial_hardware and not self.pi_simulation
                if not self.partial_hardware:
                    # Legacy Pi reports all-or-nothing startup rather than parts.
                    self.hardware = {name: {'state': 'available', 'available': True,
                                           'presence': 'legacy_server_not_reported', 'reason': None}
                                     for name in ('motors', 'servos', 'pump', 'sensors')}
            elif kind == 'status':
                now = self.clock()
                servos = event.get('servos', {})
                if 'hardware' in event:
                    self.partial_hardware = True
                    self.sensors.require_signal_evidence = not self.pi_simulation
                try:
                    hardware = validate_hardware(event.get('hardware'), simulated=self.pi_simulation) if self.partial_hardware or 'hardware' in event else self.hardware
                    if not isinstance(servos, dict) or not {'pan', 'tilt'} <= set(servos):
                        raise ValueError('Invalid servo status')
                    if not hardware['servos']['available'] and any(servos[axis] is not None for axis in ('pan', 'tilt')):
                        raise ValueError('Unavailable servos must report unknown angles')
                    angles = {axis: (None if servos.get(axis) is None and not hardware['servos']['available']
                                     else number(servos.get(axis), axis, 0, 180)) for axis in ('pan', 'tilt')}
                    if 'pump' not in event or (type(event.get('pump')) is not bool and not (event.get('pump') is None and not hardware['pump']['available'])):
                        raise ValueError('Invalid pump status')
                    if not hardware['pump']['available'] and event['pump'] is not None:
                        raise ValueError('Unavailable pump must report unknown state')
                except (ValueError, TypeError):
                    self.pi_at = None
                    await self._stop('Malformed Pi telemetry')
                    return
                lost = [name for name in ('motors', 'servos', 'pump') if self.hardware[name]['available'] and not hardware[name]['available']]
                self.hardware = hardware
                self.servos = angles
                self.pump = event['pump']
                speech = event.get('speech')
                if isinstance(speech, dict) and 'available' in speech:
                    self.pi_speech = speech['available'] is True
                self.pi_at = now
                self.sensors.update(event.get('sensors'), now, self.hardware['sensors'])
                safety = event.get('safety', {})
                if not isinstance(safety, dict):
                    self.pi_at = None
                    await self._stop('Malformed Pi safety status')
                    return
                faults = safety.get('faults') or []
                unavailable = [name for name in ('motors', 'servos', 'pump') if not hardware[name]['available']]
                isolated_faults = self.partial_hardware and isinstance(faults, list) and all(
                    isinstance(fault, str) and any(re.search(r'\b' + name + r'\b', fault) for name in unavailable)
                    for fault in faults)
                self.pi_fault = bool(faults) and not isolated_faults
                reason = safety.get('reason')
                trip_count = safety.get('trip_count', self.pi_trip_count)
                new_trip = type(trip_count) is int and trip_count > self.pi_trip_count
                if type(trip_count) is int:
                    self.pi_trip_count = max(self.pi_trip_count, trip_count)
                self.pi_safety = {'reason': reason if isinstance(reason, str) else None,
                                  'fault': self.pi_fault, 'component_faults': bool(faults) and isolated_faults,
                                  'trip_count': self.pi_trip_count,
                                  'control_lease_valid': safety.get('control_lease_valid') is True}
                if lost:
                    self.alignment_confirmed = False
                if not self.stopped and (lost or new_trip or self.pi_fault or reason in {
                    'control_timeout', 'watchdog_hardware_error', 'telemetry_error',
                }):
                    await self._stop('Pi safety watchdog or hardware fault stopped the robot')
                if self.drive is not None and not self.sensors.clear(now, self.settings.telemetry_timeout):
                    await self._stop('IR hazard or unknown reading while driving')
                if self.mode == 'auto' and not self.stopped and not self.sensors.clear(now, self.settings.telemetry_timeout):
                    await self._stop('IR hazard or unknown reading in auto')
            elif kind == 'error':
                self.last_error = 'Pi rejected a command; inspect Pi logs and settings'
                await self._stop(self.last_error)

    def _validate_result(self, event):
        if event.get('session_id') != self.ml_session or event.get('model_id') != self.model_id:
            return False
        if event.get('stream_id') != self.settings.stream_id or event.get('schema_version') != 1:
            return False
        seq, epoch = event.get('frame_seq'), event.get('capture_epoch')
        if type(seq) is not int or seq <= self.frame_seq or not isinstance(epoch, str):
            return False
        if self.capture_epoch is not None and epoch != self.capture_epoch:
            return False
        age = number(event.get('frame_age_at_send_ms'), 'frame age', 0, 60000)
        if age > self.settings.detection_timeout * 1000:
            return False
        detections = event.get('detections')
        if not isinstance(detections, list) or len(detections) > 100:
            return False
        for item in detections:
            if not isinstance(item, dict) or item.get('class') not in {'fire', 'smoke'}:
                return False
            number(item.get('score'), 'confidence', 0, 1)
            box = item.get('bbox')
            if not isinstance(box, list) or len(box) != 4:
                return False
            x1, y1, x2, y2 = [number(v, 'box coordinate', 0, 1) for v in box]
            if x1 >= x2 or y1 >= y2:
                return False
        self.frame_seq, self.capture_epoch = seq, epoch
        return True

    async def on_ml(self, event):
        async with self.lock:
            kind = event.get('type')
            if kind == 'connection':
                self.ml_connected = event.get('connected') is True
                self.ml_ready = False
                self.ml_session = None
                self.vision_pending = self.vision_wait_stop = None
                self.ml_workers_stopped = False
                self.latest_result = self.result_at = None
                if not self.ml_connected:
                    self.ml_error = event.get('code', 'ml_disconnected')
                    if self.mode == 'auto' and not self.stopped:
                        await self._stop('ML connection lost in auto')
                else:
                    self.ml_error = None
                return
            if kind == 'session.stopped' and event.get('session_id') == self.vision_wait_stop:
                self.vision_wait_stop = None
            if kind == 'health':
                health = event.get('vision', {})
                self.ml_workers_stopped = (health.get('state') == 'stopped' and
                                           not any(health.get('workers_alive', {}).values()))
                if self.vision_pending is not None and self.vision_wait_stop is None and self.ml_workers_stopped:
                    await self._begin_vision()
                    return
            if event.get('session_id') is not None and event.get('session_id') != self.ml_session:
                return
            if kind == 'session.ready':
                self.ml_ready = True
                self.ml_error = None
            elif kind == 'session.stopped':
                self.ml_ready = False
                if self.mode == 'auto' and not self.stopped:
                    await self._stop('ML session stopped')
            elif kind == 'model.status':
                self.ml_ready = False
            elif kind == 'error' or (kind == 'health' and event.get('vision', {}).get('state') == 'unhealthy'):
                self.ml_ready = False
                self.ml_error = event.get('code', 'ml_unhealthy')
                if self.mode == 'auto' and not self.stopped:
                    await self._stop('ML reported a failure')
            elif kind == 'result':
                try:
                    valid = self._validate_result(event)
                except (ValueError, TypeError):
                    valid = False
                if not valid:
                    return
                self.latest_result = dict(event)
                self.result_at = self.clock()
                self._broadcast(dict(event, type='detections', receipt_age_ms=0))
                if self.mode == 'auto' and not self.stopped:
                    try:
                        self._pi_ready()
                        self._auto_ready()
                        action = self.auto.step(event, self.clock(), self.servos)
                        if action:
                            if action['kind'] == 'servo':
                                await self._servo(action['pan'], action['tilt'])
                            elif action['kind'] == 'pump':
                                await self._pump(action['duration'])
                            elif action['kind'] == 'complete':
                                await self._stop(self.auto.reason or 'Auto cycle complete')
                    except ValueError as error:
                        await self._stop(f'Auto paused: {error}')

    async def _chat(self, sid, rid, message, speak, generation):
        session = self.sessions.get(sid)
        if not session:
            return
        began = self.clock()
        context = self.chat_context(sid)
        try:
            reply = await self.ml.chat({'session_id': sid, 'request_id': rid, 'message': message,
                                        'history': list(session.history[-12:]), 'context': context})
            async with self.lock:
                if sid not in self.sessions:
                    return
                if not isinstance(reply, dict) or reply.get('request_id') != rid or reply.get('session_id') != sid:
                    raise ValueError('Invalid chat response')
                text = reply.get('text')
                if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                    raise ValueError('Invalid conversation text')
                status = 'none'
                action = reply.get('action')
                if action is not None:
                    try:
                        await self._gesture(sid, rid, action, generation, began, message)
                        status = 'sent_to_pi'
                        text = 'I sent the gesture request; movement is not physically confirmed.'
                    except ValueError as error:
                        status = 'blocked'
                        text = f'I did not send that gesture: {error}.'
                elif reply.get('action_status') in {'blocked', 'duplicate'}:
                    status = 'blocked'
                session.history.extend([{'role': 'user', 'content': message}, {'role': 'assistant', 'content': text[:2000]}])
                del session.history[:-12]
                event = {'type': 'chat.reply', 'request_id': rid, 'text': text, 'action_status': status,
                         'reason_code': reply.get('reason_code'), 'speech_status': 'not_requested',
                         'chat_mode': reply.get('chat_mode')}
                if speak:
                    if self.owner != sid or generation != self.generation or self.stopped:
                        event['speech_status'] = 'blocked'
                    elif not self.settings.speech_enabled or not self.pi_speech:
                        event['speech_status'] = 'disabled'
                    else:
                        event['speech_status'] = 'pending'
                        self._background(self._speak(sid, rid, text, self.generation))
                self._emit(sid, event)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._emit(sid, {'type': 'chat.reply', 'request_id': rid,
                             'text': 'Conversation service is unavailable. No new gesture was sent.',
                             'action_status': 'blocked', 'reason_code': 'chat_unavailable'})
        finally:
            session.chat_busy = False

    async def _gesture(self, sid, rid, action, generation, began, message):
        if not isinstance(action, dict):
            raise ValueError('Malformed action proposal')
        kind = choice(action.get('kind'), 'gesture kind', {'move', 'look', 'stop'})
        # An ML reply cannot invent a movement for an ordinary conversation.
        # Recheck the original user's entire sentence independently of ML.
        normalized = ' '.join(message.lower().split())
        matched = re.fullmatch(
            r'(?:please )?(?:can you |could you )?(?:please )?'
            r'(?P<command>stop|look (?:left|right|up|down)|'
            r'move (?:(?:a little(?: bit)?|a bit) )?(?:forward|backward|backwards)|turn (?:left|right))'
            r'(?: please)?[.!?]?', normalized)
        if matched is None:
            raise ValueError('The original message did not request one supported gesture')
        command = matched['command']
        expected_kind = 'stop' if command == 'stop' else 'look' if command.startswith('look ') else 'move'
        expected_direction = command.split()[-1].replace('backwards', 'backward')
        if command.startswith('turn '):
            expected_direction = 'turn_' + expected_direction
        if kind != expected_kind or (kind != 'stop' and action.get('direction') != expected_direction):
            raise ValueError('Proposed gesture does not match the user request')
        fields = {'action_id', 'request_id', 'session_id', 'status', 'valid_for_ms', 'kind'}
        fields |= {'direction', 'degrees'} if kind == 'look' else {'direction', 'duration_ms', 'speed'} if kind == 'move' else set()
        if set(action) != fields or action.get('request_id') != rid or action.get('session_id') != sid or action.get('status') != 'proposed':
            raise ValueError('Proposal does not match this request')
        aid = action.get('action_id')
        if not isinstance(aid, str) or not IDENTIFIER.fullmatch(aid) or aid in self.action_ids:
            raise ValueError('Invalid or repeated action identifier')
        ttl = number(action.get('valid_for_ms'), 'proposal lifetime', 1, 1000) / 1000
        if self.clock() - began > ttl or generation != self.generation:
            raise ValueError('Gesture expired or another command took priority')
        self._ready(sid)
        self.action_ids[aid] = True
        while len(self.action_ids) > 1024:
            self.action_ids.popitem(last=False)
        if kind == 'stop':
            await self._stop('Chat stop proposal')
        elif kind == 'look':
            direction = choice(action.get('direction'), 'look direction', LOOK)
            degrees = number(action.get('degrees'), 'gesture degrees', 1, 5)
            await self._override()
            pan, tilt = LOOK[direction]
            await self._servo(pan * degrees, tilt * degrees)
        else:
            direction = choice(action.get('direction'), 'gesture direction', {'forward', 'backward', 'turn_left', 'turn_right'})
            speed = number(action.get('speed'), 'gesture speed', 0.01, 0.2)
            duration = number(action.get('duration_ms'), 'gesture duration', 1, 300) / 1000
            await self._override()
            await self._drive(direction.removeprefix('turn_'), speed, duration)

    async def _speak(self, sid, rid, text, generation):
        # Speech is cancellable independently; Pi also cancels it on system.stop.
        status = 'cancelled'
        if generation == self.generation and self.owner == sid and not self.stopped:
            try:
                await self.pi.speech(text[:500], rid)
                status = 'accepted'
                if generation != self.generation or self.owner != sid or self.stopped:
                    await self.pi.stop_speech()
                    status = 'cancelled'
            except Exception:
                status = 'unavailable'
        self._emit(sid, {'type': 'event', 'request_id': rid, 'code': 'speech_status', 'status': status})

    async def _speech_stop(self, sid, rid):
        try:
            await self.pi.stop_speech()
            self._result(sid, rid, 'completed', 'Speech stop accepted by Pi')
        except Exception:
            self._result(sid, rid, 'rejected', 'Pi speech endpoint unavailable')

    def chat_context(self, sid):
        now = self.clock()
        detection = None
        if self.latest_result and self.result_at is not None and self.latest_result['detections']:
            item = max(self.latest_result['detections'], key=lambda d: d['score'])
            detection = {'class': item['class'], 'score': float(item['score']),
                         'age_ms': min(60000.0, max(0.0, (now - self.result_at) * 1000 + self.latest_result['frame_age_at_send_ms']))}
        return {'mode': self.mode, 'pi_connected': self.pi_connected, 'stopped': self.stopped,
                'state_age_ms': 60000.0 if self.pi_at is None else min(60000.0, max(0.0, (now - self.pi_at) * 1000)),
                'control_session_id': self.owner, 'operator_has_control': self.owner == sid,
                'movement_executor_ready': self.pi_watchdog and self._fresh_pi() and not self.pi_fault,
                'latest_detection': detection,
                'speaker_available': self.settings.speech_enabled and self.pi_speech and self.pi_connected}

    async def _tick_loop(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                async with self.lock:
                    self.last_error = 'Control timer error; inspect backend logs'
                    await self._stop(self.last_error)
            await asyncio.sleep(0.05)

    async def tick(self):
        async with self.lock:
            now = self.clock()
            if self.owner and now - self.sessions[self.owner].heartbeat > self.settings.owner_timeout:
                await self._stop('Operator heartbeat expired')
                self.owner = None
            if not self.stopped and not self._fresh_pi():
                await self._stop('Pi telemetry is stale')
            if self.mode == 'auto' and not self.stopped and not self._fresh_detection():
                await self._stop('ML results are stale')
            if self.vision_pending is not None and now - self.vision_pending > 10:
                self.vision_pending = None
                self.ml_error = 'Old model workers did not stop; restart ML before selecting a model'
            if self.drive is not None:
                if now >= self.drive_until:
                    self.drive = self.drive_until = None
                    with contextlib.suppress(ValueError):
                        await self._send_pi({'type': 'drive', 'left': 0, 'right': 0, 'speed': 0})
                elif not self.sensors.clear(now, self.settings.telemetry_timeout):
                    await self._stop('IR readings are stale or blocked')
                elif now - self.last_drive_send >= 0.09:
                    with contextlib.suppress(ValueError):
                        await self._send_pi(self.drive)
                    self.last_drive_send = now
            if self.pump_until is not None and now >= self.pump_until:
                self.pump_until = None
                self.last_pump_off = now
                with contextlib.suppress(ValueError):
                    await self._send_pi({'type': 'pump', 'on': False})
                if self.mode == 'auto':
                    self.auto.phase = 'reassess'
            if self.pi_connected and now - self.last_pi_heartbeat >= 0.19:
                with contextlib.suppress(ValueError):
                    await self._send_pi({'type': 'heartbeat'})
                self.last_pi_heartbeat = now
            if self.ml_connected and now - self.last_ml_heartbeat >= 0.9:
                with contextlib.suppress(Exception):
                    await self.ml.send({'type': 'heartbeat'})
                self.last_ml_heartbeat = now
            if now - self.last_publish >= 0.19:
                self._broadcast(self.snapshot())
                self.last_publish = now

    def snapshot(self):
        now = self.clock()
        return {'type': 'state', 'mode': self.mode, 'stopped': self.stopped,
                'stop_reason': self.stop_reason, 'owner_session_id': self.owner,
                'pi': {'connected': self.pi_connected, 'watchdog': self.pi_watchdog,
                       'age_ms': None if self.pi_at is None else round((now - self.pi_at) * 1000),
                       'simulation': self.pi_simulation, 'speech_available': self.pi_speech,
                       'safety': dict(self.pi_safety), 'hardware': self.hardware},
                'ml': {'connected': self.ml_connected, 'ready': self.ml_ready, 'model_id': self.model_id,
                       'session_id': self.ml_session, 'fresh': self._fresh_detection(), 'error': self.ml_error,
                       'starting': self.vision_pending is not None or (self.ml_session is not None and not self.ml_ready)},
                'servos': dict(self.servos), 'pump': self.pump, 'drive_active': self.drive is not None,
                'sensors': self.sensors.snapshot(now, self.settings.telemetry_timeout), 'auto': self.auto.snapshot(),
                'readiness': self.readiness(),
                'calibration': {'motion_calibrated': self.settings.motion_calibrated,
                                'auto_calibrated': self.settings.auto_calibrated,
                                'motion_profile_configured': True,
                                'ir_blocked_value': self.settings.ir_blocked_value,
                                'simulation_allowed': self.settings.allow_simulation},
                'speech_enabled': self.settings.speech_enabled, 'last_error': self.last_error}

    def video_sources(self):
        return {'whep_url': self.settings.whep_url, 'viewer_url': self.settings.viewer_url,
                'stream_id': self.settings.stream_id, 'stream_revision': 1,
                'alignment': 'approximate', 'frame_age_basis': 'local_decoder_receipt'}

    def auto_config(self):
        return {'model_id': self.model_id, 'confidence': self.settings.auto_confidence,
                'spray_ms': round(self.settings.auto_spray_seconds * 1000),
                'cooldown_ms': round(self.settings.auto_cooldown_seconds * 1000),
                'maximum_bursts': 3, 'approach_enabled': False,
                'calibration_required': not (self.alignment_confirmed or self.settings.auto_calibrated),
                'readiness': self.readiness()['auto']}
