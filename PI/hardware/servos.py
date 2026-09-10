"""PCA9685 servo control calibrated for MG996R high-torque servos."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from adafruit_servokit import ServoKit
except ImportError:
    ServoKit = None


@dataclass
class ServoConfig:
    pan_channel: int = 0
    tilt_channel: int = 1
    pan_min: int = 500
    pan_max: int = 2500
    tilt_min: int = 500
    tilt_max: int = 2500


class PanTilt:
    def __init__(self, cfg: ServoConfig):
        self.cfg = cfg
        self._pca = None
        if ServoKit :
            try:
                self._pca = ServoKit(channels=16)

                self.pan = self._pca.servo[self.cfg.pan_channel]
                self.pan.set_pulse_width_range(self.cfg.pan_min, self.cfg.pan_max)
                self.pan.actuation_range = 180 

                self.tilt = self._pca.servo[self.cfg.tilt_channel]
                self.tilt.set_pulse_width_range(self.cfg.tilt_min, self.cfg.tilt_max)
                self.tilt.actuation_range = 180 
                
                self.pan.angle = 90
                self.tilt.angle = 90
            except Exception as e:
                print(f"PCA9685 servo unavailable: {e}")
                self._pca = None




    def set_pan_tilt(self, pan_us: int | None, tilt_us: int | None):
        if pan_us is not None:
            try :
                self.pan.angle = max(0 ,min(self.pan.angle + pan_us, self.pan.actuation_range))
            except :
                print("Hardware error for pan :- ", pan_us)
        if tilt_us is not None:
            try :
                self.tilt.angle = max(0 ,min(self.tilt.angle + tilt_us, self.tilt.actuation_range))
            except :
                print("Hardware error for tilt :-", tilt_us)

    def center(self):
        self.pan.angle = self.pan.actuation_range // 2
        self.tilt.angle = self.tilt.actuation_range // 2



if __name__ == "__main__":
    import time
    import sys 
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    import config
    print("Testing Servos Module (MG996R / PCA9685)...")
    servos = PanTilt(ServoConfig(**config.PINS['servo']))
    print(f"Current Pan: {servos.pan.angle} degree | Current Tilt: {servos.tilt.angle} degree")
    
    print("Sweeping Pan Left / Right...")
    servos.set_pan_tilt(90, None)
    time.sleep(1)
    servos.set_pan_tilt(-180, None)
    time.sleep(1)
    servos.set_pan_tilt(90, None)
    time.sleep(1)
    
    print("Sweeping Tilt Up / Down...")
    servos.set_pan_tilt(None, 90)
    time.sleep(1)
    servos.set_pan_tilt(None, -180)
    time.sleep(1)
    servos.set_pan_tilt(None, 90)
    time.sleep(1)

    print("Servos test complete!")

