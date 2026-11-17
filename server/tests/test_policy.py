import math
import random
import unittest

from server.policy import base_schedule, decide_next, jittered_next, online_status


class FixedRandom:
    def __init__(self, value):
        self.value = value
        self.bounds = None

    def uniform(self, low, high):
        self.bounds = (low, high)
        return self.value


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "default_interval_s": 300,
            "vbat_low_mv": 3450,
            "vbat_critical_mv": 3300,
            "test_mode": False,
        }

    def node(self, **values):
        result = {
            "state": "ATTACHED", "interval_s": 300, "session_req_s": 0,
            "watch_until": None, "last_vbat_mv": 3900,
        }
        result.update(values)
        return result

    def test_state_defaults(self):
        self.assertEqual(base_schedule({"state": "DISCOVERED"}, self.config)[0], 900)
        self.assertEqual(base_schedule({"state": "DETACHED"}, self.config)[0], 3600)

    def test_attached_priority_order(self):
        node = self.node(session_req_s=40, watch_until=2000, last_vbat_mv=3200)
        self.assertEqual(base_schedule(node, self.config, now=1000), (300, 40, "session"))
        node["session_req_s"] = 0
        self.assertEqual(base_schedule(node, self.config, now=1000), (60, 0, "watch"))
        node["watch_until"] = None
        self.assertEqual(base_schedule(node, self.config, now=1000), (14400, 0, "low_battery_critical"))
        node["last_vbat_mv"] = 3400
        self.assertEqual(base_schedule(node, self.config, now=1000), (1200, 0, "low_battery"))
        node["last_vbat_mv"] = 3450
        self.assertEqual(base_schedule(node, self.config, now=1000), (300, 0, "interval"))

    def test_jitter_and_bounds(self):
        fixed = FixedRandom(90)
        self.assertEqual(jittered_next(100, self.config, fixed), 90)
        self.assertEqual(fixed.bounds, (90.0, 110.00000000000001))
        self.assertEqual(jittered_next(100, self.config, FixedRandom(110)), 110)
        self.assertEqual(jittered_next(10, self.config, FixedRandom(9)), 30)
        test_config = {"test_mode": True, "test_min_next_s": 5}
        self.assertEqual(jittered_next(5, test_config, FixedRandom(4.5)), 5)
        self.assertEqual(jittered_next(20000, test_config, FixedRandom(22000)), 15300)

    def test_jitter_randomized_bounds_property(self):
        rng = random.Random(20261109)
        cases = (
            ({"test_mode": False}, 30, (30, 100, 300, 14400)),
            ({"test_mode": True}, 5, (5, 10, 30, 300, 14400)),
        )
        for config, lower, bases in cases:
            for base in bases:
                expected_low = max(math.floor(0.9 * base), lower)
                expected_high = min(math.ceil(1.1 * base), 15300)
                self.assertLessEqual(expected_low, expected_high)
                for _ in range(1000):
                    value = jittered_next(base, config, rng)
                    self.assertGreaterEqual(value, expected_low)
                    self.assertLessEqual(value, expected_high)

    def test_jitter_boundary_clamps(self):
        normal_config = {"test_mode": False}
        test_config = {"test_mode": True}
        self.assertEqual(jittered_next(14400, normal_config, FixedRandom(15840)), 15300)
        self.assertEqual(jittered_next(10, normal_config, FixedRandom(9)), 30)
        self.assertEqual(jittered_next(10, test_config, FixedRandom(9)), 9)

    def test_test_mode_short_discovery(self):
        cfg = {"test_mode": True, "test_discovered_next_s": 5}
        self.assertEqual(base_schedule({"state": "DISCOVERED"}, cfg)[0], 5)

    def test_online_threshold(self):
        node = {"last_seen": 100.0, "next_given": 300}
        self.assertEqual(online_status(node, now=609.9), "online")
        self.assertEqual(online_status(node, now=610.1), "offline")
        self.assertEqual(online_status({}, now=100), "offline")

    def test_decide_returns_base_and_reason(self):
        fixed = FixedRandom(600)
        next_s, hold, base, reason = decide_next(
            self.node(interval_s=600), self.config, rng=fixed, now=0
        )
        self.assertEqual((next_s, hold, base, reason), (600, 0, 600, "interval"))
        self.assertEqual(fixed.bounds, (540.0, 660.0))


if __name__ == "__main__":
    unittest.main()
