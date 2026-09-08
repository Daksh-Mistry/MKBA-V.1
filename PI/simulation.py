"""Explicit hardware-free simulation. Never imported as an error fallback."""
from types import SimpleNamespace


class SimMotors:
    def __init__(self):
        self.left = self.right = self.speed = 0

    def drive(self, left, right, speed=0):
        self.left, self.right, self.speed = left, right, speed

    def stop(self):
        self.drive(0, 0, 0)

    shutdown = stop


class SimServos:
    def __init__(self):
        self.pan = SimpleNamespace(angle=90, actuation_range=180)
        self.tilt = SimpleNamespace(angle=90, actuation_range=180)

    def set_pan_tilt(self, pan, tilt):
        for axis, delta in ((self.pan, pan), (self.tilt, tilt)):
            if delta is not None:
                axis.angle = max(0, min(180, axis.angle + delta))

    def center(self):
        self.pan.angle = self.tilt.angle = 90


class SimRelay:
    def __init__(self):
        self._pump = False

    def pump_on(self):
        self._pump = True

    def pump_off(self):
        self._pump = False

    def state(self):
        return self._pump

    def led(self, on):
        pass


class SimSensors:
    def read(self):
        # Synthetic no-flame, clear active-low IR. Not real sensor evidence.
        return {"flame_array": [0, 0, 0, 0], "ir_array": [1, 1, 1, 1]}
