"""Local mirror for Beacon nodes and their sensor/image results.

Beacon remains the source of truth for node protocol state. This store keeps
dashboard metadata and mirrors completed results into MIRGAM's existing sensor
and camera tables so the dashboard and MCP SQLite tools share one data model.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


FIELD_INFO: dict[str, tuple[str, str, str]] = {
    "t_c": ("temperature", "°C", "기온"),
    "temp_c": ("temperature", "°C", "기온"),
    "temperature": ("temperature", "°C", "기온"),
    "rh": ("humidity", "%RH", "습도"),
    "rh_pct": ("humidity", "%RH", "습도"),
    "humidity": ("humidity", "%RH", "습도"),
    "soil_moisture": ("soil_moisture", "%", "토양 수분"),
    "moisture_pct": ("soil_moisture", "%", "토양 수분"),
    "lux": ("illuminance", "lx", "조도"),
    "light_lux": ("illuminance", "lx", "조도"),
    "co2_ppm": ("co2", "ppm", "이산화탄소"),
}


def _utc(value: object) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class BeaconStore:
    def __init__(self, database_path: str | Path, data_root: str | Path):
        self.database_path = Path(database_path)
        self.data_root = Path(data_root)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS beacon_node_profiles (
                    node_id TEXT PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    farm_id TEXT,
                    label TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    interval_s INTEGER NOT NULL DEFAULT 300,
                    requested_data_json TEXT NOT NULL DEFAULT '["sensor"]',
                    next_collection_at REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS beacon_profiles_account_idx
                    ON beacon_node_profiles(account_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS beacon_node_checkins (
                    checkin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    seq INTEGER,
                    boot TEXT,
                    vbat_mv INTEGER,
                    rssi INTEGER,
                    channel INTEGER,
                    wifi_ms INTEGER,
                    fast INTEGER,
                    prev_awake_ms INTEGER,
                    prev_result TEXT,
                    next_given INTEGER,
                    UNIQUE(node_id, received_at)
                );
                CREATE INDEX IF NOT EXISTS beacon_checkins_node_time_idx
                    ON beacon_node_checkins(node_id, received_at DESC);

                CREATE TABLE IF NOT EXISTS beacon_commands (
                    command_id INTEGER PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    command_type TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reason TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL,
                    dispatched_at REAL,
                    done_at REAL,
                    result_json TEXT,
                    image_asset_id TEXT,
                    synced_at TEXT
                );
                CREATE INDEX IF NOT EXISTS beacon_commands_node_time_idx
                    ON beacon_commands(node_id, command_id DESC);
                CREATE INDEX IF NOT EXISTS beacon_commands_pending_idx
                    ON beacon_commands(state, synced_at);

                CREATE TABLE IF NOT EXISTS beacon_sensor_results (
                    command_id INTEGER PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS beacon_data_deletions (
                    deletion_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    node_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    matched INTEGER NOT NULL,
                    deleted INTEGER NOT NULL,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    freed_bytes INTEGER NOT NULL DEFAULT 0,
                    criteria_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS beacon_data_deletions_node_idx
                    ON beacon_data_deletions(node_id, created_at DESC);
                """
            )
            profile_columns = {row[1] for row in db.execute("PRAGMA table_info(beacon_node_profiles)")}
            if "farm_id" not in profile_columns:
                db.execute("ALTER TABLE beacon_node_profiles ADD COLUMN farm_id TEXT")

    @staticmethod
    def _assert_owner(db: sqlite3.Connection, account_id: int, node_id: str) -> None:
        row = db.execute(
            "SELECT account_id FROM beacon_node_profiles WHERE node_id=?", (node_id,)
        ).fetchone()
        if row is not None and int(row["account_id"]) != account_id:
            raise PermissionError("이 beacon은 다른 계정에 등록되어 있습니다.")

    def save_profile(
        self,
        account_id: int,
        node_id: str,
        farm_id: str | None,
        metadata: dict[str, Any],
        interval_s: int,
        requested_data: list[str],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        label = str(metadata.get("label") or node_id).strip()[:64] or node_id
        metadata["schema_version"] = 1
        metadata["label"] = label
        with self._connect() as db:
            self._assert_owner(db, account_id, node_id)
            db.execute(
                """INSERT INTO beacon_node_profiles(
                       node_id,account_id,farm_id,label,metadata_json,interval_s,requested_data_json,
                       next_collection_at,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,0,?,?)
                   ON CONFLICT(node_id) DO UPDATE SET farm_id=excluded.farm_id,label=excluded.label,
                       metadata_json=excluded.metadata_json,interval_s=excluded.interval_s,
                       requested_data_json=excluded.requested_data_json,updated_at=excluded.updated_at""",
                (node_id, account_id, farm_id, label, _json(metadata), interval_s,
                 _json(requested_data), now, now),
            )
        return {"node_id": node_id, "account_id": account_id, "farm_id": farm_id, "label": label,
                "metadata": metadata, "interval_s": interval_s,
                "requested_data": requested_data, "updated_at": now}

    def profile(self, account_id: int, node_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM beacon_node_profiles WHERE node_id=? AND account_id=?",
                (node_id, account_id),
            ).fetchone()
        if row is None:
            return None
        return self._profile_dict(dict(row))

    def _profile_dict(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            metadata = json.loads(row.pop("metadata_json"))
        except (TypeError, json.JSONDecodeError):
            metadata = {"schema_version": 1, "label": row.get("label")}
        try:
            requested = json.loads(row.pop("requested_data_json"))
        except (TypeError, json.JSONDecodeError):
            requested = ["sensor"]
        return {**row, "metadata": metadata, "requested_data": requested}

    def visible_node_ids(self, account_id: int) -> set[str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT node_id FROM beacon_node_profiles WHERE account_id=?", (account_id,)
            ).fetchall()
        return {str(row["node_id"]) for row in rows}

    def _latest_readings(self, db: sqlite3.Connection, node_id: str, limit: int = 4) -> list[dict[str, Any]]:
        rows = db.execute(
            """SELECT d.sensor_id,d.display_name,d.sensor_type,d.unit,
                      r.value,r.unit AS reading_unit,r.recorded_at
               FROM sensor_devices d
               LEFT JOIN sensor_readings r ON r.reading_id=(
                   SELECT reading_id FROM sensor_readings
                   WHERE sensor_id=d.sensor_id
                   ORDER BY recorded_at DESC,reading_id DESC LIMIT 1)
               WHERE json_extract(d.metadata_json,'$.beacon_node_id')=?
                 AND d.status='active'
               ORDER BY CASE d.sensor_type
                   WHEN 'temperature' THEN 0 WHEN 'humidity' THEN 1 ELSE 2 END,
                   d.display_name
               LIMIT ?""",
            (node_id, max(0, limit)),
        ).fetchall()
        return [
            {
                "sensor_id": row["sensor_id"],
                "display_name": row["display_name"],
                "sensor_type": row["sensor_type"],
                "value": float(row["value"]) if row["value"] is not None else None,
                "unit": row["reading_unit"] or row["unit"],
                "recorded_at": row["recorded_at"],
            }
            for row in rows
        ]

    def cached_nodes(self, account_id: int) -> list[dict[str, Any]]:
        output = []
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM beacon_node_profiles WHERE account_id=? ORDER BY updated_at DESC",
                (account_id,),
            ).fetchall()
            for raw in rows:
                profile = self._profile_dict(dict(raw))
                if profile is None:
                    continue
                node_id = str(profile["node_id"])
                output.append({
                    "node_id": node_id, "state": "UNKNOWN", "online": False,
                    "farm_id": profile["farm_id"],
                    "first_seen": None, "last_seen": None, "next_given": None, "last_ip": None,
                    "last_rssi": None, "last_vbat_mv": None, "last_seq": None, "last_ch": None, "fw": None,
                    "last_boot": None, "last_wifi_ms": None, "last_fast": None,
                    "last_prev_awake_ms": None, "last_prev_result": None,
                    "label": profile["label"], "metadata": profile["metadata"],
                    "interval_s": profile["interval_s"], "requested_data": profile["requested_data"],
                    "registered": True, "sensor_count": len(profile["metadata"].get("sensors") or []),
                    "pending_commands": 0, "next_expected_at": None,
                    "latest_readings": self._latest_readings(db, node_id),
                })
        return output

    def record_checkin_snapshot(self, node: dict[str, Any]) -> None:
        last_seen = node.get("last_seen")
        if not isinstance(last_seen, (int, float)) or last_seen <= 0:
            return
        with self._connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO beacon_node_checkins(
                       node_id,received_at,seq,boot,vbat_mv,rssi,channel,wifi_ms,fast,
                       prev_awake_ms,prev_result,next_given
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (node["id"], float(last_seen), node.get("last_seq"), node.get("last_boot"),
                 node.get("last_vbat_mv"), node.get("last_rssi"), node.get("last_ch"),
                 node.get("last_wifi_ms"), node.get("last_fast"), node.get("last_prev_awake_ms"),
                 node.get("last_prev_result"), node.get("next_given")),
            )

    def record_command(self, account_id: int, node_id: str, command_type: str,
                       params: dict[str, Any], remote: dict[str, Any]) -> None:
        with self._connect() as db:
            self._assert_owner(db, account_id, node_id)
            db.execute(
                """INSERT INTO beacon_commands(
                       command_id,node_id,account_id,command_type,params_json,state,reason,
                       attempts,created_at,dispatched_at,done_at,result_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(command_id) DO UPDATE SET state=excluded.state,
                       reason=excluded.reason,attempts=excluded.attempts,
                       dispatched_at=excluded.dispatched_at,done_at=excluded.done_at,
                       result_json=COALESCE(excluded.result_json,beacon_commands.result_json)""",
                (int(remote["cmd_id"]), node_id, account_id, command_type, _json(params),
                 remote.get("state", "queued"), None, 0, datetime.now(timezone.utc).timestamp(),
                 None, None, None),
            )

    def pending_commands(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT command_id,node_id FROM beacon_commands WHERE state NOT IN ('done','failed','expired') ORDER BY command_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def due_collections(self, now: float) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT p.* FROM beacon_node_profiles p
                   WHERE p.next_collection_at<=? AND p.requested_data_json!='[]'
                     AND NOT EXISTS (SELECT 1 FROM beacon_commands c WHERE c.node_id=p.node_id
                       AND c.state NOT IN ('done','failed','expired'))
                   ORDER BY p.next_collection_at LIMIT 20""",
                (now,),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            try:
                item["requested_data"] = json.loads(item["requested_data_json"])
            except (TypeError, json.JSONDecodeError):
                item["requested_data"] = []
            output.append(item)
        return output

    def postpone_collection(self, node_id: str, now: float, interval_s: int) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE beacon_node_profiles SET next_collection_at=?,updated_at=? WHERE node_id=?",
                (now + interval_s, datetime.now(timezone.utc).isoformat(), node_id),
            )

    def record_remote_command(self, command: dict[str, Any]) -> dict[str, Any] | None:
        command_id = int(command["id"])
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM beacon_commands WHERE command_id=?", (command_id,)
            ).fetchone()
            if existing is None:
                return None
            prior = dict(existing)
            if prior["synced_at"]:
                db.execute(
                    "UPDATE beacon_commands SET state=?,reason=?,attempts=?,dispatched_at=?,done_at=? WHERE command_id=?",
                    (command.get("state"), command.get("reason"), command.get("attempts", 0),
                     command.get("dispatched_at"), command.get("done_at"), command_id),
                )
                return None

            result = command.get("result")
            db.execute(
                """UPDATE beacon_commands SET state=?,reason=?,attempts=?,dispatched_at=?,done_at=?,result_json=?
                   WHERE command_id=?""",
                (command.get("state"), command.get("reason"), command.get("attempts", 0),
                 command.get("dispatched_at"), command.get("done_at"), _json(result) if result is not None else None,
                 command_id),
            )
            if command.get("state") not in {"done", "failed", "expired"}:
                return None

            if isinstance(result, dict) and result.get("kind") == "reading":
                body = result.get("body") if isinstance(result.get("body"), dict) else {}
                self._save_reading_result(db, prior, command, body)
            elif isinstance(result, dict) and result.get("kind") == "image":
                asset_id = self._save_image_result(db, prior, command, result)
                if asset_id:
                    db.execute("UPDATE beacon_commands SET image_asset_id=? WHERE command_id=?", (asset_id, command_id))
            db.execute(
                "UPDATE beacon_commands SET synced_at=? WHERE command_id=?",
                (datetime.now(timezone.utc).isoformat(), command_id),
            )
            return {"node_id": prior["node_id"], "command_id": command_id, "result": result}

    def _profile_metadata(self, db: sqlite3.Connection, node_id: str) -> dict[str, Any]:
        row = db.execute("SELECT metadata_json,label FROM beacon_node_profiles WHERE node_id=?", (node_id,)).fetchone()
        if row is None:
            return {"schema_version": 1, "label": node_id, "sensors": []}
        try:
            metadata = json.loads(row["metadata_json"])
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        metadata.setdefault("schema_version", 1)
        metadata.setdefault("label", row["label"])
        metadata.setdefault("sensors", [])
        return metadata

    def _save_reading_result(self, db: sqlite3.Connection, command: dict[str, Any],
                             remote: dict[str, Any], body: dict[str, Any]) -> None:
        node_id, account_id, command_id = command["node_id"], command["account_id"], int(remote["id"])
        result = remote.get("result") or {}
        received_at = _utc(result.get("received_at") or remote.get("done_at"))
        db.execute(
            "INSERT OR IGNORE INTO beacon_sensor_results(command_id,node_id,account_id,received_at,ok,raw_json) VALUES(?,?,?,?,?,?)",
            (command_id, node_id, account_id, received_at, int(bool(body.get("ok"))), _json(body)),
        )
        sensors = body.get("sensors") if isinstance(body.get("sensors"), list) else []
        metadata = self._profile_metadata(db, node_id)
        inventory = metadata.get("sensors") if isinstance(metadata.get("sensors"), list) else []
        discovered: dict[tuple[str, str], dict[str, Any]] = {}
        for sensor in sensors:
            if not isinstance(sensor, dict):
                continue
            sensor_type = str(sensor.get("type") or "unknown")[:48]
            address_value = sensor.get("addr", sensor.get("address"))
            address_key = str(address_value) if address_value is not None else "unknown"
            raw_id = str(sensor.get("sensor_id") or sensor.get("id") or "")
            inventory_key = (sensor_type, address_key)
            item_meta = next((x for x in inventory if isinstance(x, dict)
                              and str(x.get("type")) == sensor_type
                              and str(x.get("address", x.get("addr", "unknown"))) == address_key), {})
            discovered[inventory_key] = {
                **item_meta,
                "sensor_id": item_meta.get("sensor_id") or raw_id or f"{sensor_type}-{address_key}",
                "type": sensor_type,
                "model": item_meta.get("model") or sensor_type.upper(),
                "address": address_value,
                "bus": item_meta.get("bus") or "Grove-I2C",
                "location": item_meta.get("location") or "미지정",
                "enabled": item_meta.get("enabled", True),
                "units": item_meta.get("units") or {},
                "fields": sorted(str(k) for k,v in sensor.items() if isinstance(v,(int,float)) and not isinstance(v,bool)),
            }
            for field, value in sensor.items():
                if str(field).lower() in {"type", "id", "sensor_id", "addr", "address"}:
                    continue
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                metric, unit, metric_label = FIELD_INFO.get(str(field).lower(), (str(field)[:64], "raw", str(field)))
                units = item_meta.get("units") if isinstance(item_meta.get("units"), dict) else {}
                unit = str(units.get(field) or unit)
                sensor_id = f"beacon:{node_id}:{sensor_type}:{address_key}:{field}"
                display = f"{metadata.get('label') or node_id} · {sensor_type.upper()} {metric_label}"
                device_metadata = {
                    "source": "beacon", "beacon_node_id": node_id, "sensor_type": sensor_type,
                    "sensor_address": address_value, "sensor_field": field,
                    "sensor_metadata_id": discovered[inventory_key]["sensor_id"],
                    "location": discovered[inventory_key].get("location"),
                }
                db.execute(
                    """INSERT INTO sensor_devices(sensor_id,zone_id,sensor_type,display_name,unit,status,metadata_json)
                       VALUES(?,NULL,?,?,?,'active',?) ON CONFLICT(sensor_id) DO UPDATE SET
                       display_name=excluded.display_name,unit=excluded.unit,status='active',metadata_json=excluded.metadata_json""",
                    (sensor_id, metric, display, unit, _json(device_metadata)),
                )
                db.execute(
                    """INSERT INTO sensor_readings(sensor_id,metric,value,unit,recorded_at,source,quality,payload_json)
                       VALUES(?,?,?,?,?,'beacon','reported',?)""",
                    (sensor_id, metric, float(value), unit, received_at,
                     _json({"node_id": node_id, "command_id": command_id, "sensor": sensor, "raw": body})),
                )
        if discovered:
            merged = {(str(x.get("type")), str(x.get("address", x.get("addr", "unknown")))): x
                      for x in inventory if isinstance(x, dict)}
            merged.update(discovered)
            metadata["sensors"] = list(merged.values())
            db.execute(
                "UPDATE beacon_node_profiles SET metadata_json=?,updated_at=? WHERE node_id=?",
                (_json(metadata), datetime.now(timezone.utc).isoformat(), node_id),
            )

    def _save_image_result(self, db: sqlite3.Connection, command: dict[str, Any],
                           remote: dict[str, Any], result: dict[str, Any]) -> str | None:
        path = result.get("local_file_path")
        if not isinstance(path, str):
            return None
        node_id, command_id = command["node_id"], int(remote["id"])
        metadata = self._profile_metadata(db, node_id)
        camera_id = f"beacon:{node_id}"
        camera_meta = {"source": "beacon", "beacon_node_id": node_id,
                       "location": metadata.get("location"), "label": metadata.get("label")}
        db.execute(
            """INSERT INTO camera_devices(camera_id,zone_id,display_name,camera_type,status,metadata_json)
               VALUES(?,NULL,?,'timer_camera','active',?) ON CONFLICT(camera_id) DO UPDATE SET
               display_name=excluded.display_name,status='active',metadata_json=excluded.metadata_json""",
            (camera_id, f"{metadata.get('label') or node_id} · 비콘 카메라", _json(camera_meta)),
        )
        asset_id = f"beacon-command-{command_id}"
        relative_path = Path(path).resolve().relative_to(self.data_root.resolve()).as_posix()
        db.execute(
            """INSERT OR IGNORE INTO camera_assets(asset_id,camera_id,captured_at,file_path,sha256,content_type,
                   byte_size,width,height,created_at) VALUES(?,?,?,?,NULL,'image/jpeg',?,?,?,?)""",
            (asset_id,camera_id,_utc(result.get("received_at") or remote.get("done_at")),relative_path,
             int(result.get("bytes") or 0),int(result.get("width") or 0),int(result.get("height") or 0),
             datetime.now(timezone.utc).isoformat()),
        )
        return asset_id

    def list_history(self, account_id: int, node_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            self._assert_owner(db, account_id, node_id)
            rows = db.execute(
                "SELECT command_id,node_id,command_type,params_json,state,reason,attempts,created_at,dispatched_at,done_at,result_json,image_asset_id FROM beacon_commands WHERE node_id=? AND account_id=? ORDER BY command_id DESC LIMIT ?",
                (node_id, account_id, max(1, min(limit, 200))),
            ).fetchall()
        output=[]
        for row in rows:
            item=dict(row)
            for name in ("params_json","result_json"):
                try: item[name.removesuffix("_json")]=json.loads(item.pop(name)) if item[name] else None
                except (TypeError,json.JSONDecodeError): item[name.removesuffix("_json")]=None
            output.append(item)
        return output

    def detail(self, account_id: int, node_id: str) -> dict[str, Any]:
        with self._connect() as db:
            self._assert_owner(db, account_id, node_id)
            profile_row = db.execute(
                "SELECT * FROM beacon_node_profiles WHERE node_id=? AND account_id=?",
                (node_id, account_id),
            ).fetchone()
            if profile_row is None:
                raise KeyError(node_id)
            sensors = db.execute(
                """SELECT sensor_id,display_name,sensor_type,unit,status,metadata_json
                   FROM sensor_devices
                   WHERE json_extract(metadata_json,'$.beacon_node_id')=?
                   ORDER BY display_name""",
                (node_id,),
            ).fetchall()
            sensor_output = []
            for sensor in sensors:
                sensor_dict = dict(sensor)
                try:
                    sensor_dict["metadata"] = json.loads(sensor_dict.pop("metadata_json") or "{}")
                except (TypeError, json.JSONDecodeError):
                    sensor_dict["metadata"] = {}
                latest = db.execute(
                    """SELECT reading_id,value,unit,recorded_at,quality FROM sensor_readings
                       WHERE sensor_id=? ORDER BY recorded_at DESC,reading_id DESC LIMIT 1""",
                    (sensor["sensor_id"],),
                ).fetchone()
                history = db.execute(
                    """SELECT reading_id,value,unit,recorded_at,quality FROM sensor_readings
                       WHERE sensor_id=? ORDER BY recorded_at DESC,reading_id DESC LIMIT 96""",
                    (sensor["sensor_id"],),
                ).fetchall()
                reading_count = db.execute(
                    "SELECT COUNT(*) FROM sensor_readings WHERE sensor_id=?",
                    (sensor["sensor_id"],),
                ).fetchone()[0]
                sensor_output.append({
                    "device": sensor_dict,
                    "latest_reading": dict(latest) if latest else None,
                    "readings": [dict(row) for row in reversed(history)],
                    "reading_count": int(reading_count),
                })
            image_where = """FROM camera_assets a
                JOIN camera_devices c ON c.camera_id=a.camera_id
                WHERE json_extract(c.metadata_json,'$.beacon_node_id')=?"""
            assets = db.execute(
                """SELECT a.asset_id,a.captured_at,a.byte_size,a.width,a.height,a.content_type """
                + image_where
                + " ORDER BY a.captured_at DESC LIMIT 30",
                (node_id,),
            ).fetchall()
            image_count = db.execute(
                "SELECT COUNT(*) " + image_where,
                (node_id,),
            ).fetchone()[0]
            checkins = db.execute(
                """SELECT * FROM beacon_node_checkins
                   WHERE node_id=? ORDER BY received_at DESC LIMIT 48""",
                (node_id,),
            ).fetchall()
            checkin_count = db.execute(
                "SELECT COUNT(*) FROM beacon_node_checkins WHERE node_id=?",
                (node_id,),
            ).fetchone()[0]
        profile = self._profile_dict(dict(profile_row))
        return {
            "profile": profile,
            "sensors": sensor_output,
            "images": [dict(row) for row in assets],
            "image_count": int(image_count),
            "commands": self.list_history(account_id, node_id),
            "checkins": [dict(row) for row in reversed(checkins)],
            "checkin_count": int(checkin_count),
        }

    def update_node_snapshot(self, account_id: int, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        visible=self.visible_node_ids(account_id)
        output=[]
        for node in nodes:
            node_id=str(node.get("id") or "")
            if not node_id:
                continue
            profile=self.profile(account_id,node_id)
            if profile is None and node_id in visible:
                continue
            self.record_checkin_snapshot(node)
            sensor_count=0
            if profile:
                try:
                    metadata=json.loads(json.dumps(profile["metadata"]))
                    sensor_count=len(metadata.get("sensors") or [])
                except (TypeError,ValueError): pass
            with self._connect() as db:
                pending=db.execute("SELECT COUNT(*) FROM beacon_commands WHERE node_id=? AND account_id=? AND state NOT IN ('done','failed','expired')",(node_id,account_id)).fetchone()[0]
                latest_readings=self._latest_readings(db,node_id)
            output.append({
                "node_id":node_id,"state":node.get("state","DISCOVERED"),"online":bool(node.get("online")),
                "farm_id":(profile or {}).get("farm_id"),
                "first_seen":node.get("first_seen"),"last_seen":node.get("last_seen"),
                "next_given":node.get("next_given"),"last_ip":node.get("last_ip"),
                "last_rssi":node.get("last_rssi"),"last_vbat_mv":node.get("last_vbat_mv"),
                "last_seq":node.get("last_seq"),"last_ch":node.get("last_ch"),"fw":node.get("fw"),
                "last_boot":node.get("last_boot"),"last_wifi_ms":node.get("last_wifi_ms"),
                "last_fast":node.get("last_fast"),"last_prev_awake_ms":node.get("last_prev_awake_ms"),
                "last_prev_result":node.get("last_prev_result"),
                "label":(profile or {}).get("label") or node.get("label") or node_id,
                "metadata":(profile or {}).get("metadata") or {"schema_version":1,"label":node.get("label") or node_id,"location":{},"sensors":[]},
                "interval_s":(profile or {}).get("interval_s") or node.get("interval_s",300),
                "requested_data":(profile or {}).get("requested_data") or [],
                "registered":profile is not None,"sensor_count":sensor_count,"pending_commands":pending,
                "latest_readings":latest_readings,
                "next_expected_at":(float(node.get("last_seen") or 0)+int(node.get("next_given") or 0)) or None,
            })
        return output


    def delete_data(self, account_id: int, node_id: str, req: dict[str, Any]) -> dict[str, Any]:
        kind = req.get("kind")
        mode = req.get("mode")
        ids = req.get("ids")
        sensor_ids = req.get("sensor_ids")
        before = req.get("before")
        dry_run = bool(req.get("dry_run", False))
        if kind not in {"sensor", "image", "checkin", "command"}:
            raise ValueError("삭제 종류가 올바르지 않습니다.")
        if mode not in {"ids", "before", "all"}:
            raise ValueError("삭제 방식이 올바르지 않습니다.")
        if mode == "ids":
            if not isinstance(ids, list) or not ids:
                raise ValueError("ids 모드에는 하나 이상의 ID가 필요합니다.")
            pattern = r"^beacon-command-\d{1,18}$" if kind == "image" else r"^\d{1,18}$"
            if any(not isinstance(item, str) or re.fullmatch(pattern, item) is None for item in ids):
                raise ValueError("삭제 ID 형식이 올바르지 않습니다.")
        if sensor_ids is not None and (
            kind != "sensor" or mode == "ids" or not isinstance(sensor_ids, list) or not sensor_ids
        ):
            raise ValueError("sensor_ids는 센서의 기간·전체 삭제에서만 사용할 수 있습니다.")
        if mode == "before" and not isinstance(before, datetime):
            raise ValueError("before에는 시간대가 있는 날짜가 필요합니다.")
        if isinstance(before, datetime) and before.tzinfo is None:
            raise ValueError("before에는 시간대가 있어야 합니다.")

        table, pk, time_column = {
            "sensor": ("sensor_readings", "reading_id", "recorded_at"),
            "image": ("camera_assets", "asset_id", "captured_at"),
            "checkin": ("beacon_node_checkins", "checkin_id", "received_at"),
            "command": ("beacon_commands", "command_id", "created_at"),
        }[kind]
        if kind == "image":
            select_columns = "asset_id AS row_id,captured_at AS happened,file_path,byte_size"
        else:
            select_columns = f"{pk} AS row_id,{time_column} AS happened"

        if mode == "before":
            before_value: str | float = (
                before.astimezone(timezone.utc).isoformat()
                if kind in {"sensor", "image"}
                else before.timestamp()
            )
        else:
            before_value = ""

        def make_where(db: sqlite3.Connection) -> tuple[str, list[Any]]:
            clauses: list[str] = []
            params: list[Any] = []
            if kind == "sensor":
                owned = [
                    str(row[0]) for row in db.execute(
                        """SELECT sensor_id FROM sensor_devices
                           WHERE json_extract(metadata_json,'$.beacon_node_id')=?""",
                        (node_id,),
                    ).fetchall()
                ]
                if sensor_ids is not None:
                    selected = set(str(item) for item in sensor_ids)
                    owned = [sensor_id for sensor_id in owned if sensor_id in selected]
                if owned:
                    clauses.append("sensor_id IN (" + ",".join("?" for _ in owned) + ")")
                    params.extend(owned)
                else:
                    clauses.append("0")
            elif kind == "image":
                clauses.append("camera_id=?")
                params.append(f"beacon:{node_id}")
            elif kind == "checkin":
                clauses.append("node_id=?")
                params.append(node_id)
            else:
                clauses.extend(("node_id=?", "account_id=?"))
                params.extend((node_id, account_id))
            if mode == "ids":
                clauses.append(f"{pk} IN (" + ",".join("?" for _ in ids) + ")")
                params.extend(ids)
            elif mode == "before":
                clauses.append(f"{time_column}<?")
                params.append(before_value)
            return " AND ".join(clauses), params

        def count_where(db: sqlite3.Connection, where: str, params: list[Any]) -> int:
            return int(db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}", params
            ).fetchone()[0])

        def result_range(db: sqlite3.Connection, where: str, params: list[Any]) -> dict[str, str] | None:
            row = db.execute(
                f"SELECT MIN({time_column}) AS first,MAX({time_column}) AS last FROM {table} WHERE {where}",
                params,
            ).fetchone()
            if row["first"] is None:
                return None
            def render(value: Any) -> str:
                if kind in {"checkin", "command"}:
                    return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
                return str(value)
            return {"from": render(row["first"]), "to": render(row["last"])}

        def criteria_json() -> str:
            criteria = {
                "ids_count": len(ids) if isinstance(ids, list) else 0,
                "sensor_ids": sensor_ids,
                "before": before.astimezone(timezone.utc).isoformat() if isinstance(before, datetime) else None,
                "all": mode == "all",
            }
            return _json(criteria)

        db = self._connect()
        total_deleted = 0
        committed_deleted = 0
        batch_started = False
        file_errors = 0
        try:
            owner = db.execute(
                "SELECT label FROM beacon_node_profiles WHERE node_id=? AND account_id=?",
                (node_id, account_id),
            ).fetchone()
            if owner is None:
                raise KeyError(node_id)
            if mode == "all" and (req.get("confirm_label") or "").strip() != str(owner["label"]).strip():
                raise ValueError("장치 이름이 일치하지 않습니다.")

            if mode == "ids":
                db.execute("BEGIN IMMEDIATE")
            where, params = make_where(db)
            matched = count_where(db, where, params)

            skipped_current = 0
            current_id: int | None = None
            if kind == "checkin":
                latest = db.execute(
                    "SELECT checkin_id FROM beacon_node_checkins WHERE node_id=? ORDER BY received_at DESC,checkin_id DESC LIMIT 1",
                    (node_id,),
                ).fetchone()
                if latest is not None:
                    current_id = int(latest["checkin_id"])
                    skipped_current = count_where(db, f"({where}) AND checkin_id=?", params + [current_id])

            skipped_busy = 0
            if kind == "command":
                skipped_busy = count_where(
                    db, f"({where}) AND state NOT IN ('done','failed','expired')", params
                )

            eligible_where = where
            eligible_params = list(params)
            if current_id is not None:
                eligible_where += " AND checkin_id<>?"
                eligible_params.append(current_id)
            if kind == "command":
                eligible_where += " AND state IN ('done','failed','expired')"

            eligible = count_where(db, eligible_where, eligible_params)
            freed_bytes = 0
            if kind == "image":
                freed_bytes = int(db.execute(
                    f"SELECT COALESCE(SUM(byte_size),0) FROM {table} WHERE {eligible_where}",
                    eligible_params,
                ).fetchone()[0] or 0)
            affected_range = result_range(db, eligible_where, eligible_params)
            response: dict[str, Any] = {
                "kind": kind, "mode": mode, "dry_run": dry_run,
                "matched": matched, "deleted": 0,
                "skipped_busy": skipped_busy, "skipped_current": skipped_current,
                "freed_bytes": freed_bytes, "file_errors": 0, "range": affected_range,
            }
            if dry_run:
                return response

            def select_rows(limit: int | None = None) -> list[sqlite3.Row]:
                sql = f"SELECT {select_columns} FROM {table} WHERE {eligible_where} ORDER BY {pk}"
                if limit is not None:
                    sql += f" LIMIT {int(limit)}"
                return db.execute(sql, eligible_params).fetchall()

            def delete_rows(rows: list[sqlite3.Row]) -> list[tuple[str, str]]:
                nonlocal total_deleted
                if not rows:
                    return []
                row_ids = [row["row_id"] for row in rows]
                placeholders = ",".join("?" for _ in row_ids)
                files: list[tuple[str, str]] = []
                if kind == "image":
                    files = [(str(row["row_id"]), str(row["file_path"])) for row in rows]
                    db.execute(
                        f"UPDATE beacon_commands SET image_asset_id=NULL WHERE image_asset_id IN ({placeholders})",
                        row_ids,
                    )
                elif kind == "command":
                    db.execute(
                        f"DELETE FROM beacon_sensor_results WHERE command_id IN ({placeholders})",
                        row_ids,
                    )
                cursor = db.execute(
                    f"DELETE FROM {table} WHERE {pk} IN ({placeholders})",
                    row_ids,
                )
                total_deleted += max(0, cursor.rowcount)
                return files

            def unlink_files(files: list[tuple[str, str]]) -> None:
                nonlocal file_errors
                allowed = (self.data_root / "raw" / "beacons" / node_id).resolve()
                for asset_id, file_path in files:
                    target = (self.data_root / file_path).resolve()
                    try:
                        if allowed not in target.parents:
                            file_errors += 1
                            logger.warning("Beacon image file delete blocked asset_id=%s", asset_id)
                            continue
                        target.unlink(missing_ok=True)
                    except OSError:
                        file_errors += 1
                        logger.warning("Beacon image file delete failed asset_id=%s", asset_id)

            if mode == "ids":
                rows = select_rows()
                files = delete_rows(rows)
                db.execute(
                    """INSERT INTO beacon_data_deletions(
                           account_id,node_id,kind,mode,matched,deleted,skipped,freed_bytes,criteria_json,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (account_id, node_id, kind, mode, matched, total_deleted,
                     skipped_busy + skipped_current, freed_bytes, criteria_json(),
                     datetime.now(timezone.utc).isoformat()),
                )
                db.commit()
                unlink_files(files)
            else:
                db.execute(
                    """INSERT INTO beacon_data_deletions(
                           account_id,node_id,kind,mode,matched,deleted,skipped,freed_bytes,criteria_json,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (account_id, node_id, kind, mode, matched, 0,
                     skipped_busy + skipped_current, freed_bytes, criteria_json(),
                     datetime.now(timezone.utc).isoformat()),
                )
                audit_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
                db.commit()
                batch_started = True
                while True:
                    db.execute("BEGIN IMMEDIATE")
                    rows = select_rows(5000)
                    if not rows:
                        db.commit()
                        break
                    files = delete_rows(rows)
                    db.execute(
                        "UPDATE beacon_data_deletions SET deleted=? WHERE deletion_id=?",
                        (total_deleted, audit_id),
                    )
                    db.commit()
                    committed_deleted = total_deleted
                    unlink_files(files)

            response["deleted"] = total_deleted
            response["file_errors"] = file_errors
            return response
        except Exception as exc:
            if db.in_transaction:
                db.rollback()
            if mode in {"before", "all"} and not dry_run and batch_started:
                total_deleted = committed_deleted
                error = RuntimeError(f"삭제 도중 오류가 발생했습니다. deleted={total_deleted}")
                error.deleted = total_deleted
                raise error from exc
            raise
        finally:
            db.close()
