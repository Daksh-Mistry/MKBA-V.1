"""L298N motor driver control."""

from __future__ import annotations

import time
from dataclasses import dataclass

try:
    import RPi.GPIO as GPIO
except ImportError:  # Running off-Pi for dev
    GPIO = None  # type: ignore


@dataclass
class MotorPins:
    ena: int
    in1: int
    in2: int
    enb: int
    in3: int
    in4: int



# troubleshoot_L298N:
# 1. No movement? Check ENA/ENB jumpers are present (if not using PWM pins).
# 2. Humm but no turn? Check battery voltage (need > 7V for 12V motors).
# 3. One side only? Swap IN1/IN2 with IN3/IN4 to rule out motor failure.
class MotorController:
    def __init__(self, pins: MotorPins, default_speed: float = 0.5):
        self.pins = pins
        self.default_speed = default_speed
        self._pwm_left = None
        self._pwm_right = None
        if GPIO:
            GPIO.setmode(GPIO.BCM)
            for pin in (pins.ena, pins.in1, pins.in2, pins.enb, pins.in3, pins.in4):
                GPIO.setup(pin, GPIO.OUT)
            self._pwm_left = GPIO.PWM(pins.ena, 1000)
            self._pwm_right = GPIO.PWM(pins.enb, 1000)
            self._pwm_left.start(0)
            self._pwm_right.start(0)

    def _set_side(self, pwm, in_a: int, in_b: int, speed: float):
        speed_pct = max(0.0, min(1.0, abs(speed))) * 100
        direction = 0 if speed == 0 else (GPIO.LOW if speed > 0 else GPIO.HIGH)
        if GPIO:
            GPIO.output(in_a, direction)
            GPIO.output(in_b, GPIO.HIGH if direction == GPIO.LOW else GPIO.LOW)
            pwm.ChangeDutyCycle(speed_pct)

    def drive(self, left: float, right: float):
        """Drive tank-style; left/right in range [-1, 1]."""
        if GPIO:
            self._set_side(self._pwm_left, self.pins.in1, self.pins.in2, left)
            self._set_side(self._pwm_right, self.pins.in3, self.pins.in4, right)

    def stop(self):
        self.drive(0.0, 0.0)

    def shutdown(self):
        try:
            self.stop()
            if GPIO:
                self._pwm_left.stop()
                self._pwm_right.stop()
                time.sleep(0.1)
        finally:
            if GPIO:
                GPIO.cleanup()

