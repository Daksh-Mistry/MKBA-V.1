import unittest

from Backend.auto_policy import AutoPolicy
from Backend.config import Settings


class AutoPolicyTests(unittest.TestCase):
    def result(self, box=None):
        return {'detections': [{'class': 'fire', 'score': 0.9, 'bbox': box or [0.4, 0.4, 0.6, 0.6]}]}

    def test_smoke_alone_never_sprays(self):
        policy = AutoPolicy(Settings())
        for i in range(10):
            action = policy.step({'detections': [{'class': 'smoke', 'score': 0.99, 'bbox': [0.4, 0.4, 0.6, 0.6]}]},
                                 float(i), {'pan': 90, 'tilt': 90})
            self.assertNotEqual(action.get('kind') if action else None, 'pump')

    def test_aiming_uses_small_relative_steps(self):
        policy = AutoPolicy(Settings())
        action = None
        for i in range(3):
            action = policy.step(self.result([0.7, 0.7, 0.9, 0.9]), float(i), {'pan': 90, 'tilt': 90})
        self.assertEqual(action, {'kind': 'servo', 'pan': -3, 'tilt': 3})

    def test_three_burst_limit_and_cooldown(self):
        policy = AutoPolicy(Settings())
        actions = []
        for i in range(150):
            action = policy.step(self.result(), i * 0.2, {'pan': 90, 'tilt': 90})
            if action:
                actions.append((i * 0.2, action))
                if action['kind'] == 'complete':
                    break
        bursts = [when for when, action in actions if action['kind'] == 'pump']
        self.assertEqual(len(bursts), 3)
        self.assertTrue(all(b - a >= 5.8 for a, b in zip(bursts, bursts[1:])))
        self.assertEqual(actions[-1][1]['kind'], 'complete')

    def test_clear_frames_after_spray_end_cycle(self):
        policy = AutoPolicy(Settings())
        policy.bursts = 1
        for i in range(4):
            action = policy.step({'detections': []}, float(i), {'pan': 90, 'tilt': 90})
        self.assertEqual(action['kind'], 'complete')

    def test_mechanical_aim_limit_ends_cycle(self):
        policy = AutoPolicy(Settings())
        for i in range(3):
            action = policy.step(self.result([0.1, 0.4, 0.2, 0.6]), float(i), {'pan': 150, 'tilt': 90})
        self.assertEqual(action['kind'], 'complete')
        self.assertEqual(policy.phase, 'blocked')


if __name__ == '__main__':
    unittest.main()
