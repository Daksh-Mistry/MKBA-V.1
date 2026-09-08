"""Partial hardware behavior using injected devices; never opens real GPIO."""
import asyncio
import json
import os
import sys
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from components import HardwareComponents, HardwareUnavailable, SensorBank, cleanup_gpio
from simulation import SimMotors, SimServos, SimRelay
from server import RobotServerManager, create_app
from api import websocket as protocol
from fastapi.testclient import TestClient


def missing():
    raise ModuleNotFoundError("hardware dependency missing")


def hardware(**overrides):
    factories = dict(motors=missing, servos=missing, pump=missing, sensor=Mock())
    factories.update(overrides)
    return HardwareComponents(simulation=False, factories=factories, flame_channels=(), ir_channels=())


class PartialRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 0.0
        self.robot = None

    def make(self, **devices):
        self.robot = RobotServerManager(simulation=False, clock=lambda: self.now, hardware=hardware(**devices))
        self.robot.control_connected()
        return self.robot

    async def asyncTearDown(self):
        protocol.set_robot_reference(None)
        if self.robot:
            await self.robot.stop()

    async def test_bare_pi_has_real_unknowns_and_no_cleanup_errors(self):
        robot = self.make()
        result = robot.telemetry()
        self.assertFalse(result["simulation"])
        self.assertEqual(result["servos"], {"pan": None, "tilt": None})
        self.assertIsNone(result["pump"])
        self.assertEqual(result["sensors"], {"flame_array": [-1]*4, "ir_array": [-1]*4})
        self.assertEqual(result["hardware"]["servos"]["state"], "unavailable")
        robot.safe_mode()
        await robot.stop()
        self.assertFalse(robot.faults)

    async def test_missing_servo_does_not_prevent_motor_commands(self):
        robot = self.make(motors=SimMotors)
        robot.drive(1, -1, 0.2)
        with self.assertRaises(HardwareUnavailable):
            robot.move_servos(5, None)
        self.assertEqual((robot.motors.left, robot.motors.right), (1, -1))
        self.assertFalse(robot.control_expired)
        robot.safe_mode()
        self.assertEqual(robot.motors.left, 0)
        self.assertFalse(robot.faults)

    async def test_only_servo_available_moves_and_centers(self):
        robot = self.make(servos=SimServos)
        robot.move_servos(5, -10)
        self.assertEqual(robot.telemetry()["servos"], {"pan": 95, "tilt": 80})
        robot.safe_mode()
        self.assertEqual(robot.telemetry()["servos"], {"pan": 90, "tilt": 90})
        self.assertIsNone(robot.telemetry()["pump"])

    async def test_only_pump_available_still_has_independent_deadline(self):
        robot = self.make(pump=SimRelay)
        robot.pump(True)
        self.now = 0.8
        robot.touch_control()
        self.now = 1.01
        robot.check_deadlines()
        self.assertFalse(robot.telemetry()["pump"])
        self.assertTrue(robot.pump_requires_off)
        self.assertFalse(robot.faults)

    async def test_missing_actuators_reject_commands_with_correlated_errors(self):
        robot = self.make()
        protocol.set_robot_reference(robot)
        for kind, fields, component in (("drive", {"left": 1}, "motors"),
                                         ("servo", {"pan": 5}, "servos"),
                                         ("pump", {"on": True}, "pump")):
            ws = SimpleNamespace(send_text=AsyncMock())
            await protocol.dispatch_ws_message(ws, json.dumps(dict(type=kind, request_id=kind, **fields)))
            error = json.loads(ws.send_text.call_args.args[0])
            self.assertEqual(error["code"], "hardware_unavailable")
            self.assertEqual(error["component"], component)
            self.assertEqual(error["request_id"], kind)
        self.assertFalse(robot.control_expired)

    async def test_runtime_motor_failure_stops_other_outputs_and_expires_control(self):
        robot = self.make(motors=SimMotors, pump=SimRelay, servos=SimServos)
        robot.pump(True)
        robot.move_servos(10, 10)
        robot.motors.drive = Mock(side_effect=OSError("GPIO disconnected"))
        with self.assertRaises(HardwareUnavailable):
            robot.drive(1, 1, 0.2)
        self.assertTrue(robot.control_expired)
        self.assertEqual(robot.last_trip_reason, "hardware_error")
        self.assertEqual(robot.hardware.parts["motors"].state, "unavailable")
        self.assertFalse(robot.relay.state())
        self.assertEqual(robot.servos.pan.angle, 90)

    async def test_servo_swallowed_write_failure_is_reported(self):
        robot = self.make(servos=SimServos)
        robot.servos.set_pan_tilt = Mock()  # Old driver may log instead of raising.
        with self.assertRaises(HardwareUnavailable):
            robot.move_servos(5, 0)
        self.assertIsNone(robot.telemetry()["servos"]["pan"])
        self.assertTrue(robot.control_expired)

    async def test_servo_read_failure_does_not_break_telemetry(self):
        robot = self.make(servos=SimServos, pump=SimRelay)
        robot.pump(True)
        robot.servos.pan = None
        result = robot.telemetry()
        self.assertIsNone(result["servos"]["pan"])
        self.assertFalse(result["pump"])
        self.assertEqual(result["hardware"]["servos"]["state"], "unavailable")
        count = robot.trip_count
        robot.telemetry()
        self.assertEqual(robot.trip_count, count)

    async def test_bare_pi_watchdog_and_shutdown_work(self):
        robot = self.make()
        self.now = 1.01
        robot.check_deadlines()
        self.assertTrue(robot.control_expired)
        self.assertEqual(robot.last_trip_reason, "control_timeout")
        robot.shutdown_callback = Mock()
        robot.request_shutdown()
        robot.shutdown_callback.assert_called_once()
        self.assertFalse(robot.faults)


class SensorTests(unittest.TestCase):
    def test_empty_gpio_cleanup_warning_is_quiet_but_other_warnings_remain(self):
        def cleanup(pins):
            self.assertEqual(pins, [18, 22])
            warnings.warn("No channels have been set up yet - nothing to clean up!", RuntimeWarning)
            warnings.warn("Unexpected cleanup condition", RuntimeWarning)
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            cleanup_gpio(SimpleNamespace(cleanup=cleanup), [18, 22])
        self.assertEqual([str(item.message) for item in recorded], ["Unexpected cleanup condition"])

    def test_gpio_cleanup_exceptions_remain_visible(self):
        with self.assertRaisesRegex(OSError, "cleanup failed"):
            cleanup_gpio(SimpleNamespace(cleanup=Mock(side_effect=OSError("cleanup failed"))))

    def test_unconfigured_channels_never_import_or_read_a_driver(self):
        factory = Mock()
        bank = SensorBank(factory, (), ())
        self.assertEqual(bank.read()["ir_array"], [-1]*4)
        factory.assert_not_called()
        self.assertEqual(bank.status()["state"], "disabled")

    def test_partial_arrays_preserve_physical_channel_positions(self):
        factory = Mock(side_effect=lambda group, index: SimpleNamespace(read=lambda: {group: [index % 2]}))
        bank = SensorBank(factory, (0, 3), (1,))
        self.assertEqual(bank.read(), {"flame_array": [0, -1, -1, 1], "ir_array": [-1, 1, -1, -1]})
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(bank.status()["readable_channels"], 3)

    def test_one_sensor_initialization_failure_does_not_hide_another(self):
        def factory(group, index):
            if index == 0:
                raise OSError("bad input")
            return SimpleNamespace(read=lambda: {group: [1]})
        bank = SensorBank(factory, (), (0, 2))
        self.assertEqual(bank.read()["ir_array"], [-1, -1, 1, -1])
        self.assertEqual(bank.status()["state"], "partial")
        self.assertEqual(bank.status()["channels"]["ir_array"][0]["state"], "unavailable")

    def test_one_sensor_read_failure_keeps_other_readings_and_no_fake_clear(self):
        failed = Mock(return_value={"ir_array": [-1]})
        bank = SensorBank(lambda group, i: SimpleNamespace(read=failed if i == 0 else lambda: {group: [0]}), (), (0, 1))
        self.assertEqual(bank.read()["ir_array"], [-1, 0, -1, -1])
        self.assertEqual(bank.read()["ir_array"], [-1, 0, -1, -1])
        self.assertEqual(failed.call_count, 2)
        self.assertEqual(bank.status()["readable_channels"], 1)
        channel = bank.status()["channels"]["ir_array"][0]
        self.assertEqual((channel["samples"], channel["changes"], channel["read_errors"]), (0, 0, 2))

    def test_defaults_read_all_eight_channels_without_configuration(self):
        factory = Mock(side_effect=lambda group, index: SimpleNamespace(read=lambda: {group: [1]}))
        with patch.dict(os.environ, {"PI_IR_CHANNELS": "", "PI_FLAME_CHANNELS": ""}):
            parts = HardwareComponents(factories={"sensor": factory},
                                       enabled=dict(motors=False, servos=False, pump=False))
        self.assertEqual(factory.call_count, 8)
        self.assertEqual(parts.sensors.read(), {"flame_array": [1]*4, "ir_array": [1]*4})

    def test_signal_changes_are_observed_without_claiming_sensor_presence(self):
        readings = Mock(side_effect=[{"ir_array": [1]}, {"ir_array": [1]},
                                    {"ir_array": [0]}, {"ir_array": [1]}])
        bank = SensorBank(lambda *_: SimpleNamespace(read=readings), (), (0,))
        self.assertEqual(bank.status()["channels"]["ir_array"][0]["evidence"], "no_valid_reading")
        bank.read()
        bank.read()
        channel = bank.status()["channels"]["ir_array"][0]
        self.assertEqual((channel["samples"], channel["changes"], channel["evidence"]), (2, 0, "steady_signal"))
        bank.read()
        bank.read()
        channel = bank.status()["channels"]["ir_array"][0]
        self.assertEqual((channel["gpio"], channel["value"], channel["changes"]), (10, 1, 2))
        self.assertEqual(channel["evidence"], "signal_changed")
        self.assertEqual(bank.status()["presence"], "GPIO_only_not_sensor_detection")

    def test_read_fault_recovers_without_restart_or_fabricated_signal_change(self):
        readings = Mock(side_effect=[{"ir_array": [1]}, OSError("temporary read fault"), {"ir_array": [1]}])
        bank = SensorBank(lambda *_: SimpleNamespace(read=readings), (), (0,))
        self.assertEqual(bank.read()["ir_array"][0], 1)
        self.assertEqual(bank.read()["ir_array"][0], -1)
        self.assertEqual(bank.status()["state"], "unavailable")
        self.assertEqual(bank.read()["ir_array"][0], 1)
        channel = bank.status()["channels"]["ir_array"][0]
        self.assertEqual((channel["samples"], channel["changes"], channel["read_errors"]), (2, 0, 1))
        self.assertEqual(channel["state"], "available")
        self.assertIsNone(channel["reason"])

    def test_diagnostic_reports_pin_levels_and_unknowns(self):
        from test_websocket import sensor_rows
        bank = SensorBank(lambda *_: SimpleNamespace(read=lambda: {"flame_array": [0]}), (0,), ())
        bank.read()
        rows = sensor_rows({"hardware": {"sensors": bank.status()}})
        self.assertIn("GPIO  5: raw=1 value= 0", rows[0])
        self.assertIn("steady_signal", rows[0])
        self.assertIn("raw=? value=-1", rows[-1])

    def test_disabled_component_is_not_initialized(self):
        factory = Mock(side_effect=AssertionError("should not initialize"))
        parts = HardwareComponents(factories={"sensor": factory}, enabled=dict(motors=False, servos=False, pump=False),
                                   flame_channels=(), ir_channels=())
        factory.assert_not_called()
        self.assertEqual(parts.status()["motors"]["state"], "disabled")


class PartialApiTests(unittest.TestCase):
    def test_normal_bare_pi_http_and_websocket_keep_serving(self):
        robot = RobotServerManager(simulation=False, hardware=hardware())
        headers = {}
        with TestClient(create_app(robot)) as client:
            health = client.get("/").json()
            self.assertEqual(health["version"], "2.3")
            self.assertFalse(health["simulation"])
            self.assertEqual(client.get("/status").status_code, 200)
            self.assertFalse(health["authentication_required"])
            self.assertIsNone(client.get("/status", headers=headers).json()["pump"])
            with client.websocket_connect("/ws", headers=headers) as ws:
                hello = ws.receive_json()
                self.assertTrue(hello["capabilities"]["partial_hardware"])
                self.assertEqual(hello["hardware"]["servos"]["state"], "unavailable")
                ws.send_json({"type": "heartbeat", "request_id": "hb"})
                types = set()
                for _ in range(8):
                    event = ws.receive_json()
                    types.add(event["type"])
                    if event["type"] == "status":
                        self.assertIsNone(event["servos"]["pan"])
                        self.assertEqual(event["sensors"]["flame_array"], [-1]*4)
                    if {"heartbeat_ack", "status"} <= types:
                        break
                self.assertTrue({"heartbeat_ack", "status"} <= types)
        self.assertFalse(robot.faults)


if __name__ == "__main__":
    unittest.main()
