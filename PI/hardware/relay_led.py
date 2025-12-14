"""Pump relay and status LED control."""

from __future__ import annotations

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None  # type: ignore


class RelayLED:
    def __init__(self, relay_pin: int, led_pin: int):
        self.relay_pin = relay_pin
        self.led_pin = led_pin
        if GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(relay_pin, GPIO.OUT, initial=GPIO.HIGH)  # active LOW
            GPIO.setup(led_pin, GPIO.OUT, initial=GPIO.LOW)
        self._pump = False

    def pump_on(self):
        self._pump = True
        if GPIO:
            GPIO.output(self.relay_pin, GPIO.LOW)

    def pump_off(self):
        self._pump = False
        if GPIO:
            GPIO.output(self.relay_pin, GPIO.HIGH)

    def led(self, on: bool):
        if GPIO:
            GPIO.output(self.led_pin, GPIO.HIGH if on else GPIO.LOW)

    def state(self) -> bool:
        return self._pump

