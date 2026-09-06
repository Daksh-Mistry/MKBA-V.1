"""
Robo 2.0 - Raspberry Pi 5 FastAPI Server Entry Point.
Modular architecture: Hardware abstractions in hardware/, Routers in api/.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import config
from hardware import MotorController, MotorPins, PanTilt, ServoConfig, Sensors, SensorPins, RelayLED
from api.websocket import websocket_router, set_robot_reference, broadcast_telemetry_loop


class RobotServerManager:
    """Central manager coordinating hardware components and runtime state."""
    def __init__(self):
        print("Initializing Robo 2.0 Server...")
        pins = config.PINS

        # Initialize hardware drivers
        print("MotorController Setup...")
        self.motors = MotorController(MotorPins(**pins["motor"]), default_speed=config.DEFAULT_SPEED)

        print("   🎯 Servos (PCA9685 / MG996R)...")
        self.servos = PanTilt(ServoConfig(**pins["servo"]))

        print("  Sensors (4 IR + 4 Flame)...")
        # Only pass recognised SensorPins fields — avoids KeyError if relay/led keys are present or absent
        sensor_pins = SensorPins(
            flame_array=pins["sensors"]["flame_array"],
            ir_array=pins["sensors"]["ir_array"],
        )
        self.sensors = Sensors(sensor_pins, enabled=config.ENABLE_SENSORS)

        print("  Relay & LED...")
        relay_pin = pins["sensors"]["relay"]
        led_pin = pins["sensors"].get("led")  # Optional — may not be wired yet
        self.relay = RelayLED(relay_pin, led_pin)

        self.mode = "manual"
        self.speed_scalar = 1.0
        self._telemetry_task = None

    def start(self):
        # Inject references into API routers
        set_robot_reference(self)
        # Start background 10Hz sensor telemetry loop
        self._telemetry_task = asyncio.create_task(broadcast_telemetry_loop())
        print("Hardware & Services Fully Initialized!\n")

    def stop(self):
        print("\n🔻 Shutting down server and hardware...")
        if self._telemetry_task:
            self._telemetry_task.cancel()
        self.safe_mode()
        self.motors.shutdown()

    def drive(self, left: float, right: float):
        scale = self.speed_scalar
        self.motors.drive(left * scale, right * scale)

    def safe_mode(self):
        print("🛡️ Safe Mode: Motors Stopped, Pump OFF, Servos Centered")
        self.motors.stop()
        self.relay.pump_off()
        self.servos.center()


# Global Robot Server Instance
robot = RobotServerManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and graceful shutdown lifecycle manager."""
    robot.start()
    yield
    robot.stop()


# FastAPI App
app = FastAPI(
    title="Robo 2.0 Pi 5 Server API",
    description="Modular FastAPI server for 6-wheel robot control and sensor telemetry. Camera WebRTC stream is managed by MediaMTX background service on port 8889.",
    version="2.0",
    lifespan=lifespan
)

# Enable CORS for external client applications (Laptop/Browser/Web UI)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers

# ----------------------------- LOOK INSIDE WEBSOCKET FILE -------------------------------------------
app.include_router(websocket_router)


@app.get("/")
async def root():
    """Health check and system status endpoint."""
    return {
        "status": "online",
        "system": "Robo 2.0",
        "hardware": "Raspberry Pi 5",
        "mode": robot.mode,
        "speed_scalar": robot.speed_scalar,
    }


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")