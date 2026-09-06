"""Centralized pin mappings and runtime constants for the Raspberry Pi 5 server."""

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
HOST = "0.0.0.0"
PORT = 8000       # Unified FastAPI port (HTTP & WebSockets)
WS_PORT = 8000    # Backwards compatibility alias
VIDEO_PORT = 8000 # Backwards compatibility alias
MDNS_NAME = "robo"

# Behavior defaults
DEFAULT_SPEED = 0.5  # 0.0 - 1.0
BOOST_FACTOR = 1.3
SLOW_FACTOR = 0.7
SENSOR_HZ = 5  # 10 Hz telemetry & sensor broadcast

# Feature flags
ENABLE_CAMERA = True
ENABLE_SENSORS = True
RELAY_ACTIVE_LOW = True  # Set to False if your relay triggers on HIGH

