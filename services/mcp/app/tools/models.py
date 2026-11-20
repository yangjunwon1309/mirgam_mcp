"""On-demand RTMDet and Timestral tools backed by the serialized host runner."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from ..mcp_app import mcp
from .sqlite import _connection, _public_sensor, _resolve_sensor


KST = ZoneInfo("Asia/Seoul")
RUNNER_URL = os.getenv("MODEL_RUNNER_URL", "http://host.docker.internal:8766").rstrip("/")
INTERVALS = {15, 30, 60}
CLASS_ALIASES = {
    "귤": "orange",
    "감귤": "orange",
    "오렌지": "orange",
    "나무": "tree",
    "나무 줄기": "tree trunk",
    "나무줄기": "tree trunk",
}


def _error_response(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return {
        "ok": False,
        "error": payload.get("error", "model_runner_error"),
        "detail": str(payload.get("detail", response.reason_phrase))[:400],
    }


def _camera_match(
    camera_ref: str,
) -> tuple[dict[str, object] | None, list[dict[str, object]], str | None]:
    with _connection() as connection:
        cameras = [dict(row) for row in connection.execute(
            """
            SELECT camera_id, display_name, camera_type, status, zone_id
            FROM camera_devices ORDER BY display_name
            """
        ).fetchall()]
        if not cameras:
            return None, [], "camera_not_found"

        ref = "".join(ch for ch in camera_ref.casefold() if ch.isalnum())
        if not ref:
            if len(cameras) == 1:
                matches = cameras
            else:
                return None, cameras[:5], "camera_ref_required"
        else:
            # Ignore generic device words so "A2 camera" resolves by its A2
            # token, while a bare "camera" remains ambiguous.
            ref_tokens = set(re.findall(r"[a-z0-9]+|[가-힣]+", camera_ref.casefold()))
            ref_tokens -= {"카메라", "camera", "cam", "온실", "greenhouse"}
            if not ref_tokens:
                return None, cameras[:5], "camera_ref_required"
            matches = []
            for camera in cameras:
                candidates = (
                    str(camera["camera_id"]),
                    str(camera["display_name"]),
                    str(camera.get("zone_id") or ""),
                )
                normalized = ["".join(ch for ch in value.casefold() if ch.isalnum()) for value in candidates]
                candidate_tokens = {
                    token
                    for value in candidates
                    for token in re.findall(r"[a-z0-9]+|[가-힣]+", value.casefold())
                }
                substring_match = any(ref in value for value in normalized if value)
                token_match = bool(ref_tokens) and ref_tokens.issubset(candidate_tokens)
                if substring_match or token_match:
                    matches.append(camera)

            if not matches:
                return None, cameras[:5], "camera_not_found"
            if len(matches) > 1:
                return None, matches[:5], "ambiguous_camera"

        camera = matches[0]
        asset = connection.execute(
            """
            SELECT asset_id, captured_at, file_path, content_type, width, height
            FROM camera_assets WHERE camera_id = ? ORDER BY captured_at DESC LIMIT 1
            """,
            (camera["camera_id"],),
        ).fetchone()
        return ({**camera, "latest_image": dict(asset) if asset else None}, matches, None)


@mcp.tool()
def detect_camera_objects(
    camera_ref: str = "",
    confidence_threshold: float = 0.30,
    classes: list[str] | None = None,
    max_detections: int = 20,
) -> dict[str, object]:
    """Run the local TensorRT RTMDet model on a camera's latest saved image.

    Returns class counts and detections with class, confidence, and image-pixel bbox_xyxy.
    The currently installed weights are closed-vocabulary COCO-80: they detect labels such
    as orange, but have no tree/trunk label. Requesting an unsupported label returns an
    explicit unsupported_classes error. A later fine-tuned engine and class list can replace it.
    This is one-frame detection; it does not track or deduplicate objects across a video.

    Args:
        camera_ref: Camera ID or part of its registered display name, e.g. "A2" or "귤 생육 카메라".
        confidence_threshold: Minimum detection confidence, from 0.01 to 0.99.
        classes: Optional class names to filter, such as ["orange"].
        max_detections: Maximum number of boxes to return; class counts include all detections.
    """
    if not 0.01 <= confidence_threshold <= 0.99:
        return {"ok": False, "error": "invalid_confidence_threshold", "allowed": "0.01..0.99"}
    max_detections = max(1, min(max_detections, 30))
    camera, matches, match_error = _camera_match(camera_ref)
    if camera is None:
        return {
            "ok": False,
            "error": match_error or "camera_not_found",
            "camera_ref": camera_ref,
            "matches": [{key: item.get(key) for key in ("camera_id", "display_name", "zone_id")} for item in matches[:5]],
        }
    image = camera.get("latest_image")
    if not image:
        return {"ok": False, "error": "camera_has_no_saved_image", "camera": camera}

    requested_classes = [CLASS_ALIASES.get(value.strip().casefold(), value.strip()) for value in classes] if classes else None
    try:
        response = httpx.post(
            f"{RUNNER_URL}/v1/detect",
            json={
                "image_relative_path": image["file_path"],
                "confidence_threshold": confidence_threshold,
                "classes": requested_classes,
                "max_detections": max_detections,
            },
            timeout=75.0,
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": "model_runner_unavailable", "detail": type(exc).__name__}
    if response.is_error:
        return _error_response(response)
    result = response.json()
    result["camera"] = {
        "camera_id": camera["camera_id"],
        "display_name": camera["display_name"],
        "captured_at": image["captured_at"],
        "asset_id": image["asset_id"],
    }
    result["warning"] = (
        "현재 COCO 가중치에는 나무 클래스가 없어 나무 수로 해석할 수 없습니다. "
        "개수는 검출된 지원 클래스별 박스 수입니다."
        if result.get("label_set") == "COCO-80"
        else None
    )
    return result


@mcp.tool()
def forecast_sensor(
    sensor_ref: str,
    horizon_steps: int = 24,
    interval_minutes: int = 60,
    history_days: int = 7,
) -> dict[str, object]:
    """Forecast a sensor series with Timestral-28M on CPU.

    sensor_ref accepts a sensor ID, alias, or greenhouse/bed and metric description.
    interval_minutes is 15, 30, or 60; horizon_steps is 1..48 (default: next 24 hourly values).
    Returns median and 10th/90th-percentile forecasts plus history coverage. Gaps are marked
    missing and supplied to Timestral as NaN; sparse-history warnings are included in output.
    """
    if interval_minutes not in INTERVALS:
        return {"ok": False, "error": "invalid_interval", "allowed": sorted(INTERVALS)}
    if not 1 <= horizon_steps <= 48:
        return {"ok": False, "error": "invalid_horizon", "allowed": "1..48"}
    if not 1 <= history_days <= 30:
        return {"ok": False, "error": "invalid_history_days", "allowed": "1..30"}

    with _connection() as connection:
        sensor, matches = _resolve_sensor(connection, sensor_ref)
        if sensor is None:
            return {
                "ok": False,
                "error": "sensor_not_found" if not matches else "ambiguous_sensor",
                "sensor_ref": sensor_ref,
                "matches": [_public_sensor(item) for item in matches[:5]],
            }
        now_local = datetime.now(KST).replace(second=0, microsecond=0)
        interval_minutes_floor = (now_local.minute // interval_minutes) * interval_minutes
        end_local = now_local.replace(minute=interval_minutes_floor)
        delta = timedelta(minutes=interval_minutes)
        points_per_day = 24 * 60 // interval_minutes
        expected = history_days * points_per_day
        start_local = end_local - expected * delta
        start_utc = start_local.astimezone(timezone.utc).isoformat()
        end_utc = end_local.astimezone(timezone.utc).isoformat()
        rows = connection.execute(
            """
            SELECT value, recorded_at FROM sensor_readings
            WHERE sensor_id = ? AND recorded_at >= ? AND recorded_at < ?
            ORDER BY recorded_at
            """,
            (sensor["sensor_id"], start_utc, end_utc),
        ).fetchall()
        latest = connection.execute(
            """SELECT recorded_at FROM sensor_readings WHERE sensor_id = ?
               ORDER BY recorded_at DESC LIMIT 1""",
            (sensor["sensor_id"],),
        ).fetchone()

    buckets: list[list[float]] = [[] for _ in range(expected)]
    for row in rows:
        timestamp = datetime.fromisoformat(str(row["recorded_at"]).replace("Z", "+00:00"))
        timestamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp
        local_time = timestamp.astimezone(KST)
        bucket_minute = (local_time.minute // interval_minutes) * interval_minutes
        bucket = local_time.replace(minute=bucket_minute, second=0, microsecond=0)
        index = int((bucket - start_local).total_seconds() // delta.total_seconds())
        if 0 <= index < expected:
            buckets[index].append(float(row["value"]))
    values: list[float | None] = [sum(value) / len(value) if value else None for value in buckets]
    valid_count = sum(value is not None for value in values)
    coverage_ratio = valid_count / expected if expected else 0.0
    if valid_count < 16:
        return {
            "ok": False,
            "error": "insufficient_sensor_history",
            "sensor": _public_sensor(sensor),
            "valid_samples": valid_count,
            "expected_samples": expected,
            "coverage_ratio": round(coverage_ratio, 3),
        }

    try:
        response = httpx.post(
            f"{RUNNER_URL}/v1/forecast",
            json={"values": values, "horizon": horizon_steps},
            timeout=150.0,
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": "model_runner_unavailable", "detail": type(exc).__name__}
    if response.is_error:
        return _error_response(response)
    forecast = response.json()

    point_rows = []
    for index, (q10, median, q90) in enumerate(zip(forecast["q10"], forecast["median"], forecast["q90"])):
        timestamp = end_local + (index + 1) * delta
        point_rows.append([
            timestamp.isoformat(timespec="minutes"),
            round(float(q10), 3),
            round(float(median), 3),
            round(float(q90), 3),
        ])
    return {
        "ok": True,
        "model": "Timestral-28M",
        "device": "CPU",
        "sensor": _public_sensor(sensor),
        "timezone": "Asia/Seoul",
        "interval_minutes": interval_minutes,
        "forecast_horizon": horizon_steps,
        "history": {
            "from": start_local.isoformat(timespec="minutes"),
            "through": end_local.isoformat(timespec="minutes"),
            "valid_samples": valid_count,
            "expected_samples": expected,
            "coverage_percent": round(coverage_ratio * 100, 1),
            "latest_observed_at": latest["recorded_at"] if latest else None,
        },
        "warning": "과거 데이터에 빈 시간 구간이 있습니다." if coverage_ratio < 0.8 else None,
        "point_fields": ["time", "q10", "median", "q90"],
        "points": point_rows,
        "model_load_and_forecast_ms": forecast.get("model_load_and_forecast_ms"),
    }
