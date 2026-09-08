"""Centralized pin mappings and runtime constants for the Raspberry Pi 5 server."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=False, interpolate=False)

# GPIO pin mapping (BCM numbering for Pi 5 via rpi-lgpio / RPi.GPIO)
PINS = {
    "motor": {
        "ena": 18, # Left
        "in1": 22, # forword
        "in2": 27, # backward
        "enb": 13, # Right
        "in3": 23, # forword
        "in4": 24, # backward
    },
    "servo": {
        "pan_channel": 0,    # Horizontal
        "tilt_channel": 1,   # Vertical
        # Calibrated microsecond pulse range for MG996R high-torque servos
        "pan_min": 500,
        "pan_max": 2500,
        "tilt_min": 500,
        "tilt_max": 2500,
    },
    "sensors": {
        # 4 Flame sensors: [Front-Left, Front-Right, Rear-Left, Rear-Right]
        "flame_array": [5, 6, 12, 16],
        # 4 IR Edge/Obstacle sensors: [Front-Left, Front-Right, Rear-Left, Rear-Right]
        "ir_array": [10, 9, 11, 8],
        "relay": 17,  # Water pump relay (Powered via Motor Power Supply)
        # "led": 7,     # Status LED ( we dont have it yet)
    },
}

# Unified FastAPI Server Configuration
HOST = os.getenv("PI_HOST", "0.0.0.0")
PORT = int(os.getenv("PI_PORT", "8000"))
WS_PORT = 8000    # Backwards compatibility alias
VIDEO_PORT = 8000 # Backwards compatibility alias
MDNS_NAME = "robo"

# Behavior defaults
DEFAULT_SPEED = 0.5  # 0.0 - 1.0
BOOST_FACTOR = 1.3
SLOW_FACTOR = 0.7
SENSOR_HZ = 5

# All defaults work without a .env file; overrides are optional.
SIMULATION = os.getenv("PI_SIMULATION", "0") == "1"
CONTROL_TIMEOUT = 1.0
DRIVE_TIMEOUT = 0.4
PUMP_MAX_ON = 1.0
SPEECH_DEVICE = os.getenv("PI_SPEECH_DEVICE", "default")

# Feature flags
ENABLE_SENSORS = True
RELAY_ACTIVE_LOW = True  # Set to False if your relay triggers on HIGH


def enabled_setting(name, default="1"):
    value = os.getenv(name, default).strip()
    if value not in ("0", "1"):
        raise ValueError(f"{name} must be 0 or 1")
    return value == "1"


MOTORS_ENABLED = enabled_setting("PI_MOTORS_ENABLED")
SERVOS_ENABLED = enabled_setting("PI_SERVOS_ENABLED")
PUMP_ENABLED = enabled_setting("PI_PUMP_ENABLED")
CAMERA_ENABLED = enabled_setting("PI_CAMERA_ENABLED")
# Read every mapped input. A readable GPIO pin does not prove a sensor is attached.
# Old PI_FLAME_CHANNELS / PI_IR_CHANNELS environment settings are ignored.
FLAME_CHANNELS = tuple(range(len(PINS["sensors"]["flame_array"])))
IR_CHANNELS = tuple(range(len(PINS["sensors"]["ir_array"])))

