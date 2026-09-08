"""Pump relay and status LED control."""
# Useful things:
# pump_on() to turn the pump on
# pump_off() to turn the pump off
# state() to get the state of the pump
# led(True) to turn the led on
# led(False) to turn the led off

from __future__ import annotations

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None  # type: ignore



try:
    from config import RELAY_ACTIVE_LOW
except ImportError:
    RELAY_ACTIVE_LOW = True


class RelayLED:
    def __init__(self, relay_pin: int = 17, led_pin: int | None = None):
        self.relay_pin = relay_pin
        self.led_pin = led_pin  # Optional — None means LED not connected yet

        # Determine logic levels based on relay module type
        if GPIO:
            self.on_level = GPIO.LOW if RELAY_ACTIVE_LOW else GPIO.HIGH
            self.off_level = GPIO.HIGH if RELAY_ACTIVE_LOW else GPIO.LOW
        else:
            self.on_level = 0
            self.off_level = 1  

        self._pump = False

        if GPIO:
            try:
                GPIO.setwarnings(False)
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(relay_pin, GPIO.OUT, initial=self.off_level)
                if led_pin is not None:
                    GPIO.setup(led_pin, GPIO.OUT, initial=GPIO.LOW)
                    print(f"  Relay ready on pin {relay_pin} | LED on pin {led_pin}")
                else:
                    print(f"  Relay ready on pin {relay_pin} | LED not configured (skipped)")
            except Exception as e:
                print(f"  Relay/LED GPIO setup failed: {e}")
        else:
            print("  Relay offline: RPi.GPIO not available (simulation mode)")

    def pump_on(self):
        self._pump = True
        print(f"[Relay] Pump ON (pin {self.relay_pin})")
        if GPIO:
            GPIO.output(self.relay_pin, self.on_level)

    def pump_off(self):
        self._pump = False
        print(f"[Relay] Pump OFF (pin {self.relay_pin})")
        if GPIO:
            GPIO.output(self.relay_pin, self.off_level)

    def led(self, on: bool):
        """Toggle status LED. No-ops silently if LED pin is not configured."""
        if GPIO and self.led_pin is not None:
            try:
                GPIO.output(self.led_pin, GPIO.HIGH if on else GPIO.LOW)
            except Exception as e:
                print(f"  LED write error: {e}")

    def state(self) -> bool:
        return self._pump



if __name__ == "__main__":
    import time
    print("Testing Relay & LED Module...")
    relay = RelayLED(relay_pin=17, led_pin=7)
    
    print("LED ON...")
    relay.led(True)
    time.sleep(1)
    
    print("Turning Pump ON (2 seconds)...")
    relay.pump_on()
    time.sleep(2)
    
    print("Turning Pump OFF...")
    relay.pump_off()
    time.sleep(1)
    
    print("LED OFF...")
    relay.led(False)
    print("Relay & LED test complete!")

