"""Pump relay and status LED control."""

from __future__ import annotations

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None  # type: ignore



from config import RELAY_ACTIVE_LOW

class RelayLED:
    def __init__(self, relay_pin: int, led_pin: int):
        self.relay_pin = relay_pin
        self.led_pin = led_pin
        
        # Determine logic levels
        self.on_level = GPIO.LOW if RELAY_ACTIVE_LOW else GPIO.HIGH
        self.off_level = GPIO.HIGH if RELAY_ACTIVE_LOW else GPIO.LOW
        
        if GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(relay_pin, GPIO.OUT, initial=self.off_level)
            GPIO.setup(led_pin, GPIO.OUT, initial=GPIO.LOW)
        self._pump = False

    def pump_on(self):
        self._pump = True
        print(f"   [Relay] Pump ON (Pin {self.relay_pin} -> {'LOW' if self.on_level == GPIO.LOW else 'HIGH'})")
        if GPIO:
            GPIO.output(self.relay_pin, self.on_level)

    def pump_off(self):
        self._pump = False
        print(f"   [Relay] Pump OFF (Pin {self.relay_pin} -> {'HIGH' if self.off_level == GPIO.HIGH else 'LOW'})")
        if GPIO:
            GPIO.output(self.relay_pin, self.off_level)

    def led(self, on: bool):
        if GPIO:
            GPIO.output(self.led_pin, GPIO.HIGH if on else GPIO.LOW)

    def state(self) -> bool:
        return self._pump

