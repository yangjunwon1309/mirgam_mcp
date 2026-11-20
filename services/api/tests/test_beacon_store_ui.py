import base64
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.schemas import BeaconDataDeleteRequest
from app.services.beacon_store import BeaconStore
from app.services.sqlite_store import SQLiteStore


class BeaconStoreUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.db_path = self.base / "state" / "test.db"
        self.data_root = self.base / "a" / "b"
        self.data_root.mkdir(parents=True)
        SQLiteStore(str(self.db_path)).initialize()
        self.store = BeaconStore(self.db_path, self.data_root)
        self.store.initialize()
        self.node, self.other, self.account = "tc-abcdef", "tc-123456", 1
        self.label = "Node A"
        self.readings = {"temp": [], "humidity": [], "foreign": []}
        self.checkins, self.assets, self.files = [], [], []
        self._seed()

    def tearDown(self):
        self.temp.cleanup()

    def _seed(self):
        db = self.store._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            for node, account, label in ((self.node, 1, self.label), (self.other, 2, "Other")):
                meta = json.dumps({"schema_version": 1, "label": label, "sensors": []})
                db.execute("""INSERT INTO beacon_node_profiles(
                    node_id,account_id,farm_id,label,metadata_json,interval_s,requested_data_json,
                    next_collection_at,created_at,updated_at)
                    VALUES(?,?,NULL,?,?,300,'["sensor"]',0,?,?)""",
                    (node, account, label, meta, now, now))
            devices = [
                ("temp-a", self.node, "temperature", "온도", "°C", "sht30", 68, "t_c", "temp"),
                ("humid-a", self.node, "humidity", "습도", "%RH", "sht30", 68, "rh", "humidity"),
                ("foreign-temp", self.other, "temperature", "다른 온도", "°C", "sht30", 69, "t_c", "foreign"),
            ]
            for sid, node, stype, display, unit, model, addr, field, _ in devices:
                meta = json.dumps({"source": "beacon", "beacon_node_id": node,
                                   "sensor_type": model, "sensor_address": addr, "sensor_field": field})
                db.execute("""INSERT INTO sensor_devices(
                    sensor_id,zone_id,sensor_type,display_name,unit,status,metadata_json)
                    VALUES(?,NULL,?,?,?,'active',?)""", (sid, stype, display, unit, meta))
            for i in range(5):
                recorded = f"2026-11-{10+i:02d}T12:00:00+00:00"
                for sid, metric, unit, value, key in (
                    ("temp-a", "temperature", "°C", 20+i, "temp"),
                    ("humid-a", "humidity", "%RH", 60+i, "humidity"),
                    ("foreign-temp", "temperature", "°C", 25+i, "foreign"),
                ):
                    cur = db.execute("""INSERT INTO sensor_readings(
                        sensor_id,metric,value,unit,recorded_at,source,quality,payload_json)
                        VALUES(?,?,?,?,?,'beacon','reported','{}')""",
                        (sid, metric, value, unit, recorded))
                    self.readings[key].append(str(cur.lastrowid))
            for node, label in ((self.node, self.label), (self.other, "Other")):
                db.execute("""INSERT INTO camera_devices(
                    camera_id,zone_id,display_name,camera_type,status,metadata_json)
                    VALUES(?,NULL,?,'timer_camera','active',?)""",
                    (f"beacon:{node}", label, json.dumps({"beacon_node_id": node})))
            jpeg = base64.b64decode(
                "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd3eHqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq6/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA//9k="
            )
            jpeg = jpeg[:-2] + b"\xff\xd9"
            for i, cid in enumerate((201, 202, 203)):
                asset = f"beacon-command-{cid}"
                relative = f"raw/beacons/{self.node}/{cid}.jpg"
                file = self.data_root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(jpeg)
                self.assets.append(asset)
                self.files.append(file)
                db.execute("""INSERT INTO camera_assets(
                    asset_id,camera_id,captured_at,file_path,sha256,content_type,byte_size,
                    width,height,created_at)
                    VALUES(?,?,?, ?,NULL,'image/jpeg',1000,640,480,?)""",
                    (asset, f"beacon:{self.node}", f"2026-11-{10+i:02d}T12:00:00+00:00",
                     relative, now))
            foreign_file = self.data_root / "raw/beacons/tc-123456/foreign.jpg"
            foreign_file.parent.mkdir(parents=True, exist_ok=True)
            foreign_file.write_bytes(jpeg)
            db.execute("""INSERT INTO camera_assets(
                asset_id,camera_id,captured_at,file_path,sha256,content_type,byte_size,width,height,created_at)
                VALUES('beacon-command-299',?,?,? ,NULL,'image/jpeg',1000,640,480,?)""",
                (f"beacon:{self.other}", "2026-11-10T12:00:00+00:00",
                 "raw/beacons/tc-123456/foreign.jpg", now))
            for i in range(5):
                cur = db.execute("""INSERT INTO beacon_node_checkins(
                    node_id,received_at,seq,boot,vbat_mv,rssi,channel,wifi_ms,fast,
                    prev_awake_ms,prev_result,next_given)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (self.node, 1794000000+i*60, i+1, "rtc", 3900, -50, 8, 500, 1, 2000, "ok", 300))
                self.checkins.append(str(cur.lastrowid))
            db.execute("""INSERT INTO beacon_node_checkins(
                node_id,received_at,seq,boot,vbat_mv,rssi,channel,wifi_ms,fast,
                prev_awake_ms,prev_result,next_given)
                VALUES(?,?,1,'cold',3900,-55,8,700,0,2500,'ok',300)""",
                (self.other, 1794000000))
            for cid in (201, 202, 203):
                db.execute("""INSERT INTO beacon_commands(
                    command_id,node_id,account_id,command_type,params_json,state,reason,attempts,
                    created_at,dispatched_at,done_at,result_json,image_asset_id,synced_at)
                    VALUES(?,?,1,'image','{}','done',NULL,1,?,?,?,'{}',?,?)""",
                    (cid, self.node, 1794000000+cid, 1794000010+cid, 1794000020+cid,
                     f"beacon-command-{cid}", now))
                db.execute("""INSERT INTO beacon_sensor_results(
                    command_id,node_id,account_id,received_at,ok,raw_json) VALUES(?,?,1,?,1,'{}')""",
                    (cid, self.node, now))
            db.execute("""INSERT INTO beacon_commands(
                command_id,node_id,account_id,command_type,params_json,state,reason,attempts,
                created_at,dispatched_at,done_at,result_json,image_asset_id,synced_at)
                VALUES(204,?,1,'sensor','{}','queued',NULL,0,?,NULL,NULL,NULL,NULL,NULL)""",
                (self.node, 1794000300))
            db.execute("""INSERT INTO beacon_commands(
                command_id,node_id,account_id,command_type,params_json,state,reason,attempts,
                created_at,dispatched_at,done_at,result_json,image_asset_id,synced_at)
                VALUES(299,?,2,'image','{}','done',NULL,1,?,NULL,NULL,'{}',NULL,?)""",
                (self.other, 1794000000, now))
            db.commit()
        finally:
            db.close()

    def count(self, table):
        db = self.store._connect()
        try:
            return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            db.close()

    def delete(self, kind, **kwargs):
        return self.store.delete_data(1, self.node, {"kind": kind, **kwargs})

    def test_latest_readings_order_and_values(self):
        db = self.store._connect()
        try:
            rows = self.store._latest_readings(db, self.node)
        finally:
            db.close()
        self.assertEqual([r["sensor_type"] for r in rows], ["temperature", "humidity"])
        self.assertEqual((rows[0]["value"], rows[0]["unit"]), (24.0, "°C"))
        self.assertEqual(rows[0]["recorded_at"], "2026-11-14T12:00:00+00:00")
        self.assertEqual(rows[1]["value"], 64.0)

    def test_detail_has_ids_and_counts(self):
        detail = self.store.detail(1, self.node)
        self.assertEqual((detail["image_count"], detail["checkin_count"]), (3, 5))
        self.assertEqual(len(detail["sensors"]), 2)
        for item in detail["sensors"]:
            self.assertEqual(item["reading_count"], 5)
            self.assertIn("reading_id", item["latest_reading"])
            self.assertIn("reading_id", item["readings"][0])

    def test_delete_sensor_ids(self):
        result = self.delete("sensor", mode="ids", ids=self.readings["temp"][:3])
        self.assertEqual((result["matched"], result["deleted"]), (3, 3))
        self.assertEqual(self.count("sensor_readings"), 12)
        self.assertEqual(self.count("beacon_data_deletions"), 1)

    def test_delete_sensor_ids_foreign_ignored(self):
        result = self.delete("sensor", mode="ids",
                             ids=[self.readings["temp"][0], self.readings["foreign"][0], "987654321"])
        self.assertEqual((result["matched"], result["deleted"]), (1, 1))
        self.assertEqual(self.count("sensor_readings"), 14)

    def test_delete_sensor_before_scoped(self):
        result = self.delete("sensor", mode="before",
                             before=datetime(2026, 11, 13, tzinfo=timezone.utc), sensor_ids=["temp-a"])
        self.assertEqual((result["matched"], result["deleted"]), (3, 3))
        db = self.store._connect()
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sensor_readings WHERE sensor_id='temp-a'").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sensor_readings WHERE sensor_id='humid-a'").fetchone()[0], 5)
        finally:
            db.close()

    def test_dry_run_writes_nothing(self):
        tables = ("sensor_readings", "camera_assets", "beacon_node_checkins",
                  "beacon_commands", "beacon_sensor_results", "beacon_data_deletions")
        before = {table: self.count(table) for table in tables}
        files = [p.read_bytes() for p in self.files]
        requests = [
            {"kind": "sensor", "mode": "ids", "ids": [self.readings["temp"][0]]},
            {"kind": "image", "mode": "ids", "ids": ["beacon-command-201"]},
            {"kind": "checkin", "mode": "ids", "ids": [self.checkins[0]]},
            {"kind": "command", "mode": "ids", "ids": ["201"]},
        ]
        for request in requests:
            self.assertTrue(self.store.delete_data(1, self.node, {**request, "dry_run": True})["dry_run"])
        self.assertEqual(before, {table: self.count(table) for table in tables})
        self.assertEqual(files, [p.read_bytes() for p in self.files])

    def test_delete_all_requires_label(self):
        with self.assertRaisesRegex(ValueError, "장치 이름이 일치하지 않습니다"):
            self.delete("sensor", mode="all", all=True, confirm_label="Wrong")
        self.assertEqual(self.count("beacon_data_deletions"), 0)
        result = self.delete("sensor", mode="all", all=True, confirm_label=self.label)
        self.assertEqual((result["matched"], result["deleted"]), (10, 10))

    def test_delete_image_removes_file_and_row(self):
        result = self.delete("image", mode="ids", ids=["beacon-command-201"])
        self.assertEqual((result["matched"], result["deleted"], result["freed_bytes"]), (1, 1, 1000))
        self.assertFalse(self.files[0].exists())
        db = self.store._connect()
        try:
            self.assertIsNone(db.execute("SELECT image_asset_id FROM beacon_commands WHERE command_id=201").fetchone()[0])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM camera_assets WHERE asset_id='beacon-command-201'").fetchone()[0], 0)
        finally:
            db.close()

    def test_delete_image_path_escape_blocked(self):
        outside = self.base / "evil.jpg"
        outside.write_bytes(b"keep")
        db = self.store._connect()
        try:
            db.execute("""INSERT INTO camera_assets(
                asset_id,camera_id,captured_at,file_path,sha256,content_type,byte_size,width,height,created_at)
                VALUES('beacon-command-205',?,?,?,NULL,'image/jpeg',12,640,480,?)""",
                (f"beacon:{self.node}", "2026-11-15T12:00:00+00:00",
                 "raw/beacons/tc-abcdef/../../../../evil.jpg", datetime.now(timezone.utc).isoformat()))
            db.commit()
        finally:
            db.close()
        result = self.delete("image", mode="ids", ids=["beacon-command-205"])
        self.assertEqual((result["deleted"], result["file_errors"]), (1, 1))
        self.assertEqual(outside.read_bytes(), b"keep")

    def test_delete_checkin_keeps_latest(self):
        result = self.delete("checkin", mode="all", all=True, confirm_label=self.label)
        self.assertEqual((result["matched"], result["deleted"], result["skipped_current"]), (5, 4, 1))
        db = self.store._connect()
        try:
            rows = db.execute("SELECT checkin_id FROM beacon_node_checkins WHERE node_id=?", (self.node,)).fetchall()
        finally:
            db.close()
        self.assertEqual([row[0] for row in rows], [int(self.checkins[-1])])

    def test_delete_command_skips_busy(self):
        result = self.delete("command", mode="all", all=True, confirm_label=self.label)
        self.assertEqual((result["matched"], result["deleted"], result["skipped_busy"]), (4, 3, 1))
        db = self.store._connect()
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM beacon_sensor_results WHERE command_id IN (201,202,203)").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM beacon_commands WHERE command_id=204").fetchone()[0], 1)
        finally:
            db.close()

    def test_not_owner_is_keyerror(self):
        with self.assertRaises(KeyError):
            self.store.delete_data(2, self.node, {
                "kind": "sensor", "mode": "all", "all": True, "confirm_label": self.label
            })

    def test_bad_id_format(self):
        with self.assertRaisesRegex(ValueError, "ID 형식"):
            self.delete("sensor", mode="ids", ids=["abc"])

    def test_request_model_modes(self):
        self.assertEqual(BeaconDataDeleteRequest(kind="image", ids=["beacon-command-12"]).mode, "ids")
        invalid = (
            {"kind": "sensor"},
            {"kind": "sensor", "ids": ["1"], "all": True},
            {"kind": "sensor", "before": "2026-11-01T00:00:00"},
            {"kind": "image", "all": True, "sensor_ids": ["x"]},
        )
        for payload in invalid:
            with self.assertRaises(ValidationError):
                BeaconDataDeleteRequest.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
