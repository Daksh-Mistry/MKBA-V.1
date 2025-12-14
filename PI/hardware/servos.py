"""PCA9685 servo control for pan/tilt."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from adafruit_pca9685 import PCA9685
    import busio
    import board
except ImportError:
    PCA9685 = None  # type: ignore
    busio = None  # type: ignore
    board = None  # type: ignore


@dataclass
class ServoConfig:
    pan_channel: int
    tilt_channel: int
    pan_min: int
    pan_max: int
    tilt_min: int
    tilt_max: int
    step_us: int = 30


class PanTilt:
    def __init__(self, cfg: ServoConfig):
        self.cfg = cfg
        self.pan = (cfg.pan_min + cfg.pan_max) // 2
        self.tilt = (cfg.tilt_min + cfg.tilt_max) // 2
        self._pca = None
        if PCA9685:
            i2c = busio.I2C(board.SCL, board.SDA)
            self._pca = PCA9685(i2c)
            self._pca.frequency = 50
            self._write(self.cfg.pan_channel, self.pan)
            self._write(self.cfg.tilt_channel, self.tilt)

    def _clamp(self, val: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, val))

    def _write(self, channel: int, pulse_us: int):
        if not self._pca:
            return
        duty_cycle = int(pulse_us / 1000000 * 50 * 0xFFFF)
        self._pca.channels[channel].duty_cycle = duty_cycle

    def set_pan_tilt(self, pan_us: int, tilt_us: int):
        self.pan = self._clamp(pan_us, self.cfg.pan_min, self.cfg.pan_max)
        self.tilt = self._clamp(tilt_us, self.cfg.tilt_min, self.cfg.tilt_max)
        self._write(self.cfg.pan_channel, self.pan)
        self._write(self.cfg.tilt_channel, self.tilt)

    def nudge(self, pan_delta_us: int, tilt_delta_us: int):
        self.set_pan_tilt(self.pan + pan_delta_us, self.tilt + tilt_delta_us)

    def center(self):
        self.set_pan_tilt(
            (self.cfg.pan_min + self.cfg.pan_max) // 2,
            (self.cfg.tilt_min + self.cfg.tilt_max) // 2,
        )

