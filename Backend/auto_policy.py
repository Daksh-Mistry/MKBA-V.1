"""Stationary fire observation/aiming policy. It never drives the chassis."""
from __future__ import annotations


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
            self.next_at = now + 0.4
            return {'kind': 'servo', 'pan': 3 * self.scan_sign, 'tilt': 0}
        self.clear_frames = 0
        target = max(fires, key=lambda d: d['score'])
        x1, y1, x2, y2 = target['bbox']
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
            pan = -3 if dx > 0.08 else 3 if dx < -0.08 else 0
            tilt = 3 if dy > 0.08 else -3 if dy < -0.08 else 0
            # Do not continue aiming indefinitely into a mechanical limit.
            if not 30 <= servos.get('pan', 90) + pan <= 150 or not 45 <= servos.get('tilt', 90) + tilt <= 135:
                self.phase = 'blocked'
                self.reason = 'Target is outside calibrated aiming range'
                return {'kind': 'complete'}
            return {'kind': 'servo', 'pan': pan, 'tilt': tilt}
        self.aligned += 1
        self.phase = 'align'
        if self.aligned < 3:
            return None
        if self.bursts >= 3:
            self.phase = 'complete'
            self.reason = 'Maximum three bursts reached; operator review required'
            return {'kind': 'complete'}
        self.bursts += 1
        self.phase = 'spray'
        self.confirmed = self.aligned = 0
        self.next_at = now + self.settings.auto_spray_seconds + self.settings.auto_cooldown_seconds
        return {'kind': 'pump', 'duration': self.settings.auto_spray_seconds}
