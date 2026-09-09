"""Digital sensor validity and immediate hazard / delayed clear handling."""
from __future__ import annotations


class SensorProcessor:
    def __init__(self, blocked_value=None, *, require_signal_evidence=False):
        self.blocked_value = blocked_value
        self.require_signal_evidence = require_signal_evidence
        self.observed = [set() for _ in range(4)]
        self.signal_observed = [False] * 4
        self.raw = {'ir_array': [-1] * 4, 'flame_array': [-1] * 4}
        self.ir = [None] * 4
        self.clear_counts = [0] * 4
        self.last_at = None

    def update(self, raw, now, hardware=None):
        if not isinstance(raw, dict):
            raw = {}
        self.raw = {}
        for key in ('ir_array', 'flame_array'):
            value = raw.get(key)
            if not isinstance(value, list) or len(value) != 4:
                value = [-1] * 4
            self.raw[key] = [v if type(v) is int and v in (0, 1) else -1 for v in value]
            if hardware is not None:
                channels = hardware.get('channels', {}).get(key, [])
                for index in range(4):
                    if hardware.get('available') is not True or (index < len(channels) and channels[index].get('available') is not True):
                        self.raw[key][index] = -1
        for index, value in enumerate(self.raw['ir_array']):
            if value != -1:
                self.observed[index].add(value)
                if len(self.observed[index]) == 2:
                    self.signal_observed[index] = True
            channels = (hardware or {}).get('channels', {}).get('ir_array', [])
            if index < len(channels):
                channel = channels[index]
                # Pi 2.3 retains observed changes for this boot. This is signal
                # evidence, never a claim that GPIO can identify attached sensors.
                changes = channel.get('changes')
                if channel.get('available') is True and type(changes) is int and changes > 0:
                    self.signal_observed[index] = True
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
        ir_res = []
        for val in self.raw.get('ir_array', [-1] * 4):
            if not fresh or val == -1:
                ir_res.append(-1)
            elif val == self.blocked_value:
                ir_res.append(1)
            else:
                ir_res.append(0)

        flame_res = []
        for val in self.raw.get('flame_array', [-1] * 4):
            if not fresh or val == -1:
                flame_res.append(-1)
            elif val == 1:
                flame_res.append(1)
            else:
                flame_res.append(0)

        return {
            'ir': ir_res,
            'flame': flame_res,
            'fresh': fresh,
            'age_ms': None if self.last_at is None else round((now - self.last_at) * 1000)
        }

    def clear(self, now, timeout=1.0):
        return (self.last_at is not None and now - self.last_at <= timeout and all(v is False for v in self.ir)
                and (not self.require_signal_evidence or all(self.signal_observed)))
