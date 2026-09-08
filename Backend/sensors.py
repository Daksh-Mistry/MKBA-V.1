"""Digital sensor validity and immediate hazard / delayed clear handling."""
from __future__ import annotations


class SensorProcessor:
    def __init__(self, blocked_value=None):
        self.blocked_value = blocked_value
        self.raw = {'ir_array': [-1] * 4, 'flame_array': [-1] * 4}
        self.ir = [None] * 4
        self.clear_counts = [0] * 4
        self.last_at = None

    def update(self, raw, now):
        if not isinstance(raw, dict):
            raw = {}
        self.raw = {}
        for key in ('ir_array', 'flame_array'):
            value = raw.get(key)
            if not isinstance(value, list) or len(value) != 4:
                value = [-1] * 4
            self.raw[key] = [v if type(v) is int and v in (0, 1) else -1 for v in value]
        for index, value in enumerate(self.raw['ir_array']):
            if value == -1 or self.blocked_value is None:
                self.ir[index] = None
                self.clear_counts[index] = 0
            elif value == self.blocked_value:
                self.ir[index] = True
                self.clear_counts[index] = 0
            else:
                self.clear_counts[index] += 1
                if self.clear_counts[index] >= 2:
                    self.ir[index] = False
        self.last_at = now

    def snapshot(self, now, timeout=1.0):
        fresh = self.last_at is not None and now - self.last_at <= timeout
        ir = [{'position': index, 'blocked': value if fresh else None,
               'valid': fresh and value is not None} for index, value in enumerate(self.ir)]
        flame = [{'position': index, 'detected': bool(value) if fresh and value != -1 else None,
                  'valid': fresh and value != -1} for index, value in enumerate(self.raw['flame_array'])]
        return {'raw': {key: list(values) for key, values in self.raw.items()},
                'ir': ir, 'flame': flame, 'fresh': fresh,
                'age_ms': None if self.last_at is None else round((now - self.last_at) * 1000)}

    def clear(self, now, timeout=1.0):
        return self.last_at is not None and now - self.last_at <= timeout and all(v is False for v in self.ir)
