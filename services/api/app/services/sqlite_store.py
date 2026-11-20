"""SQLite persistence for local smart-farm conversations and future farm data."""

from __future__ import annotations

import json
import hashlib
import math
import random
import secrets
import sqlite3
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..schemas import Message, Thread, ThreadDocument


KST = ZoneInfo("Asia/Seoul")
DEMO_SOURCE = "demo-seed"
DEMO_SENSOR_PROFILES: dict[str, tuple[float, float, float, float, float]] = {
    # target, daily swing, short-interval noise, lower/upper safe clamp
    "demo-env-a-temperature": (24.2, 1.8, 0.18, 17.0, 33.0),
    "demo-env-a-humidity": (67.0, 7.5, 0.75, 35.0, 95.0),
    "demo-soil-b2-moisture": (42.0, 5.2, 0.28, 20.0, 70.0),
}
DEMO_SENSOR_ALIASES = {
    "temp_A_01": "demo-env-a-temperature",
    "humidity_A_01": "demo-env-a-humidity",
}


class SQLiteStore:
    """Small, local-first data store.

    Images stay as files under ``storage/raw/images``; this database stores their
    metadata and every derived vision result. SQLite WAL mode keeps the dashboard
    responsive while a sensor ingester writes small batches.
    """

    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    account_id INTEGER NOT NULL,
                    farm_name TEXT NOT NULL,
                    username TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS auth_sessions_expiry_idx
                    ON auth_sessions(expires_at);

                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    trace_json TEXT
                );
                CREATE INDEX IF NOT EXISTS messages_thread_time_idx
                    ON messages(thread_id, message_id);
                CREATE INDEX IF NOT EXISTS threads_updated_idx
                    ON threads(updated_at DESC);

                CREATE TABLE IF NOT EXISTS sensor_readings (
                    reading_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sensor_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    source TEXT,
                    quality TEXT,
                    payload_json TEXT
                );
                CREATE INDEX IF NOT EXISTS sensor_readings_lookup_idx
                    ON sensor_readings(sensor_id, metric, recorded_at DESC);

                CREATE TABLE IF NOT EXISTS farm_zones (
                    zone_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    greenhouse_id TEXT NOT NULL,
                    bed_id TEXT,
                    zone_type TEXT NOT NULL,
                    metadata_json TEXT
                );

                CREATE TABLE IF NOT EXISTS sensor_devices (
                    sensor_id TEXT PRIMARY KEY,
                    zone_id TEXT REFERENCES farm_zones(zone_id) ON DELETE SET NULL,
                    sensor_type TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    installed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT
                );
                CREATE INDEX IF NOT EXISTS sensor_devices_zone_idx ON sensor_devices(zone_id);

                CREATE TABLE IF NOT EXISTS sensor_aliases (
                    alias TEXT PRIMARY KEY,
                    sensor_id TEXT NOT NULL REFERENCES sensor_devices(sensor_id) ON DELETE CASCADE,
                    source TEXT NOT NULL DEFAULT 'configured'
                );
                CREATE INDEX IF NOT EXISTS sensor_aliases_sensor_idx ON sensor_aliases(sensor_id);

                CREATE TABLE IF NOT EXISTS sensor_daily_rollups (
                    sensor_id TEXT NOT NULL REFERENCES sensor_devices(sensor_id) ON DELETE CASCADE,
                    metric TEXT NOT NULL,
                    local_date TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    min_value REAL NOT NULL,
                    max_value REAL NOT NULL,
                    avg_value REAL NOT NULL,
                    stddev_value REAL,
                    p05_value REAL,
                    p50_value REAL,
                    p95_value REAL,
                    source TEXT NOT NULL,
                    calculated_at TEXT NOT NULL,
                    PRIMARY KEY(sensor_id, metric, local_date, source)
                );
                CREATE INDEX IF NOT EXISTS sensor_daily_rollups_lookup_idx
                    ON sensor_daily_rollups(sensor_id, metric, local_date DESC);

                CREATE TABLE IF NOT EXISTS camera_devices (
                    camera_id TEXT PRIMARY KEY,
                    zone_id TEXT REFERENCES farm_zones(zone_id) ON DELETE SET NULL,
                    display_name TEXT NOT NULL,
                    camera_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT
                );
                CREATE INDEX IF NOT EXISTS camera_devices_zone_idx ON camera_devices(zone_id);

                CREATE TABLE IF NOT EXISTS camera_assets (
                    asset_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    sha256 TEXT,
                    content_type TEXT,
                    byte_size INTEGER,
                    width INTEGER,
                    height INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS camera_assets_camera_time_idx
                    ON camera_assets(camera_id, captured_at DESC);

                CREATE TABLE IF NOT EXISTS vision_runs (
                    run_id TEXT PRIMARY KEY,
                    asset_id TEXT REFERENCES camera_assets(asset_id) ON DELETE SET NULL,
                    model_name TEXT NOT NULL,
                    model_version TEXT,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    result_json TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS vision_runs_asset_time_idx
                    ON vision_runs(asset_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS vision_observations (
                    observation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES vision_runs(run_id) ON DELETE CASCADE,
                    asset_id TEXT REFERENCES camera_assets(asset_id) ON DELETE SET NULL,
                    label TEXT NOT NULL,
                    instance_count INTEGER NOT NULL DEFAULT 0,
                    coverage_ratio REAL,
                    mean_confidence REAL,
                    metrics_json TEXT
                );
                CREATE INDEX IF NOT EXISTS vision_observations_asset_idx
                    ON vision_observations(asset_id, label);

                CREATE TABLE IF NOT EXISTS vision_daily_rollups (
                    camera_id TEXT NOT NULL REFERENCES camera_devices(camera_id) ON DELETE CASCADE,
                    local_date TEXT NOT NULL,
                    label TEXT NOT NULL,
                    image_count INTEGER NOT NULL,
                    total_instances INTEGER NOT NULL,
                    avg_coverage_ratio REAL,
                    avg_confidence REAL,
                    alert_count INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL,
                    calculated_at TEXT NOT NULL,
                    PRIMARY KEY(camera_id, local_date, label, source)
                );
                CREATE INDEX IF NOT EXISTS vision_daily_rollups_lookup_idx
                    ON vision_daily_rollups(camera_id, local_date DESC);

                CREATE TABLE IF NOT EXISTS kma_weather_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    fetched_at_epoch REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS kma_weather_cache_fetched_idx
                    ON kma_weather_cache(fetched_at_epoch DESC);

                CREATE TABLE IF NOT EXISTS mcp_tool_calls (
                    call_id TEXT PRIMARY KEY,
                    thread_id TEXT REFERENCES threads(thread_id) ON DELETE SET NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    result_json TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS mcp_tool_calls_thread_time_idx
                    ON mcp_tool_calls(thread_id, created_at DESC);
                """
            )
            message_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "trace_json" not in message_columns:
                connection.execute("ALTER TABLE messages ADD COLUMN trace_json TEXT")
            self._restore_missing_tool_traces(connection)
            # These are the two human-facing IDs already used in the dashboard
            # conversation. Keep them as aliases; the database's canonical IDs
            # remain stable and are still returned with every tool result.
            for alias, sensor_id in DEMO_SENSOR_ALIASES.items():
                connection.execute(
                    """
                    INSERT INTO sensor_aliases(alias, sensor_id, source)
                    SELECT ?, sensor_id, 'demo-alias' FROM sensor_devices WHERE sensor_id = ?
                    ON CONFLICT(alias) DO UPDATE SET
                        sensor_id = excluded.sensor_id,
                        source = excluded.source
                    """,
                    (alias, sensor_id),
                )

    def create_auth_session(
        self,
        account_id: int,
        farm_name: str,
        username: str | None,
        ttl_seconds: int,
    ) -> str:
        """Store only a hash of a random local session token and return the token."""
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        created_at = self._now()
        expires_at = created_at + timedelta(seconds=max(60, ttl_seconds))
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL",
                (created_at.isoformat(),),
            )
            connection.execute(
                """
                INSERT INTO auth_sessions(
                    session_id, token_hash, account_id, farm_name, username, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), token_hash, account_id, farm_name, username,
                    created_at.isoformat(), expires_at.isoformat(),
                ),
            )
        return token

    def get_auth_session(self, token: str | None) -> dict[str, object] | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = self._now().isoformat()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT account_id, farm_name, username
                FROM auth_sessions
                WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
        if row is None:
            return None
        return {
            "account_id": int(row["account_id"]),
            "farm_name": str(row["farm_name"]),
            "username": str(row["username"]) if row["username"] is not None else None,
        }

    def revoke_auth_session(self, token: str | None) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connection() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (self._now().isoformat(), token_hash),
            )

    @staticmethod
    def _restore_missing_tool_traces(connection: sqlite3.Connection) -> None:
        """Backfill old assistant messages from the MCP call audit trail."""
        messages = connection.execute(
            """
            SELECT message_id, thread_id, created_at, trace_json
            FROM messages WHERE role = 'assistant'
            ORDER BY thread_id, message_id
            """
        ).fetchall()
        calls_by_thread: dict[str, list[sqlite3.Row]] = {}
        for call in connection.execute(
            """
            SELECT thread_id, tool_name, arguments_json, result_json, status, error, created_at
            FROM mcp_tool_calls WHERE thread_id IS NOT NULL
            ORDER BY thread_id, created_at, call_id
            """
        ).fetchall():
            calls_by_thread.setdefault(call["thread_id"], []).append(call)
        previous_assistant_at: dict[str, str] = {}
        call_offsets: dict[str, int] = {}
        for message in messages:
            thread_id = message["thread_id"]
            previous_time = previous_assistant_at.get(thread_id)
            previous_assistant_at[thread_id] = message["created_at"]
            thread_calls = calls_by_thread.get(thread_id, [])
            call_index = call_offsets.get(thread_id, 0)
            calls: list[sqlite3.Row] = []
            while call_index < len(thread_calls) and thread_calls[call_index]["created_at"] <= message["created_at"]:
                call = thread_calls[call_index]
                if previous_time is None or call["created_at"] > previous_time:
                    calls.append(call)
                call_index += 1
            call_offsets[thread_id] = call_index
            if message["trace_json"] or not calls:
                continue

            trace: list[dict[str, object]] = [
                {
                    "type": "status",
                    "phase": "restored",
                    "message": "이전 MCP 조회 이력을 복원했습니다.",
                }
            ]
            for call in calls:
                try:
                    arguments: object = json.loads(call["arguments_json"])
                except (TypeError, json.JSONDecodeError):
                    arguments = {}
                serialized_result = call["error"] if call["status"] == "error" else call["result_json"]
                try:
                    result: object = json.loads(serialized_result) if serialized_result else None
                except (TypeError, json.JSONDecodeError):
                    result = {"detail": serialized_result}
                trace.append(
                    {
                        "type": "tool_call",
                        "tool": call["tool_name"],
                        "arguments": arguments,
                    }
                )
                trace.append(
                    {
                        "type": "tool_result",
                        "tool": call["tool_name"],
                        "result": result,
                    }
                )
            trace.append({"type": "status", "phase": "complete", "message": "이전 답변 기록입니다."})
            connection.execute(
                "UPDATE messages SET trace_json = ? WHERE message_id = ?",
                (json.dumps(trace, ensure_ascii=False, separators=(",", ":")), message["message_id"]),
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def create(self, first_message: str) -> ThreadDocument:
        now = self._now()
        document = ThreadDocument(
            thread_id=str(uuid4()),
            title=first_message.strip().replace("\n", " ")[:60] or "새 대화",
            created_at=now,
            updated_at=now,
        )
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO threads(thread_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (document.thread_id, document.title, document.created_at.isoformat(), document.updated_at.isoformat()),
            )
        return document

    def load(self, thread_id: str) -> ThreadDocument:
        with self._connection() as connection:
            thread = connection.execute(
                "SELECT thread_id, title, created_at, updated_at FROM threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            if thread is None:
                raise KeyError(thread_id)
            messages = connection.execute(
                "SELECT role, content, created_at, trace_json FROM messages WHERE thread_id = ? ORDER BY message_id", (thread_id,)
            ).fetchall()
        return ThreadDocument(
            thread_id=thread["thread_id"],
            title=thread["title"],
            created_at=thread["created_at"],
            updated_at=thread["updated_at"],
            messages=[
                Message(
                    role=row["role"],
                    content=row["content"],
                    created_at=row["created_at"],
                    trace=json.loads(row["trace_json"]) if row["trace_json"] else None,
                )
                for row in messages
            ],
        )

    def append_message(self, thread_id: str, message: Message) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO messages(thread_id, role, content, created_at, trace_json) VALUES (?, ?, ?, ?, ?)",
                (
                    thread_id,
                    message.role,
                    message.content,
                    message.created_at.isoformat(),
                    json.dumps(message.trace, ensure_ascii=False, separators=(",", ":")) if message.trace else None,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(thread_id)
            connection.execute(
                "UPDATE threads SET updated_at = ? WHERE thread_id = ?", (self._now().isoformat(), thread_id)
            )

    def list(self) -> list[Thread]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT thread_id, title, updated_at FROM threads ORDER BY updated_at DESC"
            ).fetchall()
        return [Thread(thread_id=row["thread_id"], title=row["title"], updated_at=row["updated_at"]) for row in rows]

    def delete(self, thread_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))

    @staticmethod
    def _as_dict(row: sqlite3.Row | None) -> dict[str, object] | None:
        return dict(row) if row is not None else None

    def dashboard_sensors(self) -> list[dict[str, object]]:
        """Return devices with their latest raw reading for the browser dashboard."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT d.sensor_id, d.display_name, d.sensor_type, d.unit, d.status, d.zone_id,
                       (
                           SELECT r.value FROM sensor_readings AS r
                           WHERE r.sensor_id = d.sensor_id
                           ORDER BY r.recorded_at DESC LIMIT 1
                       ) AS latest_value,
                       (
                           SELECT r.recorded_at FROM sensor_readings AS r
                           WHERE r.sensor_id = d.sensor_id
                           ORDER BY r.recorded_at DESC LIMIT 1
                       ) AS latest_recorded_at
                FROM sensor_devices AS d
                ORDER BY d.display_name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def append_demo_live_readings(self) -> int:
        """Append one small, realistic demo movement per device.

        This is intentionally limited to IDs created by the demo seed. Real
        ingestion can coexist safely, and the feature is disabled via
        ``DEMO_SIMULATOR_ENABLED=false`` once physical devices are connected.
        """
        now_utc = self._now()
        now_kst = now_utc.astimezone(KST)
        rng = random.Random()
        inserted = 0
        with self._connection() as connection:
            for sensor_id, (target, daily_swing, noise, lower, upper) in DEMO_SENSOR_PROFILES.items():
                device = connection.execute(
                    "SELECT sensor_type, unit FROM sensor_devices WHERE sensor_id = ?", (sensor_id,)
                ).fetchone()
                if device is None:
                    continue
                latest = connection.execute(
                    "SELECT value FROM sensor_readings WHERE sensor_id = ? ORDER BY recorded_at DESC LIMIT 1", (sensor_id,)
                ).fetchone()
                daily_phase = math.sin((now_kst.hour + now_kst.minute / 60 - 7) / 24 * 2 * math.pi)
                natural_value = target + daily_swing * daily_phase
                previous = float(latest["value"]) if latest is not None else natural_value
                # A damped random walk feels continuous, unlike independent values.
                value = previous + 0.18 * (natural_value - previous) + rng.gauss(0, noise)
                value = round(min(upper, max(lower, value)), 2)
                connection.execute(
                    """
                    INSERT INTO sensor_readings(sensor_id, metric, value, unit, recorded_at, source, quality, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, 'simulated', ?)
                    """,
                    (
                        sensor_id,
                        device["sensor_type"],
                        value,
                        device["unit"],
                        now_utc.isoformat(),
                        DEMO_SOURCE,
                        json.dumps({"local_time": now_kst.isoformat(), "mode": "demo-live"}, ensure_ascii=False),
                    ),
                )
                self._refresh_demo_rollup(connection, sensor_id, device["sensor_type"], device["unit"], now_kst.date())
                inserted += 1
        return inserted

    @staticmethod
    def _refresh_demo_rollup(
        connection: sqlite3.Connection, sensor_id: str, metric: str, unit: str, local_date: date
    ) -> None:
        """Recompute the one current KST-day aggregate after an appended sample."""
        day_start = datetime.combine(local_date, datetime.min.time(), tzinfo=KST).astimezone(timezone.utc)
        day_end = day_start + timedelta(days=1)
        values = [
            float(row["value"])
            for row in connection.execute(
                """
                SELECT value FROM sensor_readings
                WHERE sensor_id = ? AND recorded_at >= ? AND recorded_at < ?
                """,
                (sensor_id, day_start.isoformat(), day_end.isoformat()),
            ).fetchall()
        ]
        if not values:
            return
        ordered = sorted(values)
        def percentile(fraction: float) -> float:
            position = (len(ordered) - 1) * fraction
            low, high = math.floor(position), math.ceil(position)
            return ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (position - low)
        connection.execute(
            """
            INSERT INTO sensor_daily_rollups(
                sensor_id, metric, local_date, unit, sample_count, min_value, max_value,
                avg_value, stddev_value, p05_value, p50_value, p95_value, source, calculated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sensor_id, metric, local_date, source) DO UPDATE SET
                sample_count=excluded.sample_count, min_value=excluded.min_value, max_value=excluded.max_value,
                avg_value=excluded.avg_value, stddev_value=excluded.stddev_value, p05_value=excluded.p05_value,
                p50_value=excluded.p50_value, p95_value=excluded.p95_value, calculated_at=excluded.calculated_at
            """,
            (
                sensor_id, metric, str(local_date), unit, len(values), min(values), max(values),
                statistics.fmean(values), statistics.pstdev(values), percentile(0.05), percentile(0.50), percentile(0.95),
                DEMO_SOURCE, datetime.now(timezone.utc).isoformat(),
            ),
        )

    def dashboard_sensor_detail(self, sensor_id: str, hours: int = 24) -> dict[str, object]:
        hours = max(1, min(hours, 24 * 31))
        cutoff = (datetime.now(timezone.utc).timestamp() - hours * 3600)
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
        with self._connection() as connection:
            device = connection.execute(
                """
                SELECT sensor_id, display_name, sensor_type, unit, status, zone_id
                FROM sensor_devices WHERE sensor_id = ?
                """,
                (sensor_id,),
            ).fetchone()
            if device is None:
                raise KeyError(sensor_id)
            latest_reading = connection.execute(
                """
                SELECT sensor_id, metric, value, unit, recorded_at, quality
                FROM sensor_readings WHERE sensor_id = ?
                ORDER BY recorded_at DESC, reading_id DESC LIMIT 1
                """,
                (sensor_id,),
            ).fetchone()
            readings = connection.execute(
                """
                SELECT sensor_id, metric, value, unit, recorded_at, quality
                FROM (
                    SELECT sensor_id, metric, value, unit, recorded_at, quality
                    FROM sensor_readings
                    WHERE sensor_id = ? AND recorded_at >= ?
                    ORDER BY recorded_at DESC LIMIT 96
                ) ORDER BY recorded_at
                """,
                (sensor_id, cutoff_iso),
            ).fetchall()
            daily_rollups = connection.execute(
                """
                SELECT metric, local_date, unit, sample_count, min_value, max_value,
                       avg_value, stddev_value, p05_value, p50_value, p95_value
                FROM sensor_daily_rollups
                WHERE sensor_id = ? ORDER BY local_date DESC LIMIT 7
                """,
                (sensor_id,),
            ).fetchall()
        return {
            "device": dict(device),
            "latest_reading": dict(latest_reading) if latest_reading is not None else None,
            "readings": [dict(row) for row in readings],
            "daily_rollups": [dict(row) for row in daily_rollups],
        }

    def dashboard_cameras(self) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.camera_id, c.display_name, c.camera_type, c.status, c.zone_id,
                       a.asset_id AS latest_asset_id, a.captured_at AS latest_captured_at,
                       v.avg_coverage_ratio, v.avg_confidence, v.alert_count
                FROM camera_devices AS c
                LEFT JOIN camera_assets AS a ON a.asset_id = (
                    SELECT asset_id FROM camera_assets
                    WHERE camera_id = c.camera_id ORDER BY captured_at DESC LIMIT 1
                )
                LEFT JOIN vision_daily_rollups AS v ON v.rowid = (
                    SELECT rowid FROM vision_daily_rollups
                    WHERE camera_id = c.camera_id ORDER BY local_date DESC LIMIT 1
                )
                ORDER BY c.display_name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def dashboard_camera_detail(self, camera_id: str) -> dict[str, object]:
        with self._connection() as connection:
            camera = connection.execute(
                """
                SELECT camera_id, display_name, camera_type, status, zone_id
                FROM camera_devices WHERE camera_id = ?
                """,
                (camera_id,),
            ).fetchone()
            if camera is None:
                raise KeyError(camera_id)
            asset = connection.execute(
                """
                SELECT asset_id, captured_at, file_path, content_type, byte_size, width, height
                FROM camera_assets WHERE camera_id = ? ORDER BY captured_at DESC LIMIT 1
                """,
                (camera_id,),
            ).fetchone()
            daily_rollups = connection.execute(
                """
                SELECT local_date, label, image_count, total_instances, avg_coverage_ratio,
                       avg_confidence, alert_count
                FROM vision_daily_rollups
                WHERE camera_id = ? ORDER BY local_date DESC LIMIT 7
                """,
                (camera_id,),
            ).fetchall()
        return {
            "camera": dict(camera),
            "latest_asset": self._as_dict(asset),
            "daily_rollups": [dict(row) for row in daily_rollups],
        }

    def asset_file(self, asset_id: str) -> tuple[Path, str]:
        """Resolve a camera asset below the configured storage root only."""
        with self._connection() as connection:
            asset = connection.execute(
                "SELECT file_path, content_type FROM camera_assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if asset is None:
            raise KeyError(asset_id)
        storage_root = self.database_path.parent.parent.resolve()
        file_path = (storage_root / asset["file_path"]).resolve()
        if storage_root not in file_path.parents or not file_path.is_file():
            raise FileNotFoundError(asset_id)
        return file_path, asset["content_type"] or "application/octet-stream"

    def record_tool_call(
        self,
        *,
        thread_id: str,
        tool_name: str,
        arguments: dict[str, object],
        result: str | None,
        error: str | None,
    ) -> None:
        now = self._now().isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO mcp_tool_calls(
                    call_id, thread_id, tool_name, arguments_json, result_json,
                    status, error, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    thread_id,
                    tool_name,
                    json.dumps(arguments, ensure_ascii=False),
                    result,
                    "error" if error else "completed",
                    error,
                    now,
                    now,
                ),
            )
