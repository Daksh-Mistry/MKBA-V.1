"""Centralized pin mappings and runtime constants for the Pi side."""

# GPIO pin mapping (BCM numbering)
PINS = {
    "motor": {
        "ena": 18,
        "in1": 22,
        "in2": 27,
        "enb": 13,
        "in3": 23,
        "in4": 24,
    },
    "servo": {
        "pan_channel": 0,
        "tilt_channel": 1,
        "pan_min": 580,
        "pan_max": 3000,
        "tilt_min": 1200,
        "tilt_max": 2500,
        "step_us": 50,  # Increased for faster movement
    },
    "sensors": {
        "flame_array": [5, 6, 12, 16, 20],
        "flame_single": [19, 26, 21],
        "ir_array": [10, 9, 11, 8],
        "relay": 17,
        "led": 7,
    },
}

# Networking
HOST = "0.0.0.0"
WS_PORT = 8765
VIDEO_PORT = 8080
MDNS_NAME = "robo"

# Behavior defaults
DEFAULT_SPEED = 0.5  # 0.0 - 1.0
BOOST_FACTOR = 1.3
SLOW_FACTOR = 0.7
SENSOR_HZ = 10  # 10 Hz sensor broadcast

# Feature flags
ENABLE_CAMERA = True
ENABLE_SENSORS = True
RELAY_ACTIVE_LOW = True  # Set to False if your relay triggers on HIGH

