import asyncio
import os
import unittest
from unittest.mock import patch

from Backend.config import Settings
from Backend.controller import RobotController
from Backend.tests.test_controller import Clock, FakeML, FakePi, status


def partial_status(*, missing=(), ir=None, changes=0, faults=None, trip=0):
    hardware = {name: {'state': 'unavailable' if name in missing else 'available',
                       'available': name not in missing,
                       'reason': 'GPIO driver unavailable' if name in missing else None}
                for name in ('motors', 'servos', 'pump', 'sensors')}
    hardware['sensors']['channels'] = {
        group: [{'state': 'available', 'available': 'sensors' not in missing,
                 'changes': changes, 'evidence': 'signal_changed' if changes else 'steady_signal'} for _ in range(4)]
        for group in ('ir_array', 'flame_array')}
    result = status(ir=ir, pan=None if 'servos' in missing else 90,
                    tilt=None if 'servos' in missing else 90, pump=None if 'pump' in missing else False)
    result.update(hardware=hardware, safety={'reason': 'system_stop', 'trip_count': trip,
                                            'faults': faults or [], 'control_lease_valid': True})
    return result


class PartialHardwareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock, self.pi, self.ml = Clock(), FakePi(), FakeML()
        self.robot = RobotController(Settings(), pi=self.pi, ml=self.ml, clock=self.clock)
        self.events, self.seq = [], 0
        await self.pi.start(self.robot.on_pi)
        await self.ml.start(self.robot.on_ml)
        await self.robot.on_pi({'type': 'hello', 'capabilities': {
            'watchdog': True, 'simulation': False, 'speech': True, 'partial_hardware': True}})
        self.sid = await self.robot.connect(self.events.append)

    async def asyncTearDown(self):
        await self.robot.close()

    async def send(self, kind, **fields):
        self.seq += 1
        await self.robot.handle(self.sid, {'type': kind, 'seq': self.seq, 'request_id': f'p-{self.seq}', **fields})
        return next((e for e in reversed(self.events) if e['type'] == 'command_result'), {})

    async def resume(self):
        await self.send('control', command='claim')
        return await self.send('control', command='resume')

    async def test_real_pi_null_status_keeps_connection_and_reports_independent_failures(self):
        await self.robot.on_pi(partial_status(missing=('motors', 'servos', 'pump', 'sensors')))
        snapshot = self.robot.snapshot()
        self.assertTrue(snapshot['pi']['connected'])
        self.assertEqual(snapshot['pi']['age_ms'], 0)
        self.assertEqual(snapshot['servos'], {'pan': None, 'tilt': None})
        self.assertIsNone(snapshot['pump'])
        self.assertEqual(snapshot['sensors']['raw']['ir_array'], [-1] * 4)
        self.assertFalse(any(snapshot['readiness'][key]['available'] for key in ('drive', 'servo', 'pump', 'auto')))
        self.assertEqual((await self.resume())['status'], 'completed')
        for kind, fields in [('servo', {'direction': 'left'}), ('pump', {'on': True}), ('drive', {'direction': 'forward'})]:
            result = await self.send(kind, **fields)
            self.assertEqual(result['status'], 'rejected')
            self.assertIn('unavailable', result['message'])
        self.assertFalse(any(p['type'] in {'servo', 'drive', 'pump'} for p in self.pi.sent))

    async def test_healthy_face_and_pump_work_when_motors_and_sensors_are_missing(self):
        await self.robot.on_pi(partial_status(missing=('motors', 'sensors')))
        await self.resume()
        self.assertEqual((await self.send('servo', direction='left'))['status'], 'sent_to_pi')
        self.clock.advance(3.1)
        await self.send('heartbeat')
        await self.robot.on_pi(partial_status(missing=('motors', 'sensors')))
        self.assertEqual((await self.send('pump', on=True))['status'], 'sent_to_pi')
        self.assertEqual(self.pi.sent[-1], {'type': 'pump', 'on': True})
        self.clock.advance(0.81)
        await self.robot.tick()
        self.assertIn({'type': 'pump', 'on': False}, self.pi.sent)

    async def test_pullup_allows_only_limited_manual_test_until_all_signals_verified(self):
        for _ in range(3):
            await self.robot.on_pi(partial_status())
        await self.resume()
        self.assertTrue(self.robot.readiness()['drive']['available'])
        self.assertTrue(self.robot.readiness()['drive']['limited'])
        with self.assertRaises(ValueError):
            self.robot._motion_ready()  # Chat movement still requires real signal evidence.
        self.assertEqual((await self.send('drive', direction='forward', speed=0.6))['status'], 'sent_to_pi')
        self.assertEqual(self.pi.sent[-1]['speed'], 0.2)
        await self.send('drive', direction='stop')
        await self.robot.on_pi(partial_status(ir=[0, 0, 0, 1]))
        await self.robot.on_pi(partial_status())
        await self.robot.on_pi(partial_status())
        self.assertTrue(self.robot.readiness()['drive']['limited'])
        await self.robot.on_pi(partial_status(ir=[1, 1, 1, 0]))
        await self.robot.on_pi(partial_status())
        await self.robot.on_pi(partial_status())
        self.assertTrue(self.robot.readiness()['drive']['available'])
        self.assertFalse(self.robot.readiness()['drive']['limited'])
        self.assertEqual((await self.send('drive', direction='forward'))['status'], 'sent_to_pi')

    async def test_pi_boot_signal_history_is_retained_but_invalid_channels_limit_manual_drive(self):
        await self.robot.on_pi(partial_status(changes=2))
        await self.robot.on_pi(partial_status(changes=2))
        self.assertTrue(self.robot.readiness()['drive']['available'])
        data = partial_status(changes=2)
        data['hardware']['sensors']['channels']['ir_array'][2]['available'] = False
        await self.robot.on_pi(data)
        self.assertTrue(self.robot.readiness()['drive']['available'])
        self.assertTrue(self.robot.readiness()['drive']['limited'])
        self.assertEqual(self.robot.snapshot()['sensors']['raw']['ir_array'][2], -1)

    async def test_isolated_failed_part_stops_then_healthy_part_can_resume(self):
        await self.robot.on_pi(partial_status(changes=2))
        await self.resume()
        await self.robot.on_pi(partial_status(missing=('motors',), faults=['motors unavailable: GPIO write failed'], trip=1))
        self.assertTrue(self.robot.stopped)
        self.assertFalse(self.robot.pi_fault)
        self.assertTrue(self.robot.snapshot()['pi']['safety']['component_faults'])
        self.assertEqual((await self.send('control', command='resume'))['status'], 'completed')
        self.assertEqual((await self.send('servo', direction='right'))['status'], 'sent_to_pi')
        await self.robot.on_pi(partial_status(missing=('motors',), faults=['Unexpected telemetry serialization error']))
        self.assertEqual((await self.send('control', command='resume'))['status'], 'rejected')

    async def test_unavailable_component_blocks_even_a_valid_chat_proposal(self):
        await self.robot.on_pi(partial_status(missing=('servos',)))
        await self.resume()
        self.ml.action = {'kind': 'look', 'direction': 'left', 'degrees': 5}
        await self.send('chat', message='look left')
        await asyncio.gather(*list(self.robot.tasks))
        reply = next(e for e in reversed(self.events) if e['type'] == 'chat.reply')
        self.assertEqual(reply['action_status'], 'blocked')
        self.assertIn('Servos unavailable', reply['text'])
        self.assertFalse(any(p['type'] == 'servo' for p in self.pi.sent))

    async def test_alignment_is_owner_only_stopped_and_never_survives_reconnect(self):
        await self.robot.on_pi(partial_status())
        self.assertEqual((await self.send('readiness', command='confirm_alignment'))['status'], 'rejected')
        await self.resume()
        self.assertEqual((await self.send('readiness', command='confirm_alignment'))['status'], 'rejected')
        await self.send('system', command='stop')
        self.assertEqual((await self.send('readiness', command='confirm_alignment'))['status'], 'completed')
        self.assertTrue(self.robot.readiness()['alignment_confirmed'])
        self.assertFalse(self.robot.readiness()['auto']['available'])  # alignment cannot bypass IR/ML requirements
        await self.robot.on_pi({'type': 'connection', 'connected': False})
        self.assertFalse(self.robot.readiness()['alignment_confirmed'])

    async def test_null_from_available_component_invalidates_previous_fresh_status(self):
        await self.robot.on_pi(partial_status())
        data = partial_status()
        data['servos']['pan'] = None
        await self.robot.on_pi(data)
        self.assertIsNone(self.robot.pi_at)
        self.assertEqual((await self.resume())['status'], 'rejected')


class DefaultProfileTests(unittest.TestCase):
    def test_brand_new_environment_needs_no_manual_profile_or_speech_flags(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.ir_blocked_value, 0)
        self.assertTrue(settings.speech_enabled)
        self.assertFalse(settings.auto_calibrated)  # a file default cannot establish alignment
