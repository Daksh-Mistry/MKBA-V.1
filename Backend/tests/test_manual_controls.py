"""Operator controls with a partial robot, using fake adapters and a fake clock."""
import asyncio
import unittest

from Backend.config import Settings
from Backend.controller import RobotController
from Backend.tests.test_controller import Clock, FakeML, FakePi
from Backend.tests.test_partial_hardware import partial_status


class ManualControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock, self.pi, self.ml = Clock(), FakePi(), FakeML()
        self.robot = RobotController(Settings(auto_calibrated=True), pi=self.pi,
                                     ml=self.ml, clock=self.clock)
        await self.pi.start(self.robot.on_pi)
        await self.ml.start(self.robot.on_ml)
        await self.robot.on_pi({'type': 'hello', 'capabilities': {
            'watchdog': True, 'partial_hardware': True, 'simulation': False}})
        self.events, self.seq = [], 0
        self.sid = await self.robot.connect(self.events.append)
        await self.telemetry()

    async def asyncTearDown(self):
        await self.robot.close()

    async def send(self, kind, **fields):
        self.seq += 1
        rid = f'manual-{self.seq}'
        await self.robot.handle(self.sid, {
            'type': kind, 'request_id': rid, 'seq': self.seq, **fields})
        return next((event for event in reversed(self.events)
                     if event.get('type') == 'command_result'
                     and event.get('request_id') == rid), None)

    async def telemetry(self, **fields):
        await self.robot.on_pi(partial_status(**fields))

    async def enable(self):
        result = await self.send('control', command='enable')
        self.assertEqual(result['status'], 'completed', result)

    async def advance(self, seconds, **telemetry):
        self.clock.advance(seconds)
        await self.send('heartbeat')
        await self.telemetry(**telemetry)

    def motor_outputs(self):
        return [command for command in self.pi.sent if command['type'] == 'drive']

    async def test_enable_claims_and_resumes_without_starting_outputs(self):
        before = list(self.pi.sent)
        await self.enable()
        state = self.robot.snapshot()
        self.assertEqual(state['owner_session_id'], self.sid)
        self.assertFalse(state['stopped'])
        self.assertFalse(state['drive_active'])
        self.assertEqual(self.pi.sent, before)
        await self.enable()  # The same operator may safely click it again.
        self.assertEqual(self.pi.sent, before)

    async def test_failed_enable_does_not_claim_a_disconnected_robot(self):
        await self.robot.on_pi({'type': 'connection', 'connected': False})
        result = await self.send('control', command='enable')
        self.assertEqual(result['status'], 'rejected')
        self.assertIsNone(self.robot.snapshot()['owner_session_id'])
        self.assertTrue(self.robot.snapshot()['stopped'])

    async def test_failed_enable_does_not_claim_stale_or_invalid_pi_status(self):
        self.clock.advance(1.01)
        result = await self.send('control', command='enable')
        self.assertEqual(result['status'], 'rejected')
        self.assertIsNone(self.robot.snapshot()['owner_session_id'])
        await self.telemetry()
        await self.robot.on_pi({'type': 'hello', 'capabilities': {
            'watchdog': False, 'partial_hardware': True}})
        result = await self.send('control', command='enable')
        self.assertEqual(result['status'], 'rejected')
        self.assertIsNone(self.robot.snapshot()['owner_session_id'])
        self.assertTrue(self.robot.snapshot()['stopped'])

    async def test_enable_cannot_steal_another_operators_control(self):
        await self.enable()
        events = []
        other = await self.robot.connect(events.append)
        before = list(self.pi.sent)
        await self.robot.handle(other, {'type': 'control', 'command': 'enable',
                                       'seq': 1, 'request_id': 'other-enable'})
        self.assertEqual(events[-1]['status'], 'rejected')
        self.assertEqual(self.robot.snapshot()['owner_session_id'], self.sid)
        self.assertFalse(self.robot.snapshot()['stopped'])
        self.assertEqual(self.pi.sent, before)

    async def test_manual_drive_with_missing_ir_caps_requested_speed(self):
        await self.telemetry(missing=('sensors',))
        await self.enable()
        readiness = self.robot.snapshot()['readiness']['drive']
        self.assertTrue(readiness['available'])
        self.assertTrue(readiness['limited'])
        self.assertEqual(readiness['max_speed'], 0.2)
        self.assertEqual(readiness['max_hold_ms'], 2000)
        result = await self.send('drive', direction='forward', speed=0.6)
        self.assertEqual(result['status'], 'sent_to_pi')
        self.assertEqual(self.motor_outputs()[-1], {
            'type': 'drive', 'left': 1, 'right': -1, 'speed': 0.2})
        await self.advance(0.1, missing=('sensors',))
        await self.robot.tick()
        self.assertTrue(self.robot.snapshot()['drive_active'])
        self.assertFalse(self.robot.snapshot()['stopped'])

    async def test_missing_motor_driver_still_blocks_manual_drive(self):
        await self.telemetry(missing=('motors', 'sensors'))
        await self.enable()
        self.assertFalse(self.robot.snapshot()['readiness']['drive']['available'])
        result = await self.send('drive', direction='forward', speed=0.2)
        self.assertEqual(result['status'], 'rejected')
        self.assertFalse(self.motor_outputs())

    async def test_repeated_updates_and_direction_changes_cannot_extend_limited_hold(self):
        await self.enable()
        await self.send('drive', direction='forward', speed=0.6)
        # Simulate a held key, with fresh telemetry and operator heartbeat.
        # Changing direction is still part of this hold, not a fresh test.
        for index in range(1, 10):
            await self.advance(0.2)
            result = await self.send('drive', direction='left' if index % 2 else 'forward', speed=0.5)
            self.assertEqual(result['status'], 'sent_to_pi', result)
            await self.robot.tick()
        await self.advance(0.21)
        await self.robot.tick()
        self.assertFalse(self.robot.snapshot()['drive_active'])
        self.assertTrue(self.robot.snapshot()['readiness']['drive']['requires_release'])
        self.assertEqual(self.motor_outputs()[-1], {
            'type': 'drive', 'left': 0, 'right': 0, 'speed': 0})
        moving_before = sum(command['speed'] > 0 for command in self.motor_outputs())
        result = await self.send('drive', direction='backward', speed=0.2)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(sum(command['speed'] > 0 for command in self.motor_outputs()), moving_before)
        self.assertFalse(self.robot.snapshot()['drive_active'])
        await self.send('drive', direction='stop')
        result = await self.send('drive', direction='backward', speed=0.2)
        self.assertEqual(result['status'], 'sent_to_pi')
        self.assertTrue(self.robot.snapshot()['drive_active'])

    async def test_limited_input_timeout_requires_release_even_with_fresh_heartbeat(self):
        await self.enable()
        await self.send('drive', direction='forward')
        await self.advance(0.41)
        await self.robot.tick()
        self.assertFalse(self.robot.snapshot()['drive_active'])
        self.assertTrue(self.robot.snapshot()['readiness']['drive']['requires_release'])
        self.assertEqual((await self.send('drive', direction='forward'))['status'], 'rejected')
        await self.send('drive', direction='stop')
        self.assertEqual((await self.send('drive', direction='forward'))['status'], 'sent_to_pi')

    async def test_late_drive_update_cannot_revive_expired_input_before_timer_runs(self):
        await self.enable()
        await self.send('drive', direction='forward')
        await self.advance(0.41)
        # An incoming update can reach the controller just before its next tick.
        result = await self.send('drive', direction='left')
        self.assertEqual(result['status'], 'rejected')
        self.assertFalse(self.robot.snapshot()['drive_active'])
        self.assertTrue(self.robot.snapshot()['readiness']['drive']['requires_release'])
        self.assertEqual(self.motor_outputs()[-1], {
            'type': 'drive', 'left': 0, 'right': 0, 'speed': 0})
        await self.send('drive', direction='stop')
        self.assertEqual((await self.send('drive', direction='left'))['status'], 'sent_to_pi')

    async def test_ir_becoming_verified_cannot_remove_an_existing_hold_limit(self):
        await self.enable()
        await self.send('drive', direction='forward', speed=0.5)
        for _ in range(9):
            await self.advance(0.2, changes=2)
            await self.send('drive', direction='forward', speed=0.5)
            self.assertEqual(self.motor_outputs()[-1]['speed'], 0.2)
            await self.robot.tick()
        await self.advance(0.21, changes=2)
        await self.robot.tick()
        self.assertFalse(self.robot.snapshot()['drive_active'])
        self.assertEqual((await self.send('drive', direction='forward'))['status'], 'rejected')
        await self.send('drive', direction='stop')
        self.assertEqual((await self.send('drive', direction='forward', speed=0.5))['status'], 'sent_to_pi')
        self.assertEqual(self.motor_outputs()[-1]['speed'], 0.5)

    async def test_timeout_rejects_a_new_update_even_before_timer_runs(self):
        await self.enable()
        await self.send('drive', direction='forward')
        for _ in range(9):
            await self.advance(0.2)
            await self.send('drive', direction='forward')
        await self.advance(0.21)
        result = await self.send('drive', direction='forward')
        self.assertEqual(result['status'], 'rejected')
        self.assertFalse(self.robot.snapshot()['drive_active'])
        self.assertEqual(self.motor_outputs()[-1]['speed'], 0)
        await self.send('drive', direction='forward', speed=0)
        result = await self.send('drive', direction='forward', speed=0.1)
        self.assertEqual(result['status'], 'sent_to_pi')
        self.assertEqual(self.motor_outputs()[-1]['speed'], 0.1)

    async def test_known_verified_blocked_ir_is_not_bypassed_by_missing_inputs(self):
        data = partial_status(ir=[0, -1, -1, -1])
        data['hardware']['sensors']['channels']['ir_array'][0]['changes'] = 2
        await self.robot.on_pi(data)
        await self.enable()
        self.assertFalse(self.robot.snapshot()['readiness']['drive']['available'])
        result = await self.send('drive', direction='forward')
        self.assertEqual(result['status'], 'rejected')
        self.assertFalse(self.motor_outputs())

    async def test_new_verified_hazard_stops_an_active_limited_test(self):
        await self.enable()
        await self.send('drive', direction='forward')
        await self.telemetry(ir=[0, 1, 1, 1], changes=2)
        self.assertTrue(self.robot.snapshot()['stopped'])
        self.assertFalse(self.robot.snapshot()['drive_active'])
        self.assertEqual(self.pi.sent[-1], {'type': 'system', 'command': 'stop'})

    async def test_stale_pi_telemetry_stops_limited_drive(self):
        await self.enable()
        await self.send('drive', direction='forward')
        self.clock.advance(1.01)
        await self.send('heartbeat')
        await self.robot.tick()
        self.assertTrue(self.robot.snapshot()['stopped'])
        self.assertFalse(self.robot.snapshot()['drive_active'])
        self.assertEqual(self.robot.snapshot()['stop_reason'], 'Pi telemetry is stale')

    async def test_normal_drive_stops_when_a_verified_ir_channel_becomes_unavailable(self):
        await self.telemetry(changes=2)
        await self.telemetry(changes=2)
        await self.enable()
        await self.send('drive', direction='forward', speed=0.5)
        await self.telemetry(ir=[1, 1, -1, 1], changes=2)
        self.assertTrue(self.robot.snapshot()['stopped'])
        self.assertFalse(self.robot.snapshot()['drive_active'])

    async def test_verified_clear_ir_allows_normal_hold_beyond_two_seconds(self):
        await self.telemetry(changes=2)
        await self.telemetry(changes=2)
        await self.enable()
        for _ in range(13):
            result = await self.send('drive', direction='forward', speed=0.5)
            self.assertEqual(result['status'], 'sent_to_pi')
            self.assertEqual(self.motor_outputs()[-1]['speed'], 0.5)
            await self.advance(0.2, changes=2)
            await self.robot.tick()
        self.assertTrue(self.robot.snapshot()['drive_active'])

    async def test_pump_requires_enable_and_preserves_burst_limit_and_cooldown(self):
        self.assertEqual((await self.send('pump', on=True))['status'], 'rejected')
        await self.enable()
        await self.advance(3.01)
        self.assertTrue(self.robot.snapshot()['readiness']['pump']['available'])
        self.assertEqual((await self.send('pump', on=True, duration_ms=300))['status'], 'sent_to_pi')
        self.assertEqual(self.pi.sent[-1], {'type': 'pump', 'on': True})
        self.assertFalse(self.robot.snapshot()['readiness']['pump']['available'])
        self.assertEqual((await self.send('pump', on=True, duration_ms=1000))['status'], 'rejected')
        await self.advance(0.31)
        await self.robot.tick()
        self.assertIn({'type': 'pump', 'on': False}, self.pi.sent)
        cooldown = self.robot.snapshot()['readiness']['pump']
        self.assertFalse(cooldown['available'])
        self.assertIn('cool', cooldown['reason'].lower())
        self.assertEqual(cooldown['cooldown_ms'], 3000)
        self.assertEqual((await self.send('pump', on=True))['status'], 'rejected')
        await self.advance(3.01)
        self.assertTrue(self.robot.snapshot()['readiness']['pump']['available'])
        self.assertEqual(self.robot.snapshot()['readiness']['pump']['cooldown_ms'], 0)
        self.assertEqual((await self.send('pump', on=True))['status'], 'sent_to_pi')

    async def test_auto_enable_still_requires_verified_ir_and_preserves_unowned_state_on_failure(self):
        await self.enable()
        await self.send('mode', value='auto')
        await self.send('control', command='release')
        result = await self.send('control', command='enable')
        self.assertEqual(result['status'], 'rejected')
        self.assertIn('IR', result['message'])
        self.assertIsNone(self.robot.snapshot()['owner_session_id'])
        self.assertTrue(self.robot.snapshot()['stopped'])

    async def test_unowned_auto_can_return_to_manual_without_resuming_outputs(self):
        for leave in ('release', 'disconnect'):
            with self.subTest(leave=leave):
                await self.enable()
                await self.send('mode', value='auto')
                if leave == 'release':
                    await self.send('control', command='release')
                else:
                    await self.robot.disconnect(self.sid)
                    self.sid = await self.robot.connect(self.events.append)
                result = await self.send('control', command='enable')
                self.assertEqual(result['status'], 'rejected')
                self.assertIsNone(self.robot.snapshot()['owner_session_id'])
                before = len(self.pi.sent)
                result = await self.send('mode', value='manual')
                self.assertEqual(result['status'], 'sent_to_pi')
                state = self.robot.snapshot()
                self.assertEqual(state['mode'], 'manual')
                self.assertEqual(state['owner_session_id'], self.sid)
                self.assertTrue(state['stopped'])
                self.assertFalse(state['drive_active'])
                self.assertEqual(self.pi.sent[before:], [
                    {'type': 'system', 'command': 'stop'},
                    {'type': 'mode', 'value': 'manual'}])
                before = list(self.pi.sent)
                await self.enable()
                self.assertEqual(self.pi.sent, before)
                self.assertFalse(self.robot.snapshot()['stopped'])

    async def test_manual_mode_cannot_steal_control_or_claim_an_offline_pi(self):
        await self.enable()
        await self.send('mode', value='auto')
        other_events = []
        other = await self.robot.connect(other_events.append)
        before = list(self.pi.sent)
        await self.robot.handle(other, {'type': 'mode', 'value': 'manual',
                                       'seq': 1, 'request_id': 'other-manual'})
        self.assertEqual(other_events[-1]['status'], 'rejected')
        self.assertEqual(self.robot.snapshot()['owner_session_id'], self.sid)
        self.assertEqual(self.robot.snapshot()['mode'], 'auto')
        self.assertEqual(self.pi.sent, before)
        await self.robot.disconnect(self.sid)
        await self.robot.on_pi({'type': 'connection', 'connected': False})
        before = list(self.pi.sent)
        await self.robot.handle(other, {'type': 'mode', 'value': 'manual',
                                       'seq': 2, 'request_id': 'offline-manual'})
        self.assertEqual(other_events[-1]['status'], 'rejected')
        self.assertIsNone(self.robot.snapshot()['owner_session_id'])
        self.assertTrue(self.robot.snapshot()['stopped'])
        self.assertEqual(self.pi.sent, before)

    async def test_chat_move_cannot_use_limited_manual_drive_permission(self):
        await self.enable()
        self.ml.action = {'kind': 'move', 'direction': 'forward', 'speed': 0.2, 'duration_ms': 300}
        await self.send('chat', message='move forward')
        await asyncio.gather(*list(self.robot.tasks))
        reply = next(event for event in reversed(self.events) if event['type'] == 'chat.reply')
        self.assertEqual(reply['action_status'], 'blocked')
        self.assertFalse(any(command['speed'] > 0 for command in self.motor_outputs()))


if __name__ == '__main__':
    unittest.main()
