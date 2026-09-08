"""Hardware abstraction package for Robo 2.0 (Raspberry Pi 5)."""

from importlib import import_module

# Loading a motor must not import ServoKit (or require working I2C).
_MODULES = {"MotorController": "motors", "MotorPins": "motors", "PanTilt": "servos",
            "ServoConfig": "servos", "Sensors": "sensors", "SensorPins": "sensors", "RelayLED": "relay_led"}


def __getattr__(name):
    if name not in _MODULES:
        raise AttributeError(name)
    value = getattr(import_module(f".{_MODULES[name]}", __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "MotorController",
    "MotorPins",
    "PanTilt",
    "ServoConfig",
    "Sensors",
    "SensorPins",
    "RelayLED",
]
