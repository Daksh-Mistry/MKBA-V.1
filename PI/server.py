"""Raspberry Pi hardware API, command deadlines and speech lifecycle."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr
import uvicorn

import config
from audio import SpeechService
from components import HardwareComponents, HardwareUnavailable
from api.websocket import (
    websocket_router, set_robot_reference, broadcast_telemetry_loop,
    close_connections,
)


class RobotServerManager:
    """Coordinates tested drivers without changing their hardware implementation."""

    def __init__(self, *, simulation=None, clock=time.monotonic, hardware=None):
        self.simulation = config.SIMULATION if simulation is None else simulation
        self.clock = clock
        self.mode = "manual"
        self.speed = config.DEFAULT_SPEED
        self.shutting_down = False
        self.shutdown_callback = None
        self.connected = False
        self.control_expired = True
        self.last_control = None
        self.drive_deadline = None
        self.pump_deadline = None
        self.pump_requires_off = False
        self.safety_reason = "startup"
        self.trip_count = 0
        self.last_trip_reason = None
        self.drive_expiry_count = 0
        self.pump_expiry_count = 0
        self.faults = []
        self.tasks = []
        self.speech = SpeechService(simulation=self.simulation, device=config.SPEECH_DEVICE)
        self.hardware = hardware if hardware is not None else HardwareComponents(simulation=self.simulation)
        if self.hardware.simulation != self.simulation:
            raise ValueError("Hardware simulation flag must match the server")
        self.motors = self.hardware.parts["motors"].device
        self.servos = self.hardware.parts["servos"].device
        self.relay = self.hardware.parts["pump"].device
        self.sensors = self.hardware.sensors
        print("Pi API initialized; component readiness is reported separately.")
        if self.simulation:
            print("SIMULATION: GPIO, I2C, camera and speaker hardware are not tested")

    def _hardware_failure(self, exc):
        self.faults = (self.faults + [str(exc)])[-8:]
        self.safe_mode("hardware_error")

    def _hardware_action(self, component, operation, *args):
        was_available = self.hardware.parts[component].available
        try:
            return self.hardware.call(component, operation, *args)
        except HardwareUnavailable as exc:
            if was_available:
                self._hardware_failure(exc)
            raise

    def move_servos(self, pan, tilt):
        if self.shutting_down:
            raise RuntimeError("server is shutting down")
        self.require_control_lease()
        was_available = self.hardware.parts["servos"].available
        try:
            self.hardware.move_servos(pan, tilt)
        except HardwareUnavailable as exc:
            if was_available:
                self._hardware_failure(exc)
            raise

    def telemetry(self):
        before = {name for name, part in self.hardware.parts.items() if part.available}
        angles, pump = self.hardware.servo_angles(), self.hardware.pump_state()
        sensors = self.sensors.read()
        lost = [name for name in before if not self.hardware.parts[name].available]
        if lost:
            self._hardware_failure(RuntimeError("Hardware status failed: " + ", ".join(lost)))
            angles, pump = self.hardware.servo_angles(), self.hardware.pump_state()
        return {"type": "status", "mode": self.mode, "speed": self.speed,
                "simulation": self.simulation, "servos": angles, "pump": pump,
                "sensors": sensors, "hardware": self.hardware.status(),
                "safety": self.safety_status(), "speech": self.speech.status()}

    def start(self):
        set_robot_reference(self)
        self.tasks = [asyncio.create_task(broadcast_telemetry_loop(), name="pi-telemetry"),
                      asyncio.create_task(self.watchdog_loop(), name="pi-watchdog")]

    def control_connected(self):
        self.safe_mode("connected_stopped")
        self.connected = True
        self.control_expired = False
        self.last_control = self.clock()

    def control_disconnected(self):
        self.connected = False
        self.control_expired = True
        self.last_control = None
        self.safe_mode("backend_disconnected")

    def touch_control(self):
        self.require_control_lease()
        self.last_control = self.clock()

    def require_control_lease(self):
        # Evaluate the deadline synchronously before any received action, even
        # if the watchdog task has not had its next event-loop turn yet.
        self.check_deadlines()
        if not self.connected or self.control_expired or self.last_control is None:
            raise ValueError("control lease expired; reconnect and explicitly resume through the backend")

    def drive(self, left, right, speed):
        if self.shutting_down:
            raise RuntimeError("server is shutting down")
        self.require_control_lease()
        self._hardware_action("motors", "drive", left, right, speed)
        self.speed = speed
        self.drive_deadline = self.clock() + config.DRIVE_TIMEOUT if (left or right) and speed else None
        self.safety_reason = "commanded"

    def pump(self, on):
        if self.shutting_down and on:
            raise RuntimeError("server is shutting down")
        if on:
            self.require_control_lease()
        if not on:
            self._hardware_action("pump", "pump_off")
            self.pump_deadline = None
            self.pump_requires_off = False
        elif self.pump_requires_off:
            raise ValueError("pump maximum duration reached; send pump off before another burst")
        elif self.pump_deadline is None:
            self._hardware_action("pump", "pump_on")
            self.pump_deadline = self.clock() + config.PUMP_MAX_ON
        # Repeated on commands never extend the current burst.

    def safe_mode(self, reason="system_stop"):
        if reason in ("control_timeout", "watchdog_hardware_error", "telemetry_error", "hardware_error"):
            self.trip_count += 1
            self.last_trip_reason = reason
            self.control_expired = True
            self.last_control = None
        self.safety_reason = reason
        self.drive_deadline = self.pump_deadline = None
        self.pump_requires_off = False
        self.speech.stop_now()
        output_failed = False
        for component, action in (("motors", "stop"), ("pump", "pump_off"), ("servos", "center")):
            try:
                if self.hardware.parts[component].available:
                    self.hardware.call(component, action)
            except Exception as exc:
                output_failed = True
                self.faults = (self.faults + [f"{component}.{action}: {exc}"])[-8:]
        if output_failed and not self.control_expired:
            self.trip_count += 1
            self.last_trip_reason = self.safety_reason = "hardware_error"
            self.control_expired = True
            self.last_control = None

    def check_deadlines(self):
        now = self.clock()
        if self.connected and self.last_control is not None and now - self.last_control >= config.CONTROL_TIMEOUT:
            self.last_control = None
            self.safe_mode("control_timeout")
        if self.drive_deadline is not None and now >= self.drive_deadline:
            self.drive_expiry_count += 1
            self.drive_deadline = None
            self.safety_reason = "drive_timeout"
            self._hardware_action("motors", "stop")
        if self.pump_deadline is not None and now >= self.pump_deadline:
            self.pump_expiry_count += 1
            self.pump_deadline = None
            self.pump_requires_off = True
            self.safety_reason = "pump_timeout"
            self._hardware_action("pump", "pump_off")

    async def watchdog_loop(self):
        while True:
            try:
                self.check_deadlines()
            except Exception as exc:
                self.faults = (self.faults + [f"watchdog: {exc}"])[-8:]
                self.safe_mode("watchdog_hardware_error")
            if self.connected and self.control_expired:
                await close_connections(code=1008, reason="control lease expired; reconnect required")
            await asyncio.sleep(0.025)

    def safety_status(self):
        return {"reason": self.safety_reason, "backend_connected": self.connected,
                "trip_count": self.trip_count, "last_trip_reason": self.last_trip_reason,
                "connection_expired": self.control_expired,
                "drive_expiry_count": self.drive_expiry_count, "pump_expiry_count": self.pump_expiry_count,
                "control_lease_valid": self.connected and not self.control_expired and self.last_control is not None and self.clock() - self.last_control < config.CONTROL_TIMEOUT,
                "drive_active": self.drive_deadline is not None,
                "pump_requires_off": self.pump_requires_off, "faults": list(self.faults)}

    def request_shutdown(self):
        if self.shutdown_callback is None:
            raise RuntimeError("Start with python server.py to enable script shutdown")
        self.shutting_down = True
        self.safe_mode("shutdown")
        self.shutdown_callback()

    def _close_hardware(self):
        self.hardware.close()
        self.faults = (self.faults + self.hardware.cleanup_errors)[-8:]

    async def stop(self):
        self.shutting_down = True
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        await close_connections()
        self.safe_mode("shutdown")
        await self.speech.stop()
        self._close_hardware()
        set_robot_reference(None)


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: StrictStr = Field(min_length=1, max_length=128)
    text: StrictStr = Field(min_length=1, max_length=500)


def create_app(manager=None):
    @asynccontextmanager
    async def lifespan(app):
        robot = manager if manager is not None else RobotServerManager()
        app.state.robot = robot
        robot.shutdown_callback = getattr(app.state, "shutdown_callback", None)
        robot.start()
        try:
            yield
        finally:
            await robot.stop()

    app = FastAPI(title="Robo Pi API", version="2.3", lifespan=lifespan)
    app.include_router(websocket_router)

    def require_running(request):
        if request.app.state.robot.shutting_down:
            raise HTTPException(503, "server is shutting down")

    @app.get("/")
    async def root(request: Request):
        robot = request.app.state.robot
        return {"status": "online", "system": "Robo", "version": "2.3", "mode": robot.mode, "speed": robot.speed,
                "simulation": robot.simulation, "authentication_required": False,
                "hardware": robot.hardware.status(), "safety": robot.safety_status()}

    @app.get("/status")
    async def status(request: Request):
        require_running(request)
        return request.app.state.robot.telemetry()

    @app.post("/speech", status_code=202)
    async def speak(data: SpeechRequest, request: Request):
        require_running(request)
        if not data.text.strip():
            raise HTTPException(422, "text must not be blank")
        try:
            request.app.state.robot.require_control_lease()
            return request.app.state.robot.speech.submit(data.request_id, data.text)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/speech")
    async def speech_status(request: Request):
        require_running(request)
        return request.app.state.robot.speech.status()

    @app.delete("/speech")
    async def stop_speech(request: Request):
        require_running(request)
        return await request.app.state.robot.speech.stop()

    return app


app = create_app()

if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=config.PORT, log_level="info", ws_max_size=4096))
    app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
    server.run()
