"""Discrete sensor reads for flame array, flame singles, and IR edge sensors."""

from __future__ import annotations

from dataclasses import dataclass

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None  # type: ignore


@dataclass
class SensorPins:
    flame_array: list[int]
    flame_single: list[int]
    ir_array: list[int]


class Sensors:
    def __init__(self, pins: SensorPins, enabled: bool = True):
        self.pins = pins
        self.enabled = enabled and GPIO is not None
        if self.enabled:
            GPIO.setmode(GPIO.BCM)
            for pin in pins.flame_array + pins.flame_single + pins.ir_array:
                GPIO.setup(pin, GPIO.IN)

    def read(self) -> dict:
        if not self.enabled:
            return {
                "flame_array": [0] * len(self.pins.flame_array),
                "flame_single": [0] * len(self.pins.flame_single),
                "ir_array": [0] * len(self.pins.ir_array),
            }
        return {
            "flame_array": [int(GPIO.input(pin)) for pin in self.pins.flame_array],
            "flame_single": [int(GPIO.input(pin)) for pin in self.pins.flame_single],
            "ir_array": [int(GPIO.input(pin)) for pin in self.pins.ir_array],
        }

