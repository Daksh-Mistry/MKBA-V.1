"""Discrete sensor reader for 4 Flame and 4 IR sensors on Raspberry Pi 5."""
# Useful read() --> { "flame_array": [0, 0, 0, 0], "ir_array": [0, 0, 0, 0] }

from __future__ import annotations

from dataclasses import dataclass, field

try:
    import RPi.GPIO as GPIO
    GPIO.setwarnings(False)  # Suppress "channel already in use" warnings on restart
except ImportError:
    GPIO = None  # type: ignore


@dataclass
class SensorPins:
    flame_array: list[int] = field(default_factory=lambda: [5, 6, 12, 16])
    ir_array: list[int] = field(default_factory=lambda: [10, 9, 11, 8])


class Sensors:
    def __init__(self, pins: SensorPins, enabled: bool = True):
        self.pins = pins
        self._setup_ok = False
        self.enabled = enabled

        if not enabled:
            print("  Sensors disabled via config flag.")
            return

        if GPIO is None:
            print("  Sensors unavailable: RPi.GPIO is not installed.")
            self.enabled = False
            return

        # GPIO available — attempt hardware setup
        self.enabled = True
        try:
            GPIO.setmode(GPIO.BCM)
            all_pins = pins.flame_array + pins.ir_array
            for pin in all_pins:
                # PUD_UP: sensor pulls line LOW when triggered (active-low, most digital sensors)
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._setup_ok = True
            print(f"  Sensors ready: Flame pins {pins.flame_array} | IR pins {pins.ir_array}")
        except Exception as e:
            self.enabled = False
            print(f"  Sensors unavailable: GPIO setup failed: {e}")

    def read(self) -> dict:
        """Read sensor pins; -1 means disabled or a setup/read failure."""
        if not self.enabled or not self._setup_ok or GPIO is None:
            return {
                "flame_array": [-1] * len(self.pins.flame_array),
                "ir_array": [-1] * len(self.pins.ir_array),
            }
        try:
            return {
                "flame_array": [int(not GPIO.input(pin)) for pin in self.pins.flame_array],
                "ir_array": [int(GPIO.input(pin)) for pin in self.pins.ir_array],
            }
        except Exception as e:
            print(f"  Sensor read error: {e}")
            return {
                "flame_array": [-1] * len(self.pins.flame_array),
                "ir_array": [-1] * len(self.pins.ir_array),
            }


if __name__ == "__main__":
    import time
    print("Testing Sensors Module (4 IR Edge + 4 Flame)...")
    sensors = Sensors(SensorPins())
    print("  Reading sensor values for 5 seconds (Press Ctrl+C to stop)...")
    try:
        for i in range(10):
            data = sensors.read()
            print(f"  [{i+1}/10] Flame: {data['flame_array']} | IR: {data['ir_array']}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    print("Sensors test complete!")

