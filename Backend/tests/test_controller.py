import asyncio
import unittest
from dataclasses import replace

from Backend.config import Settings
from Backend.controller import RobotController
from Backend.sensors import SensorProcessor


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, value):
        self.now += value


def status(ir=None, pump=False, pan=90, tilt=90):
    return {'type': 'status', 'servos': {'pan': pan, 'tilt': tilt}, 'pump': pump,
            'mode': 'manual', 'sensors': {'ir_array': [1] * 4 if ir is None else ir,
                                          'flame_array': [0] * 4}}


class FakePi:
    def __init__(self):
        self.sent = []
        self.fail = False
        self.speech_calls = []

    async def start(self, callback):
        self.callback = callback
        await callback({'type': 'connection', 'connected': True})
        await callback({'type': 'hello', 'capabilities': {'watchdog': True, 'simulation': False, 'speech': True}})
        await callback(status())
        await callback(status())

    async def send(self, data):
        if self.fail:
            raise ConnectionError('private endpoint should never leak')
        self.sent.append(dict(data))

    async def speech(self, text, rid):
        self.speech_calls.append((text, rid))
        return {'status': 'accepted'}

    async def stop_speech(self):
        self.speech_calls.append(('stop', None))
        return {'status': 'stopped'}

    async def close(self):
        pass


class FakeML:
    def __init__(self):
        self.sent = []
        self.chat_calls = []
        self.chat_release = None
        self.action = None
        self.reply_override = None

    async def start(self, callback):
        self.callback = callback
        await callback({'type': 'connection', 'connected': True})
        await callback({'type': 'health', 'vision': {'state': 'stopped', 'workers_alive': {}}})

    async def send(self, data):
        self.sent.append(dict(data))

    async def models(self):
        return {'models': [{'id': 'fire-smoke-v8n'}]}

    async def chat(self, data):
        self.chat_calls.append(data)
        if self.chat_release:
            await self.chat_release.wait()
        if self.reply_override is not None:
            return self.reply_override
        action = self.action
        if action:
            action = {'action_id': data['request_id'] + '-action', 'request_id': data['request_id'],
                      'session_id': data['session_id'], 'status': 'proposed', 'valid_for_ms': 1000, **action}
        return {'request_id': data['request_id'], 'session_id': data['session_id'],
                'text': 'Hello from Robo.', 'action': action, 'action_status': 'proposed' if action else 'none'}

    async def close(self):
        pass


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock, self.pi, self.ml = Clock(), FakePi(), FakeML()
        self.settings = Settings(service_token='test', ir_blocked_value=0,
                                 motion_calibrated=True, auto_calibrated=True, speech_enabled=False)
        self.robot = RobotController(self.settings, pi=self.pi, ml=self.ml, clock=self.clock)
        # Drive the fake adapters directly; deterministic tick() replaces wall-clock timer.
        await self.pi.start(self.robot.on_pi)
        await self.ml.start(self.robot.on_ml)
        self.events = []
        self.sid = await self.robot.connect(self.events.append)
        self.seq = 0

    async def asyncTearDown(self):
        await self.robot.close()

    async def send(self, kind, **fields):
        self.seq += 1
        rid = f'r-{self.seq}'
        await self.robot.handle(self.sid, {'type': kind, 'request_id': rid, 'seq': self.seq, **fields})
        return rid

    def result(self):
        return next(e for e in reversed(self.events) if e['type'] == 'command_result')

    async def ready(self):
        await self.send('control', command='claim')
        await self.send('control', command='resume')
        self.assertFalse(self.robot.stopped)

    async def settle(self):
        for _ in range(3):
            tasks = list(self.robot.tasks)
            if not tasks:
                break
            await asyncio.gather(*tasks)

    async def vision(self):
        await self.send('vision', command='start')
        await self.robot.on_ml({'type': 'session.ready', 'session_id': self.robot.ml_session})

    async def fire(self, seq, detections=None):
        await self.robot.on_pi(status())
        await self.robot.on_ml({'type': 'result', 'schema_version': 1,
                                'model_id': self.robot.model_id, 'session_id': self.robot.ml_session,
                                'stream_id': 'pi-cam', 'capture_epoch': 'epoch', 'frame_seq': seq,
                                'frame_age_at_send_ms': 25.0,
                                'detections': [{'class': 'fire', 'score': 0.9, 'bbox': [0.4, 0.4, 0.6, 0.6]}]
                                if detections is None else detections})

    async def test_startup_stops_and_requires_claim_and_resume(self):
        await self.send('drive', direction='forward')
        self.assertEqual(self.result()['status'], 'rejected')
        await self.send('control', command='claim')
        await self.send('drive', direction='forward')
        self.assertEqual(self.result()['status'], 'rejected')
        await self.send('control', command='resume')
        await self.send('drive', direction='forward', speed=0.2)
        self.assertEqual(self.pi.sent[-1], {'type': 'drive', 'left': 1, 'right': -1, 'speed': 0.2})

    async def test_only_owner_moves_but_any_viewer_can_stop(self):
        await self.ready()
        other_events = []
        other = await self.robot.connect(other_events.append)
        await self.robot.handle(other, {'type': 'control', 'command': 'claim', 'seq': 1, 'request_id': 'c'})
        self.assertEqual(other_events[-1]['status'], 'rejected')
        await self.robot.handle(other, {'type': 'system', 'command': 'stop', 'seq': 2, 'request_id': 's'})
        self.assertTrue(self.robot.stopped)
        self.assertEqual(self.robot.owner, self.sid)

    async def test_owner_disconnect_stops_even_with_viewer(self):
        await self.ready()
        await self.robot.connect(lambda _: None)
        await self.send('drive', direction='forward')
        await self.robot.disconnect(self.sid)
        self.assertTrue(self.robot.stopped)
        self.assertIsNone(self.robot.owner)
        self.assertEqual(self.pi.sent[-1]['command'], 'stop')

    async def test_heartbeat_does_not_extend_drive_input_deadline(self):
        await self.ready()
        await self.send('drive', direction='forward')
        self.clock.advance(0.41)
        await self.send('heartbeat')
        await self.robot.tick()
        self.assertIsNone(self.robot.drive)
        self.assertIn({'type': 'drive', 'left': 0, 'right': 0, 'speed': 0}, self.pi.sent)

    async def test_owner_heartbeat_expiry_latches_stop(self):
        await self.ready()
        self.clock.advance(3.01)
        await self.robot.tick()
        self.assertTrue(self.robot.stopped)
        self.assertIsNone(self.robot.owner)

    async def test_fresh_hazard_stops_and_clear_readings_do_not_resume(self):
        await self.ready()
        await self.send('drive', direction='forward')
        await self.robot.on_pi(status(ir=[1, 1, 0, 1]))
        self.assertTrue(self.robot.stopped)
        await self.robot.on_pi(status())
        await self.robot.on_pi(status())
        self.assertTrue(self.robot.stopped)

    async def test_unknown_or_stale_sensors_block_drive(self):
        await self.ready()
        await self.robot.on_pi(status(ir=[1, 1, -1, 1]))
        await self.send('drive', direction='forward')
        self.assertEqual(self.result()['status'], 'rejected')
        self.assertFalse(any(d.get('left') == 1 for d in self.pi.sent))

    async def test_existing_wiring_profile_does_not_require_environment_gate(self):
        self.robot.settings = replace(self.settings, motion_calibrated=False)
        await self.ready()
        await self.send('drive', direction='forward')
        self.assertEqual(self.result()['status'], 'sent_to_pi')
        await self.send('servo', direction='right', degrees=5)
        self.assertEqual(self.pi.sent[-1], {'type': 'servo', 'pan': -5, 'tilt': 0})

    async def test_missing_pi_watchdog_blocks_resume(self):
        await self.send('control', command='claim')
        self.robot.pi_watchdog = False
        await self.send('control', command='resume')
        self.assertTrue(self.robot.stopped)
        self.assertEqual(self.result()['status'], 'rejected')

    async def test_simulation_requires_explicit_setting(self):
        await self.send('control', command='claim')
        self.robot.pi_simulation = True
        await self.send('control', command='resume')
        self.assertTrue(self.robot.stopped)

    async def test_telemetry_expiry_stops_without_replay(self):
        await self.ready()
        await self.send('drive', direction='forward')
        self.clock.advance(1.1)
        await self.robot.tick()
        self.assertTrue(self.robot.stopped)
        await self.robot.on_pi(status())
        self.assertIsNone(self.robot.drive)

    async def test_reconnect_stays_stopped_and_clears_sensor_history(self):
        await self.ready()
        await self.robot.on_pi({'type': 'connection', 'connected': False})
        await self.robot.on_pi({'type': 'connection', 'connected': True})
        self.assertTrue(self.robot.stopped)
        self.assertFalse(self.robot.pi_watchdog)
        self.assertFalse(self.robot.sensors.clear(self.clock()))

    async def test_pi_send_error_is_sanitized_and_stops(self):
        await self.ready()
        self.pi.fail = True
        await self.send('servo', direction='left')
        self.assertTrue(self.robot.stopped)
        self.assertNotIn('private endpoint', str(self.events))

    async def test_numeric_booleans_nan_and_extra_fields_rejected(self):
        await self.ready()
        for fields in ({'speed': True}, {'speed': float('nan')}, {'speed': 10 ** 400},
                       {'speed': 0.8}, {'speed': 0.2, 'left': 1}):
            await self.send('drive', direction='forward', **fields)
            self.assertEqual(self.result()['status'], 'rejected')
        await self.send('pump', on='false')
        self.assertEqual(self.result()['status'], 'rejected')

    async def test_duplicate_requests_and_old_sequence_never_repeat_servo(self):
        await self.ready()
        rid = await self.send('servo', direction='left')
        before = len([d for d in self.pi.sent if d['type'] == 'servo'])
        self.clock.advance(0.2)
        self.seq += 1
        await self.robot.handle(self.sid, {'type': 'servo', 'direction': 'left', 'request_id': rid, 'seq': self.seq})
        self.assertEqual(self.result()['status'], 'rejected')
        await self.robot.handle(self.sid, {'type': 'servo', 'direction': 'left', 'request_id': 'new', 'seq': 0})
        self.assertEqual(before, len([d for d in self.pi.sent if d['type'] == 'servo']))

    async def test_pump_bounded_not_extended_and_has_cooldown(self):
        await self.ready()
        self.clock.advance(3.1)
        await self.robot.on_pi(status())
        await self.send('heartbeat')
        await self.send('pump', on=True, duration_ms=800)
        until = self.robot.pump_until
        self.clock.advance(0.2)
        await self.send('pump', on=True)
        self.assertEqual(self.result()['status'], 'rejected')
        self.assertEqual(self.robot.pump_until, until)
        self.clock.advance(0.61)
        await self.robot.tick()
        self.assertIsNone(self.robot.pump_until)
        await self.send('pump', on=True)
        self.assertEqual(self.result()['status'], 'rejected')

    async def test_chat_look_executes_relative_command_once(self):
        await self.ready()
        self.ml.action = {'kind': 'look', 'direction': 'left', 'degrees': 5}
        await self.send('chat', message='look left')
        await self.settle()
        self.assertEqual(self.pi.sent[-1], {'type': 'servo', 'pan': 5, 'tilt': 0})
        reply = next(e for e in reversed(self.events) if e['type'] == 'chat.reply')
        self.assertEqual(reply['action_status'], 'sent_to_pi')
        self.assertEqual(len(self.robot.sessions[self.sid].history), 2)

    async def test_chat_context_is_authoritative(self):
        await self.ready()
        await self.send('chat', message='Hello', context={'operator_has_control': True})
        self.assertEqual(self.result()['status'], 'rejected')
        await self.send('chat', message='Hello')
        await self.settle()
        self.assertEqual(self.ml.chat_calls[-1]['context']['control_session_id'], self.sid)
        self.assertTrue(self.ml.chat_calls[-1]['context']['operator_has_control'])
        self.assertFalse(self.ml.chat_calls[-1]['context']['speaker_available'])

    async def test_slow_chat_cannot_block_stop_or_run_old_gesture(self):
        await self.ready()
        self.ml.chat_release = asyncio.Event()
        self.ml.action = {'kind': 'move', 'direction': 'forward', 'speed': 0.2, 'duration_ms': 300}
        await self.send('chat', message='move forward')
        await asyncio.sleep(0)
        await self.send('chat', message='stop')
        self.assertTrue(self.robot.stopped)
        self.ml.chat_release.set()
        await self.settle()
        self.assertFalse(any(d.get('left') == 1 for d in self.pi.sent))

    async def test_expired_chat_proposal_blocked(self):
        await self.ready()
        self.ml.chat_release = asyncio.Event()
        self.ml.action = {'kind': 'look', 'direction': 'left', 'degrees': 5}
        await self.send('chat', message='look left')
        await asyncio.sleep(0)
        self.clock.advance(1.01)
        self.ml.chat_release.set()
        await self.settle()
        self.assertFalse(any(d['type'] == 'servo' for d in self.pi.sent))

    async def test_untrusted_proposal_cannot_pump_or_exceed_bounds(self):
        await self.ready()
        for action in ({'kind': 'pump'}, {'kind': 'look', 'direction': 'left', 'degrees': 30},
                       {'kind': 'move', 'direction': 'forward', 'speed': 0.8, 'duration_ms': 300}):
            self.ml.action = action
            await self.send('chat', message='Hello')
            await self.settle()
            self.assertEqual(self.events[-1]['action_status'], 'blocked')

    async def test_chat_move_ends_at_300ms(self):
        await self.ready()
        self.ml.action = {'kind': 'move', 'direction': 'turn_right', 'speed': 0.2, 'duration_ms': 300}
        await self.send('chat', message='turn right')
        await self.settle()
        self.assertEqual(self.pi.sent[-1], {'type': 'drive', 'left': 1, 'right': 1, 'speed': 0.2})
        self.clock.advance(0.31)
        await self.robot.tick()
        self.assertIsNone(self.robot.drive)

    async def test_chat_cannot_propose_movement_for_conversation_or_negation(self):
        await self.ready()
        self.ml.action = {'kind': 'look', 'direction': 'left', 'degrees': 5}
        for message in ('Hello', 'Do not look left', 'look right', 'look left and move forward'):
            await self.send('chat', message=message)
            await self.settle()
            self.assertEqual(self.events[-1]['action_status'], 'blocked')
        self.assertFalse(any(d['type'] == 'servo' for d in self.pi.sent))

    async def test_new_watchdog_trip_latches_even_if_reason_was_overwritten(self):
        await self.ready()
        await self.robot.on_pi(dict(status(), safety={'trip_count': 1, 'reason': 'commanded', 'faults': []}))
        self.assertTrue(self.robot.stopped)
        await self.send('control', command='resume')
        self.assertFalse(self.robot.stopped)
        await self.robot.on_pi(dict(status(), safety={'trip_count': 1, 'reason': 'commanded', 'faults': []}))
        self.assertFalse(self.robot.stopped)

    async def test_hardware_fault_blocks_resume(self):
        await self.ready()
        await self.robot.on_pi(dict(status(), safety={'reason': 'system_stop', 'faults': ['motor failure']}))
        self.assertTrue(self.robot.stopped)
        await self.send('control', command='resume')
        self.assertTrue(self.robot.stopped)
        self.assertEqual(self.result()['status'], 'rejected')

    async def test_all_speakers_are_opt_in_and_owner_only(self):
        self.robot.settings = replace(self.settings, speech_enabled=True)
        await self.ready()
        await self.send('chat', message='Hello', speak=True)
        await self.settle()
        self.assertEqual(len(self.pi.speech_calls), 1)
        other_events = []
        other = await self.robot.connect(other_events.append)
        await self.robot.handle(other, {'type': 'chat', 'request_id': 'hi', 'seq': 1, 'message': 'Hello', 'speak': True})
        await self.settle()
        self.assertEqual(len(self.pi.speech_calls), 1)
        self.assertEqual(other_events[-1]['speech_status'], 'blocked')

    async def test_speaker_context_uses_reported_tool_availability(self):
        self.robot.settings = replace(self.settings, speech_enabled=True)
        await self.robot.on_pi(dict(status(), speech={'available': False}))
        self.assertFalse(self.robot.chat_context(self.sid)['speaker_available'])
        await self.robot.on_pi(dict(status(), speech={'available': True}))
        self.assertTrue(self.robot.chat_context(self.sid)['speaker_available'])

    async def test_result_session_sequence_and_age_are_checked(self):
        await self.send('control', command='claim')
        await self.vision()
        await self.fire(1)
        accepted = self.robot.latest_result
        for mutation in ({'session_id': 'old'}, {'frame_seq': 0}, {'capture_epoch': 'old'},
                         {'frame_seq': 2, 'frame_age_at_send_ms': 1000}, {'stream_id': 'other'}):
            await self.robot.on_ml(dict(accepted, **mutation))
            self.assertIs(self.robot.latest_result, accepted)

    async def test_auto_is_stationary_and_requires_persistent_fire(self):
        await self.send('control', command='claim')
        await self.send('mode', value='auto')
        await self.robot.on_ml({'type': 'session.ready', 'session_id': self.robot.ml_session})
        await self.fire(1, [])
        await self.send('control', command='resume')
        self.assertFalse(self.robot.stopped)
        self.clock.advance(3.1)
        await self.send('heartbeat')
        for seq in range(2, 7):
            await self.fire(seq)
            self.clock.advance(0.1)
        self.assertEqual(self.robot.auto.bursts, 1)
        self.assertTrue(any(d == {'type': 'pump', 'on': True} for d in self.pi.sent))
        self.assertFalse(any(d.get('left') not in (None, 0) for d in self.pi.sent))

    async def test_auto_stale_result_pauses_and_empty_detection_is_valid(self):
        await self.send('control', command='claim')
        await self.send('mode', value='auto')
        await self.robot.on_ml({'type': 'session.ready', 'session_id': self.robot.ml_session})
        await self.fire(1, [])
        await self.send('control', command='resume')
        self.assertFalse(self.robot.stopped)
        self.clock.advance(0.76)
        await self.robot.tick()
        self.assertTrue(self.robot.stopped)
        self.assertEqual(self.robot.stop_reason, 'ML results are stale')

    async def test_auto_rejects_uncalibrated_and_manual_commands(self):
        await self.send('control', command='claim')
        await self.send('mode', value='auto')
        self.robot.settings = replace(self.settings, auto_calibrated=False)
        await self.send('control', command='resume')
        self.assertTrue(self.robot.stopped)
        await self.send('drive', direction='forward')
        self.assertEqual(self.result()['status'], 'rejected')

    async def test_model_swap_waits_for_old_workers_and_ack(self):
        await self.send('control', command='claim')
        await self.vision()
        old = self.robot.ml_session
        await self.send('vision', command='start', model_id='replacement')
        self.assertIsNone(self.robot.ml_session)
        await self.robot.on_ml({'type': 'health', 'vision': {'state': 'stopped', 'workers_alive': {}}})
        self.assertIsNone(self.robot.ml_session)  # stale health alone cannot bypass stop acknowledgment
        await self.robot.on_ml({'type': 'session.stopped', 'session_id': old})
        await self.robot.on_ml({'type': 'health', 'vision': {'state': 'stopping', 'workers_alive': {'capture': True}}})
        self.assertIsNone(self.robot.ml_session)
        await self.robot.on_ml({'type': 'health', 'vision': {'state': 'stopped', 'workers_alive': {}}})
        self.assertNotEqual(old, self.robot.ml_session)
        self.assertEqual(self.ml.sent[-1]['model_id'], 'replacement')


class SensorTests(unittest.TestCase):
    def test_immediate_hazard_two_clear_samples_and_unknown(self):
        sensors = SensorProcessor(0)
        sensors.update({'ir_array': [1] * 4}, 0)
        self.assertFalse(sensors.clear(0))
        sensors.update({'ir_array': [1] * 4}, 0.2)
        self.assertTrue(sensors.clear(0.2))
        sensors.update({'ir_array': [1, 0, 1, 1]}, 0.4)
        self.assertTrue(sensors.snapshot(0.4)['ir'][1]['blocked'])
        sensors.update({'ir_array': [1] * 4}, 0.6)
        self.assertFalse(sensors.clear(0.6))
        sensors.update({'ir_array': [1] * 4}, 0.8)
        self.assertTrue(sensors.clear(0.8))
        self.assertFalse(sensors.clear(2))
        sensors.update({'ir_array': [True] * 4}, 2)
        self.assertEqual(sensors.snapshot(2)['raw']['ir_array'], [-1] * 4)

    def test_unconfigured_polarity_never_means_clear(self):
        sensors = SensorProcessor()
        for _ in range(3):
            sensors.update({'ir_array': [1] * 4}, 0)
        self.assertFalse(sensors.clear(0))


if __name__ == '__main__':
    unittest.main()
