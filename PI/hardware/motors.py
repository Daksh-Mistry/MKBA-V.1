"""Motor driver control supporting 6-wheel drive chassis and Raspberry Pi 5."""
# Use only 1/-1 for left/right and [0.0-1.0] for speed in drive(left,right,speed) method

from __future__ import annotations

import time
from dataclasses import dataclass

try:
    # rpi-lgpio provides RPi.GPIO on Pi 5
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


class MotorController:
    """Controls left and right motor banks for 6-wheel tank steering."""
    def __init__(self, pins: MotorPins, default_speed: float = 0.5):
        self.pins = pins
        self.speed = default_speed
        self._pwm_left = None
        self._pwm_right = None
        if GPIO:
            try:
                GPIO.setmode(GPIO.BCM)
                for pin in (pins.ena, pins.in1, pins.in2, pins.enb, pins.in3, pins.in4):
                    GPIO.setup(pin, GPIO.OUT)
                self._pwm_left = GPIO.PWM(pins.ena, 1000)
                self._pwm_right = GPIO.PWM(pins.enb, 1000)
                self._pwm_left.start(0)
                self._pwm_right.start(0)
            except Exception as e:
                print(f"Motor GPIO Setup Warning: {e}")

    def _set_side(self, pwm, in_a: int, in_b: int, speed: float):
        if GPIO and pwm:
            speed_pct = min(1.0, abs(speed)) * 100
            if speed > 0:
                GPIO.output(in_a, GPIO.HIGH)
                GPIO.output(in_b, GPIO.LOW)
            elif speed < 0:
                GPIO.output(in_a, GPIO.LOW)
                GPIO.output(in_b, GPIO.HIGH)
            else:
                GPIO.output(in_a, GPIO.LOW)
                GPIO.output(in_b, GPIO.LOW)
            pwm.start(speed_pct)

    def drive(self, left: float, right: float, speed: float = None):
        """Drive tank-style; left/right in [-1.0 / 1.0]"""
        if speed is None:
            speed = self.speed
        if GPIO and self._pwm_left and self._pwm_right:
            self._set_side(self._pwm_left, self.pins.in1, self.pins.in2, left*speed)
            self._set_side(self._pwm_right, self.pins.in3, self.pins.in4, right*speed)

    def stop(self):
        self.drive(0.0, 0.0)

    def shutdown(self):
        try:
            self.stop()
            if GPIO and self._pwm_left and self._pwm_right:
                self._pwm_left.stop()
                self._pwm_right.stop()
                self._pwm_left = None
                self._pwm_right = None
                time.sleep(0.05)
        finally:
            if GPIO:
                try:
                    GPIO.cleanup()
                except Exception:
                    pass


if __name__ == "__main__":
    import sys 
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    import config
    print("Testing Motors Module...")
    # Default pins for testing
    test_pins = MotorPins(**config.PINS['motor'])
    motors = MotorController(test_pins, default_speed = config.DEFAULT_SPEED)
    
    try:
      
        print("Turning LEFT-RIGHT (25% speed, 1s)...")
        motors.drive(-0.5, 0.5)
        time.sleep(1)
        motors.drive(0.5, -0.5)
        time.sleep(1)

        print("Driving FORWARD-BACKWORD (25% speed, 0.5s)...")
        motors.drive(0.5, 0.5)
        time.sleep(0.5)
        motors.drive(-0.5, -0.5)
        time.sleep(0.5)

        print("Stopping...")
        motors.stop()
    finally:
        motors.shutdown()
        print("Motors test complete!")
