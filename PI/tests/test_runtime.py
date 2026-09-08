"""Non-actuating tests. Real GPIO packages are never imported by this suite."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from audio import SpeechService
from server import RobotServerManager, create_app
from api import websocket as protocol
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


class DeadlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 0.0
        self.robot = RobotServerManager(simulation=True, clock=lambda: self.now)
        self.robot.control_connected()

    async def asyncTearDown(self):
        await self.robot.stop()

    async def test_heartbeat_cannot_keep_old_drive_moving(self):
        self.robot.drive(1, -1, 0.3)
        self.assertEqual(self.robot.speed, 0.3)
        self.now = 0.3
        self.robot.touch_control()
        self.now = 0.41
        self.robot.check_deadlines()
        self.assertEqual(self.robot.motors.left, 0)
        self.assertEqual(self.robot.safety_reason, "drive_timeout")
        self.assertTrue(self.robot.safety_status()["control_lease_valid"])

    async def test_control_loss_centers_stops_and_cancels_speech(self):
        self.robot.drive(1, 1, 0.3)
        self.robot.pump(True)
        self.robot.servos.set_pan_tilt(20, 10)
        self.robot.speech.submit("a", "hello")
        self.now = 1.01
        self.robot.check_deadlines()
        self.assertEqual(self.robot.motors.left, 0)
        self.assertFalse(self.robot.relay.state())
        self.assertEqual((self.robot.servos.pan.angle, self.robot.servos.tilt.angle), (90, 90))
        self.assertEqual(self.robot.safety_reason, "control_timeout")
        self.assertEqual(self.robot.safety_status()["trip_count"], 1)
        with self.assertRaises(ValueError):
            self.robot.touch_control()
        with self.assertRaises(ValueError):
            self.robot.drive(0, 0, 0)
        self.assertEqual(self.robot.safety_status()["trip_count"], 1)
        self.assertEqual(self.robot.safety_status()["last_trip_reason"], "control_timeout")
        await self.robot.speech.stop()
        self.assertEqual(self.robot.speech.status()["state"], "stopped")

    async def test_delayed_commands_cannot_revive_expired_connection(self):
        protocol.set_robot_reference(self.robot)
        self.robot.drive(1, -1, 0.2)
        self.robot.pump(True)
        self.robot.servos.set_pan_tilt(20, 10)
        self.now = 1.01
        # Do not call check_deadlines first: the dispatcher itself must detect
        # expiration before a late command has a chance to touch hardware.
        commands = [
            {"type": "drive", "left": 1, "right": -1, "speed": 0.2},
            {"type": "pump", "on": True}, {"type": "servo", "pan": 5},
            {"type": "heartbeat"}, {"type": "mode", "value": "auto"},
        ]
        for data in commands:
            ws = SimpleNamespace(send_text=AsyncMock(), close=AsyncMock())
            await protocol.dispatch_ws_message(ws, json.dumps(data))
            ws.close.assert_awaited_once()
            self.assertEqual(json.loads(ws.send_text.call_args.args[0])["code"], "control_lease_expired")
            self.assertIsNone(self.robot.last_control)
            self.assertEqual(self.robot.motors.left, 0)
            self.assertFalse(self.robot.relay.state())
            self.assertEqual((self.robot.servos.pan.angle, self.robot.servos.tilt.angle), (90, 90))
        self.assertEqual(self.robot.trip_count, 1)
        ws = SimpleNamespace(send_text=AsyncMock(), close=AsyncMock())
        await protocol.dispatch_ws_message(ws, json.dumps({"type": "system", "command": "stop"}))
        self.assertTrue(self.robot.control_expired)
        self.assertIsNone(self.robot.last_control)
        self.robot.shutdown_callback = Mock()
        await protocol.dispatch_ws_message(ws, json.dumps({"type": "system", "command": "shutdown"}))
        self.robot.shutdown_callback.assert_called_once()

    async def test_new_connection_is_stopped_and_can_get_fresh_lease(self):
        self.robot.drive(1, -1, 0.2)
        self.now = 1.01
        self.robot.check_deadlines()
        self.robot.control_disconnected()
        self.robot.control_connected()
        self.assertFalse(self.robot.control_expired)
        self.assertTrue(self.robot.safety_status()["control_lease_valid"])
        self.assertEqual(self.robot.motors.left, 0)
        self.assertFalse(self.robot.relay.state())
        self.assertEqual((self.robot.servos.pan.angle, self.robot.servos.tilt.angle), (90, 90))
        self.assertEqual(self.robot.trip_count, 1)

    async def test_closed_transport_does_not_become_telemetry_fault(self):
        self.now = 1.01
        self.robot.check_deadlines()
        ws = Mock()
        ws.send_text = AsyncMock(side_effect=RuntimeError("already closed"))
        ws.close = AsyncMock(side_effect=RuntimeError("already closed"))
        with patch.object(protocol, "_robot_ref", self.robot), patch.object(protocol, "_owner", ws), \
                patch.object(protocol, "active_websockets", {ws}):
            await protocol.broadcast_telemetry_once()
            self.assertFalse(protocol.active_websockets)
        self.assertEqual(self.robot.trip_count, 1)
        self.assertEqual(self.robot.last_trip_reason, "control_timeout")
        self.assertFalse(self.robot.faults)

    async def test_sensor_failure_remains_telemetry_fault(self):
        ws = Mock()
        self.robot.sensors.read = Mock(side_effect=RuntimeError("sensor failure"))
        with patch.object(protocol, "_robot_ref", self.robot), patch.object(protocol, "_owner", ws), \
                patch.object(protocol, "active_websockets", {ws}):
            await protocol.broadcast_telemetry_once()
        self.assertEqual(self.robot.trip_count, 1)
        self.assertEqual(self.robot.last_trip_reason, "telemetry_error")
        self.assertTrue(self.robot.control_expired)
        self.assertTrue(self.robot.faults)

    async def test_old_failed_transport_does_not_disconnect_new_owner(self):
        old, new = Mock(), Mock()
        old.close = AsyncMock(side_effect=RuntimeError("already closed"))

        async def replaced_owner(message):
            protocol._owner = new
            self.robot.control_connected()
            raise RuntimeError("old socket closed")

        old.send_text = replaced_owner
        with patch.object(protocol, "_robot_ref", self.robot), patch.object(protocol, "_owner", old), \
                patch.object(protocol, "active_websockets", {old}):
            await protocol.broadcast_telemetry_once()
            self.assertIs(protocol._owner, new)
        self.assertTrue(self.robot.connected)
        self.assertFalse(self.robot.control_expired)
        self.assertFalse(self.robot.faults)

    async def test_repeated_pump_on_does_not_extend_maximum(self):
        self.robot.pump(True)
        self.now = 0.8
        self.robot.pump(True)
        self.robot.touch_control()
        self.now = 1.01
        self.robot.check_deadlines()
        self.assertFalse(self.robot.relay.state())
        with self.assertRaises(ValueError):
            self.robot.pump(True)
        self.robot.pump(False)
        self.robot.pump(True)
        self.assertTrue(self.robot.relay.state())

    async def test_all_cleanup_attempted_if_motor_stop_fails(self):
        self.robot.motors.stop = Mock(side_effect=RuntimeError("test motor failure"))
        self.robot.motors.shutdown = Mock()
        self.robot.relay.pump_off = Mock()
        self.robot.servos.center = Mock()
        await self.robot.stop()
        self.robot.relay.pump_off.assert_called_once()
        self.robot.servos.center.assert_called_once()
        self.robot.motors.shutdown.assert_called_once()
        self.assertTrue(self.robot.faults)
        self.assertTrue(self.robot.control_expired)

    async def test_shutdown_requests_script_exit(self):
        self.robot.shutdown_callback = Mock()
        self.robot.request_shutdown()
        self.robot.shutdown_callback.assert_called_once()
        self.assertTrue(self.robot.shutting_down)

    async def test_speech_busy_duplicate_completion_and_stop(self):
        speech = SpeechService(simulation=True)
        self.assertEqual(speech.submit("one", "Hello")["state"], "accepted")
        self.assertTrue(speech.submit("one", "Hello")["duplicate"])
        with self.assertRaises(ValueError):
            speech.submit("one", "different")
        with self.assertRaises(RuntimeError):
            speech.submit("two", "busy")
        await speech._task
        self.assertEqual(speech.status()["state"], "completed")
        speech.submit("two", "Hi")
        await speech.stop()
        self.assertEqual(speech.status()["state"], "stopped")

    async def test_speech_invokes_argument_arrays_and_cleans_subprocess(self):
        speech = SpeechService(simulation=False, device="test-device")
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"wav", b""))
        process.wait = AsyncMock()
        with patch("audio.shutil.which", return_value="installed"), patch("audio.asyncio.create_subprocess_exec", AsyncMock(return_value=process)) as create:
            speech.submit("test", "--help; no shell interpretation")
            await speech._task
            self.assertEqual(create.call_args_list[0].args, ("espeak-ng", "--stdout", "--stdin"))
            self.assertEqual(create.call_args_list[1].args, ("aplay", "-q", "-D", "test-device"))
            self.assertEqual(process.communicate.call_args_list[0].args, (b"--help; no shell interpretation",))
            self.assertEqual(speech.status()["state"], "completed")

    async def test_cancel_hanging_speech_kills_and_reaps_owned_child(self):
        speech = SpeechService(simulation=False)
        started = asyncio.Event()
        async def hanging_communicate(data):
            started.set()
            await asyncio.sleep(100)
        process = Mock(returncode=None)
        process.communicate = hanging_communicate
        process.wait = AsyncMock()
        with patch("audio.shutil.which", return_value="installed"), patch("audio.asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            speech.submit("hang", "Hello")
            await started.wait()
            await speech.stop()
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()
        self.assertEqual(speech.status()["state"], "stopped")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.headers = {}
        self.robot = RobotServerManager(simulation=True)
        self.client = TestClient(create_app(self.robot))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_tokenless_browser_and_second_client(self):
        with self.client.websocket_connect("/ws", headers={"Origin": "http://localhost:3000"}) as browser:
            self.assertEqual(browser.receive_json()["server_version"], "2.3")
        with self.client.websocket_connect("/ws", headers=self.headers) as owner:
            hello = owner.receive_json()
            self.assertTrue(hello["capabilities"]["watchdog"])
            self.assertTrue(hello["capabilities"]["simulation"])
            self.robot.drive(1, 1, 0.2)
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect("/ws", headers=self.headers):
                    pass
            self.assertEqual(self.robot.motors.left, 1)
        self.assertFalse(self.robot.connected)
        self.assertEqual(self.robot.motors.left, 0)

    def test_tokenless_speech_still_requires_control_and_strict_text(self):
        body = {"request_id": "speech-one", "text": "Hello"}
        self.assertEqual(self.client.post("/speech", json=body).status_code, 409)
        self.assertEqual(self.client.post("/speech", json={**body, "text": 123}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post("/speech", json={**body, "text": "x" * 501}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post("/speech", json=body, headers=self.headers).status_code, 409)
        with self.client.websocket_connect("/ws", headers=self.headers) as socket:
            socket.receive_json()
            self.assertEqual(self.client.post("/speech", json=body, headers=self.headers).status_code, 202)
            self.assertTrue(self.client.get("/speech", headers=self.headers).json()["simulation"])
            self.assertEqual(self.client.delete("/speech", headers=self.headers).status_code, 200)

    def test_health_marks_simulation_and_hardware_modules_not_imported(self):
        self.assertTrue(self.client.get("/").json()["simulation"])
        self.assertNotIn("hardware.servos", sys.modules)

    def test_silent_open_socket_expires_control_lease(self):
        with self.client.websocket_connect("/ws", headers=self.headers) as socket:
            socket.receive_json()
            socket.send_json({"type": "servo", "pan": 10})
            with self.assertRaises(WebSocketDisconnect) as closed:
                for _ in range(15):
                    socket.receive_json()
            self.assertEqual(closed.exception.code, 1008)
        safety = self.client.get("/").json()["safety"]
        self.assertEqual(safety["last_trip_reason"], "control_timeout")
        self.assertEqual(safety["trip_count"], 1)
        self.assertTrue(safety["connection_expired"])
        self.assertFalse(safety["control_lease_valid"])
        self.assertEqual((self.robot.servos.pan.angle, self.robot.servos.tilt.angle), (90, 90))
        self.assertFalse(self.robot.relay.state())


if __name__ == "__main__":
    unittest.main()
