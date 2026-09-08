"""Hardware-free protocol tests: python -m unittest tests.test_protocol"""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import websocket as protocol


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.robot = SimpleNamespace(
            drive=Mock(), servos=Mock(), relay=Mock(), safe_mode=Mock(),
            request_shutdown=Mock(), shutting_down=False, mode="manual",
        )
        protocol.set_robot_reference(self.robot)
        self.ws = SimpleNamespace(send_text=AsyncMock())

    def tearDown(self):
        protocol.set_robot_reference(None)

    async def send(self, data):
        await protocol.dispatch_ws_message(self.ws, json.dumps(data))

    async def test_relative_degrees(self):
        await self.send({"type": "servo", "pan": 5, "tilt": -10})
        self.robot.servos.set_pan_tilt.assert_called_once_with(5, -10)
        self.robot.servos.nudge.assert_not_called()

    async def test_invalid_axis_does_not_partially_move(self):
        await self.send({"type": "servo", "pan": 5, "tilt": 1850})
        self.robot.servos.set_pan_tilt.assert_not_called()
        self.ws.send_text.assert_awaited_once()

    async def test_drive_includes_speed(self):
        await self.send({"type": "drive", "left": 1, "right": -1, "speed": 0.7})
        self.robot.drive.assert_called_once_with(1, -1, 0.7)

    async def test_drive_normalizes_both_directions(self):
        for left, right, expected in (
            (0.2, -0.8, (1, -1)),
            (-20, 30, (-1, 1)),
            (0, 0, (0, 0)),
            (0, -0.001, (0, -1)),
            (1000, 0, (1, 0)),
        ):
            with self.subTest(left=left, right=right):
                await self.send({"type": "drive", "left": left, "right": right, "speed": 0.3})
                self.robot.drive.assert_called_with(*expected, 0.3)
        self.ws.send_text.assert_not_awaited()

    async def test_invalid_direction_does_not_drive(self):
        for axis in ("left", "right"):
            for value in (True, "1", None, float("nan"), float("inf")):
                await self.send({"type": "drive", axis: value})
        self.robot.drive.assert_not_called()
        self.assertEqual(self.ws.send_text.await_count, 10)

    async def test_omitted_sides_stop(self):
        await self.send({"type": "drive", "speed": 0.5})
        self.robot.drive.assert_called_once_with(0, 0, 0.5)

    async def test_mode_assigns_attribute_without_calling_method(self):
        await self.send({"type": "mode", "value": "auto"})
        self.assertEqual(self.robot.mode, "auto")
        self.ws.send_text.assert_not_awaited()

    async def test_invalid_speed_does_not_drive(self):
        for speed in (-1, 2, float("nan"), True, "0.5"):
            await self.send({"type": "drive", "left": 1, "speed": speed})
        self.robot.drive.assert_not_called()

    async def test_stop_and_script_shutdown(self):
        await self.send({"type": "system", "command": "stop"})
        self.robot.safe_mode.assert_called_once()
        await self.send({"type": "system", "command": "shutdown"})
        self.robot.request_shutdown.assert_called_once()

    async def test_removed_commands_rejected(self):
        for kind in ("servo_delta", "speed_scalar", "emergency_stop"):
            await self.send({"type": kind})
        await self.send({"type": "system", "command": "reboot"})
        self.assertEqual(self.ws.send_text.await_count, 4)
        self.robot.safe_mode.assert_not_called()
        self.robot.request_shutdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
