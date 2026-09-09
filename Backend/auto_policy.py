"""Stationary fire observation/aiming policy. It never drives the chassis."""
from __future__ import annotations


from .robot_profile import LOOK


class AutoPolicy:
    def __init__(self, settings):
        self.settings = settings
        self.reset()

    def reset(self):
        self.phase = 'paused'
        self.reason = None
        self.confirmed = 0
        self.aligned = 0
        self.clear_frames = 0
        self.target = None
        self.next_at = 0.0
        self.bursts = 0
        self.scan_sign = 1

    def snapshot(self):
        return {'phase': self.phase, 'reason': self.reason, 'bursts': self.bursts,
                'chassis_motion': False, 'confirmed_frames': self.confirmed}

    def step(self, result, now, servos):
        if now < self.next_at:
            return None
        fires = [d for d in result['detections'] if d['class'] == 'fire'
                 and d['score'] >= self.settings.auto_confidence]
        if not fires:
            self.target = None
            self.confirmed = self.aligned = 0
            self.clear_frames += 1
            if self.bursts and self.clear_frames >= 4:
                self.phase = 'complete'
                self.reason = 'Fire no longer detected; operator must review before resuming'
                return {'kind': 'complete'}
            self.phase = 'reassess' if self.bursts else 'search'
            if self.bursts:
                return None
            pan = servos.get('pan', 90)
            if pan >= 115:
                self.scan_sign = -1
            elif pan <= 65:
                self.scan_sign = 1
            scan_dir = 'right' if self.scan_sign > 0 else 'left'
            pan_delta = LOOK[scan_dir][0] * 3
            tilt_delta = LOOK[scan_dir][1] * 3
            self.next_at = now + 0.4
            return {'kind': 'servo', 'direction': scan_dir, 'degrees': 3, 'pan': pan_delta, 'tilt': tilt_delta}
        self.clear_frames = 0
        target = max(fires, key=lambda d: d['score'])
        x1, y1, x2, y2 = target['bbox']
        # Centroid of bounding box reduces target area to a single aiming point
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        if self.target is None or max(abs(a - b) for a, b in zip(center, self.target)) > 0.15:
            self.confirmed = self.aligned = 0
        self.target = center
        self.confirmed += 1
        if self.confirmed < 3:
            self.phase = 'confirm'
            return None
        dx, dy = center[0] - 0.5, center[1] - 0.5
        if abs(dx) > 0.08 or abs(dy) > 0.08:
            self.phase = 'align'
            self.aligned = 0
            self.next_at = now + 0.35
            # Semantic direction mapping matching manual mode (LOOK in robot_profile.py)
            h_dir = 'right' if dx > 0.08 else 'left' if dx < -0.08 else None
            v_dir = 'down' if dy > 0.08 else 'up' if dy < -0.08 else None

            pan = (LOOK[h_dir][0] * 3) if h_dir else 0
            tilt = (LOOK[v_dir][1] * 3) if v_dir else 0
            # Do not continue aiming indefinitely into a mechanical limit.
            if not 30 <= servos.get('pan', 90) + pan <= 150 or not 45 <= servos.get('tilt', 90) + tilt <= 135:
                self.phase = 'blocked'
                self.reason = 'Target is outside calibrated aiming range'
                return {'kind': 'complete'}
            return {'kind': 'servo', 'direction': h_dir or v_dir, 'degrees': 3, 'pan': pan, 'tilt': tilt}
        self.aligned += 1
        self.phase = 'align'
        if self.aligned < 3:
            return None
        # Keep bursting until fire is extinguished; 3s burst followed by 2s assess
        self.bursts += 1
        self.phase = 'spray'
        self.confirmed = self.aligned = 0
        self.next_at = now + self.settings.auto_spray_seconds + self.settings.auto_cooldown_seconds
        return {'kind': 'pump', 'duration': self.settings.auto_spray_seconds}
