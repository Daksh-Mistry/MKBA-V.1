"""Console filtering must never filter actual control messages."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import websocket as protocol


class CommandLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.robot = SimpleNamespace(
            shutting_down=False, control_expired=False, require_control_lease=Mock(),
            touch_control=Mock(), drive=Mock(), safe_mode=Mock(),
        )
        self.ws = SimpleNamespace(send_text=AsyncMock())
        protocol.set_robot_reference(self.robot)

    def tearDown(self):
        protocol.set_robot_reference(None)

    async def send(self, data):
        await protocol.dispatch_ws_message(self.ws, json.dumps(data))

    async def test_repeated_drive_keeps_refreshing_hardware_without_console_spam(self):
        command = {"type": "drive", "left": 1, "right": 1, "speed": 0.2}
        with patch.object(protocol, "monotonic", return_value=0) as clock, self.assertLogs("pi", level="INFO") as logs:
            for index in range(10):
                await self.send({**command, "request_id": str(index)})
            self.assertEqual(len(logs.output), 1)
            await self.send({**command, "right": -1})
            self.assertEqual(len(logs.output), 2)
            clock.return_value = 1.1
            await self.send({**command, "right": -1})
            self.assertEqual(len(logs.output), 3)
        self.assertEqual(self.robot.drive.call_count, 12)
        self.assertEqual(self.robot.touch_control.call_count, 12)
        self.ws.send_text.assert_not_awaited()

    async def test_heartbeat_is_quiet_but_still_acknowledged(self):
        with self.assertNoLogs("pi", level="INFO"):
            await self.send({"type": "heartbeat", "request_id": "heartbeat-test"})
        self.robot.touch_control.assert_called_once()
        self.assertEqual(json.loads(self.ws.send_text.call_args.args[0]),
                         {"type": "heartbeat_ack", "request_id": "heartbeat-test"})

    async def test_stop_and_restarted_drive_are_both_visible(self):
        command = {"type": "drive", "left": 1, "speed": 0.2}
        with patch.object(protocol, "monotonic", return_value=0), self.assertLogs("pi", level="INFO") as logs:
            await self.send(command)
            await self.send({"type": "system", "command": "stop"})
            await self.send(command)
        self.assertEqual(len(logs.output), 3)
        self.robot.safe_mode.assert_called_once()


if __name__ == "__main__":
    unittest.main()
