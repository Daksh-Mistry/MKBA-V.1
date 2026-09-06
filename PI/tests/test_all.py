"""
System Diagnostic & Hardware Verification Test Suite.
Run this script directly to test all hardware components independently:
  python tests/test_all.py
"""

import sys
import os
import time

# Add parent directory to path so config and hardware can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import PINS, DEFAULT_SPEED
from hardware import MotorController, MotorPins, PanTilt, ServoConfig, Sensors, SensorPins, RelayLED, Camera


def test_hardware_suite():
    print("=" * 60)
    print("🧪 ROBO 2.0 HARDWARE DIAGNOSTIC TEST SUITE")
    print("=" * 60)

    # 1. Test Relay & LED
    print("\n[1/5] 💧 Testing Relay & Status LED...")
    relay_pins = PINS["sensors"]
    relay = RelayLED(relay_pins["relay"], relay_pins["led"])
    relay.led(True)
    print("  -> LED ON")
    time.sleep(1)
    relay.pump_on()
    print("  -> Pump ON (1.5s)")
    time.sleep(1.5)
    relay.pump_off()
    print("  -> Pump OFF")
    relay.led(False)
    print("  -> LED OFF")

    # 2. Test Servos
    print("\n[2/5] 🎯 Testing Servos (PCA9685 / MG996R)...")
    servos = PanTilt(ServoConfig(**PINS["servo"]))
    print(f"  -> Initial Position - Pan: {servos.pan}µs, Tilt: {servos.tilt}µs")
    print("  -> Sweeping Pan (Left/Right)...")
    servos.set_pan_tilt(1000, 1500)
    time.sleep(0.8)
    servos.set_pan_tilt(2000, 1500)
    time.sleep(0.8)
    print("  -> Centering Servos...")
    servos.center()

    # 3. Test Sensors
    print("\n[3/5] 🔥 Testing Sensors (4 IR Edge + 4 Flame)...")
    sensor_pins = {k: v for k, v in PINS["sensors"].items() if k not in ("relay", "led")}
    sensors = Sensors(SensorPins(**sensor_pins))
    data = sensors.read()
    print(f"  -> Flame Sensors Reading: {data['flame_array']}")
    print(f"  -> IR Edge Sensors Reading: {data['ir_array']}")

    # 4. Test Camera
    print("\n[4/5] 📷 Testing Multiprocessing Camera...")
    cam = Camera(width=640, height=480, fps=30)
    cam.start()
    time.sleep(2)
    frame = cam.get_latest_frame()
    print(f"  -> Captured JPEG frame size: {len(frame)} bytes")
    cam.stop()

    # 5. Test Motors
    print("\n[5/5] ⚙️ Testing Motors (6-Wheel Tank Drive)...")
    motors = MotorController(MotorPins(**PINS["motor"]), default_speed=DEFAULT_SPEED)
    try:
        print("  -> Driving Forward (30% speed, 1s)...")
        motors.drive(0.3, 0.3)
        time.sleep(1)
        print("  -> Driving Reverse (30% speed, 1s)...")
        motors.drive(-0.3, -0.3)
        time.sleep(1)
        print("  -> Stopping Motors...")
        motors.stop()
    finally:
        motors.shutdown()

    print("\n" + "=" * 60)
    print("✅ ALL HARDWARE MODULE DIAGNOSTICS COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    test_hardware_suite()
