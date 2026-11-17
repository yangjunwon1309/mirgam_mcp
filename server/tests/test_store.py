import tempfile
import unittest
from pathlib import Path

from server.store import Store


def checkin_body(seq=1):
    return {
        "v": 1, "fw": "beacon-0.1.0", "boot": "rtc", "seq": seq,
        "vbat_mv": 3980, "rssi": -55, "ch": 6,
        "t": {"wifi_ms": 640, "fast": 1, "prev_awake_ms": 2100, "prev_result": "ok"},
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="beacon-store-test-")
        self.store = Store(Path(self.temp.name) / "beacon.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def attached(self, node_id="tc-a1b2c3", interval=300):
        self.store.ensure_node(node_id, now=1000)
        return self.store.attach(node_id, "test", interval)

    def test_wal_and_attach_token(self):
        self.assertEqual(self.store.db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        node = self.attached()
        self.assertEqual(node["state"], "ATTACHED")
        self.assertEqual(len(node["token"]), 32)
        self.assertEqual(node["token_sent"], 0)

    def test_one_shot_token_and_token_reset(self):
        node = self.attached()
        token = node["token"]
        status, updated, issued = self.store.register_checkin(
            "tc-a1b2c3", checkin_body(), "192.168.25.20", "", 1001
        )
        self.assertEqual(status, "ok")
        self.assertEqual(issued, token)
        self.assertEqual(updated["state"], "ATTACHED")
        status, _updated, issued = self.store.register_checkin(
            "tc-a1b2c3", checkin_body(2), "192.168.25.20", token, 1002
        )
        self.assertEqual((status, issued), ("ok", None))
        status, _, _ = self.store.register_checkin(
            "tc-a1b2c3", checkin_body(3), "192.168.25.20", "0" * 32, 1003
        )
        self.assertEqual(status, "unauthorized")
        status, updated, issued = self.store.register_checkin(
            "tc-a1b2c3", checkin_body(4), "192.168.25.20", "", 1004
        )
        self.assertEqual(status, "ok")
        self.assertEqual(updated["state"], "DISCOVERED")
        self.assertIsNone(issued)

    def test_dispatch_retry_limit_and_no_result(self):
        node = self.attached()
        cmd_id = self.store.create_command(node["id"], "sensor", {}, 1000)
        first = self.store.dispatch_commands(node["id"], 1000)
        self.assertEqual([item["id"] for item in first], [cmd_id])
        self.assertEqual(first[0]["attempts"], 1)
        self.assertEqual(self.store.dispatch_commands(node["id"], 1119), [])
        second = self.store.dispatch_commands(node["id"], 1120)
        self.assertEqual(second[0]["attempts"], 2)
        third = self.store.dispatch_commands(node["id"], 1240)
        self.assertEqual(third[0]["attempts"], 3)
        self.assertEqual(self.store.dispatch_commands(node["id"], 1360), [])
        command = self.store.get_command(cmd_id)
        self.assertEqual((command["state"], command["reason"]), ("failed", "no_result"))

    def test_expiry_and_detach_expire_queued(self):
        node = self.attached()
        expired_id = self.store.create_command(node["id"], "sensor", {}, 1000)
        self.assertEqual(self.store.dispatch_commands(node["id"], 1900), [])
        self.assertEqual(self.store.get_command(expired_id)["state"], "expired")
        queued_id = self.store.create_command(node["id"], "image", {}, 2000)
        self.assertTrue(self.store.detach(node["id"], 2001))
        self.assertEqual(self.store.get_command(queued_id)["reason"], "detached")

    def test_low_battery_fails_queued_images(self):
        node = self.attached()
        cmd_id = self.store.create_command(node["id"], "image", {}, 1000)
        self.store.fail_queued_images_low_battery(node["id"], 1001)
        item = self.store.get_command(cmd_id)
        self.assertEqual((item["state"], item["reason"]), ("failed", "low_battery"))

    def test_duplicate_result_and_cross_node_rejected(self):
        first = self.attached("tc-a1b2c3")
        self.attached("tc-d4e5f6")
        cmd_id = self.store.create_command(first["id"], "sensor", {}, 1000)
        self.store.dispatch_commands(first["id"], 1000)
        body = {"ok": 1, "sensors": []}
        self.assertEqual(self.store.save_reading(first["id"], cmd_id, 1001, body), "inserted")
        self.assertEqual(self.store.save_reading(first["id"], cmd_id, 1002, body), "dup")
        self.assertEqual(self.store.save_reading("tc-d4e5f6", cmd_id, 1003, body), "not_found")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 1)

    def test_image_result_deduplicates(self):
        node = self.attached()
        cmd_id = self.store.create_command(node["id"], "image", {}, 1000)
        self.store.dispatch_commands(node["id"], 1000)
        args = (node["id"], cmd_id, 1001, "/tmp/test.jpg", 100, 640, 480, 500)
        self.assertEqual(self.store.save_image(*args), "inserted")
        self.assertEqual(self.store.save_image(*args), "dup")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM images").fetchone()[0], 1)

    def test_checkin_persists_energy_fields(self):
        self.attached()
        self.store.register_checkin(
            "tc-a1b2c3", checkin_body(), "192.168.25.20", "", 1001
        )
        self.store.record_checkin("tc-a1b2c3", checkin_body(), 300, 1001)
        rows = self.store.energy_rows("tc-a1b2c3")
        self.assertEqual(rows[0]["wifi_ms"], 640)
        self.assertEqual(rows[0]["prev_awake_ms"], 2100)
        self.assertEqual(rows[0]["next_given"], 300)


if __name__ == "__main__":
    unittest.main()
