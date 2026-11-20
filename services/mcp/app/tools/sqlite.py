"""Small read-only smart-farm tools with bounded, structured JSON results."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..mcp_app import mcp


DATABASE = Path(os.getenv("SQLITE_PATH", "/workspace/state/mirgam.db"))
KST = ZoneInfo("Asia/Seoul")
INTERVALS = {15, 30, 60}


def _connection() -> sqlite3.Connection:
    if not DATABASE.is_file():
        raise FileNotFoundError("SQLite database is not available yet")
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def _sensor_candidates(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT d.sensor_id, d.display_name, d.sensor_type, d.unit, d.status, d.zone_id,
               z.name AS zone_name, z.greenhouse_id, z.bed_id
        FROM sensor_devices AS d
        LEFT JOIN farm_zones AS z ON z.zone_id = d.zone_id
        ORDER BY d.display_name
        """
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["aliases"] = [
            alias["alias"]
            for alias in connection.execute(
                "SELECT alias FROM sensor_aliases WHERE sensor_id = ? ORDER BY alias",
                (item["sensor_id"],),
            ).fetchall()
        ]
        result.append(item)
    return result


def _sensor_score(sensor: dict[str, object], reference: str) -> int:
    query = _normalize(reference)
    if not query:
        return 0
    identifiers = [str(sensor["sensor_id"]), *[str(a) for a in sensor["aliases"]]]
    if any(_normalize(value) in query for value in identifiers if _normalize(value)):
        return 100
    display_name = _normalize(str(sensor["display_name"]))
    if display_name and display_name in query:
        return 90

    score = 0
    sensor_type = str(sensor["sensor_type"])
    metric_terms = {
        "temperature": ("temperature", "temp", "온도"),
        "humidity": ("humidity", "습도", "rh"),
        "soil_moisture": ("soilmoisture", "soil", "토양", "수분"),
    }
    if any(_normalize(term) in query for term in metric_terms.get(sensor_type, ())):
        score += 30

    for key in ("zone_id", "zone_name", "greenhouse_id", "bed_id"):
        value = str(sensor.get(key) or "")
        normalized = _normalize(value)
        if normalized and normalized in query:
            score += 30

    greenhouse = re.search(r"(?:온실|greenhouse)\s*[-_ ]*([a-z0-9]+)", reference, re.IGNORECASE)
    if greenhouse:
        expected = greenhouse.group(1).casefold()
        greenhouse_id = str(sensor.get("greenhouse_id") or "").casefold()
        zone_id = str(sensor.get("zone_id") or "").casefold()
        if greenhouse_id.endswith(expected) or re.search(rf"(?:^|[-_]){re.escape(expected)}\d*", zone_id):
            score += 30

    bed = re.search(r"(?:베드|bed)\s*[-_ ]*([a-z0-9]+)", reference, re.IGNORECASE)
    if bed and str(sensor.get("bed_id") or "").casefold() == bed.group(1).casefold():
        score += 30
    return score


def _resolve_sensor(connection: sqlite3.Connection, reference: str) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    sensors = _sensor_candidates(connection)
    scored = [(score, sensor) for sensor in sensors if (score := _sensor_score(sensor, reference)) > 0]
    if not scored:
        return None, []
    highest = max(score for score, _ in scored)
    matches = [sensor for score, sensor in scored if score == highest]
    return (matches[0] if len(matches) == 1 else None), matches


def _public_sensor(sensor: dict[str, object]) -> dict[str, object]:
    return {
        "sensor_id": sensor["sensor_id"],
        "aliases": sensor["aliases"],
        "display_name": sensor["display_name"],
        "sensor_type": sensor["sensor_type"],
        "unit": sensor["unit"],
        "status": sensor["status"],
        "zone_id": sensor["zone_id"],
        "zone_name": sensor["zone_name"],
        "greenhouse_id": sensor["greenhouse_id"],
        "bed_id": sensor["bed_id"],
    }


def _parse_local_date(value: str) -> date:
    today = datetime.now(KST).date()
    text = value.strip().casefold()
    if not text or text in {"today", "오늘", "현재"}:
        return today
    if text in {"yesterday", "어제"}:
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    korean = re.fullmatch(r"\s*(?:(\d{4})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*", text)
    month_day = re.fullmatch(r"\s*(\d{1,2})[-/]([0-3]?\d)\s*", text)
    if korean:
        return date(int(korean.group(1) or today.year), int(korean.group(2)), int(korean.group(3)))
    if month_day:
        return date(today.year, int(month_day.group(1)), int(month_day.group(2)))
    raise ValueError("local_date must be YYYY-MM-DD, MM월 DD일, today, or yesterday")


@mcp.tool()
def list_sensors() -> dict[str, object]:
    """List registered sensors. Returns JSON {count, sensors:[sensor_id, aliases, display_name, sensor_type, unit, zone]}.

    Call this only when the user asks which sensors are registered or a reference is ambiguous.
    """
    with _connection() as connection:
        sensors = [_public_sensor(sensor) for sensor in _sensor_candidates(connection)]
    return {"ok": True, "count": len(sensors), "sensors": sensors}


@mcp.tool()
def get_sensor_snapshot(sensor_ref: str) -> dict[str, object]:
    """Get one sensor's newest saved measurement by canonical ID, alias, or descriptive reference.

    Returns compact JSON {ok, sensor:{sensor_id,display_name,sensor_type,unit,zone_id,aliases}, reading:{value,unit,recorded_at,quality}|null}.
    The tool resolves aliases and location/metric text; never invent a sensor ID.
    """
    with _connection() as connection:
        sensor, matches = _resolve_sensor(connection, sensor_ref)
        if sensor is None:
            return {
                "ok": False,
                "error": "sensor_not_found" if not matches else "ambiguous_sensor",
                "sensor_ref": sensor_ref,
                "matches": [_public_sensor(item) for item in matches[:5]],
            }
        reading = connection.execute(
            """
            SELECT value, unit, recorded_at, quality
            FROM sensor_readings WHERE sensor_id = ?
            ORDER BY recorded_at DESC, reading_id DESC LIMIT 1
            """,
            (sensor["sensor_id"],),
        ).fetchone()
    return {
        "ok": True,
        "sensor": _public_sensor(sensor),
        "reading": dict(reading) if reading is not None else None,
    }


@mcp.tool()
def get_sensor_trend(
    sensor_ref: str,
    local_date: str = "",
    interval_minutes: int = 60,
) -> dict[str, object]:
    """Return SQL-bucketed sensor trend for one Asia/Seoul calendar date (at most 96 compact points).

    local_date may be YYYY-MM-DD, MM월 DD일, today, yesterday, or empty (today in Asia/Seoul).
    interval_minutes must be 15, 30, or 60. JSON includes sensor, date, timezone, coverage,
    sample_count, summary {min_value,max_value,avg_value}, point_fields, and points as
    [time,sample_count,min_value,max_value,avg_value] tuples to keep 2K-context payloads small.
    Partial current days stop at now; future measurements are never returned.
    """
    interval = interval_minutes if interval_minutes in INTERVALS else 60
    try:
        requested_day = _parse_local_date(local_date)
    except ValueError as exc:
        return {"ok": False, "error": "invalid_local_date", "detail": str(exc)}

    start_local = datetime.combine(requested_day, time.min, tzinfo=KST)
    end_local = start_local + timedelta(days=1)
    now_local = datetime.now(KST)
    if requested_day > now_local.date():
        effective_end_local = start_local
    elif requested_day == now_local.date():
        effective_end_local = min(end_local, now_local)
    else:
        effective_end_local = end_local
    start_utc = start_local.astimezone(timezone.utc).isoformat()
    end_utc = effective_end_local.astimezone(timezone.utc).isoformat()

    with _connection() as connection:
        sensor, matches = _resolve_sensor(connection, sensor_ref)
        if sensor is None:
            return {
                "ok": False,
                "error": "sensor_not_found" if not matches else "ambiguous_sensor",
                "sensor_ref": sensor_ref,
                "matches": [_public_sensor(item) for item in matches[:5]],
            }
        local_timestamp = "datetime(recorded_at, '+9 hours')"
        bucket = (
            f"strftime('%H:', {local_timestamp}) || "
            f"printf('%02d', (CAST(strftime('%M', {local_timestamp}) AS INTEGER) "
            f"/ {interval}) * {interval})"
        )
        rows = connection.execute(
            f"""
            SELECT {bucket} AS time, COUNT(*) AS sample_count,
                   MIN(value) AS min_value, MAX(value) AS max_value, AVG(value) AS avg_value
            FROM sensor_readings
            WHERE sensor_id = ? AND recorded_at >= ? AND recorded_at < ?
            GROUP BY time ORDER BY time LIMIT 96
            """,
            (sensor["sensor_id"], start_utc, end_utc),
        ).fetchall()
        points = [
            [row["time"], row["sample_count"], row["min_value"], row["max_value"], row["avg_value"]]
            for row in rows
        ]
        summary = connection.execute(
            """
            SELECT COUNT(*) AS sample_count, MIN(value) AS min_value,
                   MAX(value) AS max_value, AVG(value) AS avg_value
            FROM sensor_readings
            WHERE sensor_id = ? AND recorded_at >= ? AND recorded_at < ?
            """,
            (sensor["sensor_id"], start_utc, end_utc),
        ).fetchone()

    complete = requested_day < now_local.date()
    coverage_end = "24:00" if complete else effective_end_local.strftime("%H:%M")
    return {
        "ok": True,
        "sensor": _public_sensor(sensor),
        "local_date": requested_day.isoformat(),
        "timezone": "Asia/Seoul",
        "interval_minutes": interval,
        "coverage": {"from": "00:00", "through": coverage_end, "complete": complete},
        "sample_count": summary["sample_count"],
        "summary": {
            "min_value": summary["min_value"],
            "max_value": summary["max_value"],
            "avg_value": summary["avg_value"],
        },
        "point_fields": ["time", "sample_count", "min_value", "max_value", "avg_value"],
        "points": points,
    }


@mcp.tool()
def get_camera_summary(camera_ref: str = "", local_date: str = "") -> dict[str, object]:
    """Get one camera's newest image metadata and one KST-day vision summary as compact JSON.

    Returns {ok,camera,latest_image,vision_day}; image bytes remain in local SSD files.
    Omit local_date to use today in Asia/Seoul.
    """
    try:
        requested_day = _parse_local_date(local_date)
    except ValueError as exc:
        return {"ok": False, "error": "invalid_local_date", "detail": str(exc)}
    normalized_ref = _normalize(camera_ref)
    with _connection() as connection:
        cameras = [dict(row) for row in connection.execute(
            """
            SELECT c.camera_id, c.display_name, c.camera_type, c.status, c.zone_id,
                   z.name AS zone_name, z.greenhouse_id, z.bed_id
            FROM camera_devices AS c LEFT JOIN farm_zones AS z ON z.zone_id = c.zone_id
            ORDER BY c.display_name
            """
        ).fetchall()]
        if normalized_ref:
            exact = [
                camera for camera in cameras
                if normalized_ref in {
                    _normalize(str(camera["camera_id"])),
                    _normalize(str(camera["display_name"])),
                    _normalize(str(camera.get("zone_id") or "")),
                }
                or _normalize(str(camera["display_name"])) in normalized_ref
            ]
            if len(exact) == 0:
                return {"ok": False, "error": "camera_not_found", "camera_ref": camera_ref}
            if len(exact) > 1:
                return {"ok": False, "error": "ambiguous_camera", "matches": exact[:5]}
            camera = exact[0]
        elif len(cameras) == 1:
            camera = cameras[0]
        else:
            return {"ok": False, "error": "camera_ref_required", "matches": cameras[:5]}

        latest_image = connection.execute(
            """
            SELECT asset_id, captured_at, content_type, width, height
            FROM camera_assets WHERE camera_id = ? ORDER BY captured_at DESC LIMIT 1
            """,
            (camera["camera_id"],),
        ).fetchone()
        vision_day = connection.execute(
            """
            SELECT local_date, label, image_count, total_instances,
                   avg_coverage_ratio, avg_confidence, alert_count
            FROM vision_daily_rollups WHERE camera_id = ? AND local_date = ?
            ORDER BY label
            """,
            (camera["camera_id"], requested_day.isoformat()),
        ).fetchall()

    return {
        "ok": True,
        "camera": camera,
        "local_date": requested_day.isoformat(),
        "latest_image": dict(latest_image) if latest_image is not None else None,
        "vision_day": [dict(row) for row in vision_day],
    }
