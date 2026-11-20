"""Seed clearly-labelled, locally stored smart-farm demonstration data."""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import get_settings
from .services.sqlite_store import DEMO_SENSOR_ALIASES, SQLiteStore


SOURCE = "demo-seed"
KST = ZoneInfo("Asia/Seoul")
SENSORS = (
    ("demo-env-a-temperature", "zone-a1", "temperature", "온실 A 온도", "°C", 24.2, 1.8, 0.20),
    ("demo-env-a-humidity", "zone-a1", "humidity", "온실 A 습도", "%RH", 67.0, 7.5, 0.80),
    ("demo-soil-b2-moisture", "zone-b2", "soil_moisture", "베드 B2 토양 수분", "%VWC", 42.0, 5.2, 0.30),
)
# The PNG files are transformed frames generated from the user's three local
# farm views. They are copied to SSD storage when this seed command is run.
CAMERAS = (
    ("demo-cam-a1-overview", "zone-a1", "온실 A1 전경 카메라", "farmview_1_video.png"),
    ("demo-cam-a2-fruit", "zone-a2", "귤 생육 카메라 A2", "farmview_2_video.png"),
    ("demo-cam-b2-row", "zone-b2", "재배열 카메라 B2", "farmview_3_video.png"),
)
ASSET_ROOT = Path(__file__).with_name("demo_assets")


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def png_size(image: bytes) -> tuple[int, int]:
    """Read dimensions without pulling a heavyweight image package onto Jetson."""
    if image[:8] != b"\x89PNG\r\n\x1a\n" or image[12:16] != b"IHDR":
        raise ValueError("Demo asset is not a valid PNG")
    return struct.unpack(">II", image[16:24])


def seed() -> None:
    settings = get_settings()
    store = SQLiteStore(settings.sqlite_path)
    store.initialize()
    now_kst = datetime.now(KST).replace(second=0, microsecond=0)
    start_kst = now_kst.replace(minute=0) - timedelta(days=6, hours=23)
    image_root = store.database_path.parent.parent / "raw" / "images" / "demo"
    image_root.mkdir(parents=True, exist_ok=True)
    randomizer = random.Random(20261022)

    assets: list[tuple[str, str, str, bytes, int, int]] = []
    for camera_id, _, _, file_name in CAMERAS:
        source_path = ASSET_ROOT / file_name
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing generated demo camera frame: {source_path}")
        image = source_path.read_bytes()
        width, height = png_size(image)
        target_name = f"{camera_id}.png"
        (image_root / target_name).write_bytes(image)
        assets.append((camera_id, f"demo-asset-{camera_id}", f"raw/images/demo/{target_name}", image, width, height))

    with store._connection() as connection:  # Deliberately scoped to demo-owned rows only.
        connection.execute("DELETE FROM vision_daily_rollups WHERE source = ?", (SOURCE,))
        connection.execute(
            "DELETE FROM vision_observations WHERE run_id IN (SELECT run_id FROM vision_runs WHERE model_name LIKE 'demo-%')"
        )
        connection.execute("DELETE FROM vision_runs WHERE model_name LIKE 'demo-%'")
        connection.execute("DELETE FROM camera_assets WHERE camera_id LIKE 'demo-%'")
        connection.execute("DELETE FROM sensor_daily_rollups WHERE source = ?", (SOURCE,))
        connection.execute("DELETE FROM sensor_readings WHERE source = ?", (SOURCE,))
        connection.execute("DELETE FROM sensor_devices WHERE sensor_id LIKE 'demo-%'")
        connection.execute("DELETE FROM camera_devices WHERE camera_id LIKE 'demo-%'")
        connection.execute("DELETE FROM farm_zones WHERE zone_id IN ('zone-a1', 'zone-a2', 'zone-b2')")

        connection.executemany(
            "INSERT INTO farm_zones(zone_id, name, greenhouse_id, bed_id, zone_type, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("zone-a1", "재배 베드 A1", "greenhouse-a", "A1", "grow-bed", json.dumps({"crop": "citrus"})),
                ("zone-a2", "재배 베드 A2", "greenhouse-a", "A2", "grow-bed", json.dumps({"crop": "citrus"})),
                ("zone-b2", "재배 베드 B2", "greenhouse-a", "B2", "grow-bed", json.dumps({"crop": "citrus"})),
            ],
        )
        connection.executemany(
            """
            INSERT INTO sensor_devices(sensor_id, zone_id, sensor_type, display_name, unit, installed_at, status, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            [
                (sensor_id, zone_id, metric, name, unit, start_kst.isoformat(), json.dumps({"source": SOURCE}))
                for sensor_id, zone_id, metric, name, unit, _, _, _ in SENSORS
            ],
        )
        connection.executemany(
            """
            INSERT INTO sensor_aliases(alias, sensor_id, source) VALUES (?, ?, 'demo-alias')
            ON CONFLICT(alias) DO UPDATE SET
                sensor_id = excluded.sensor_id,
                source = excluded.source
            """,
            DEMO_SENSOR_ALIASES.items(),
        )
        connection.executemany(
            """
            INSERT INTO camera_devices(camera_id, zone_id, display_name, camera_type, status, metadata_json)
            VALUES (?, ?, ?, 'rgb-top-view', 'active', ?)
            """,
            [(camera_id, zone_id, name, json.dumps({"source": SOURCE})) for camera_id, zone_id, name, _ in CAMERAS],
        )

        readings: dict[tuple[str, str, str], list[float]] = {}
        for offset in range(7 * 24):
            scheduled_kst = start_kst + timedelta(hours=offset)
            # Installation clocks and radio delivery introduce small timestamp jitter.
            observed_kst = scheduled_kst + timedelta(minutes=randomizer.randint(-4, 4))
            hour_wave = math.sin((observed_kst.hour + observed_kst.minute / 60 - 7) / 24 * 2 * math.pi)
            day_wave = math.sin(offset / (24 * 3) * 2 * math.pi)
            for position, (sensor_id, _, metric, _, unit, base, amplitude, noise) in enumerate(SENSORS):
                value = round(base + amplitude * hour_wave + 0.45 * day_wave + position * 0.12 + randomizer.gauss(0, noise), 2)
                connection.execute(
                    """
                    INSERT INTO sensor_readings(sensor_id, metric, value, unit, recorded_at, source, quality, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, 'good', ?)
                    """,
                    (sensor_id, metric, value, unit, observed_kst.astimezone(timezone.utc).isoformat(), SOURCE,
                     json.dumps({"local_time": observed_kst.isoformat(), "sample_interval_minutes": 60}, ensure_ascii=False)),
                )
                readings.setdefault((sensor_id, metric, observed_kst.date().isoformat()), []).append(value)

        calculated_at = datetime.now(timezone.utc).isoformat()
        for (sensor_id, metric, local_date), values in readings.items():
            unit = next(item[4] for item in SENSORS if item[0] == sensor_id)
            connection.execute(
                """
                INSERT INTO sensor_daily_rollups(
                    sensor_id, metric, local_date, unit, sample_count, min_value, max_value,
                    avg_value, stddev_value, p05_value, p50_value, p95_value, source, calculated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sensor_id, metric, local_date, unit, len(values), min(values), max(values), statistics.fmean(values),
                 statistics.pstdev(values), percentile(values, 0.05), percentile(values, 0.50), percentile(values, 0.95), SOURCE, calculated_at),
            )

        asset_by_camera = {camera_id: (asset_id, file_path, image, width, height) for camera_id, asset_id, file_path, image, width, height in assets}
        for camera_id, _, _, _ in CAMERAS:
            asset_id, file_path, image, width, height = asset_by_camera[camera_id]
            connection.execute(
                """
                INSERT INTO camera_assets(asset_id, camera_id, captured_at, file_path, sha256, content_type, byte_size, width, height, created_at)
                VALUES (?, ?, ?, ?, ?, 'image/png', ?, ?, ?, ?)
                """,
                (asset_id, camera_id, now_kst.astimezone(timezone.utc).isoformat(), file_path,
                 hashlib.sha256(image).hexdigest(), len(image), width, height, calculated_at),
            )

        for day_offset in range(7):
            captured_kst = (now_kst - timedelta(days=day_offset)).replace(hour=10, minute=15)
            for camera_index, (camera_id, _, _, _) in enumerate(CAMERAS):
                local_date = captured_kst.date().isoformat()
                asset_id = asset_by_camera[camera_id][0]
                run_id = f"demo-run-{camera_id}-{local_date}"
                coverage = round(0.58 + 0.018 * camera_index + 0.012 * math.sin(day_offset), 3)
                confidence = round(0.90 - 0.006 * day_offset, 3)
                plants = 28 + camera_index * 3 - (1 if day_offset == 5 and camera_index == 1 else 0)
                result = {"label": "citrus", "instance_count": plants, "coverage_ratio": coverage, "mean_confidence": confidence}
                connection.execute(
                    """INSERT INTO vision_runs(run_id, asset_id, model_name, model_version, status, started_at, completed_at, result_json)
                    VALUES (?, ?, 'demo-citrus-segmentation', '0.1.0-demo', 'completed', ?, ?, ?)""",
                    (run_id, asset_id, calculated_at, calculated_at, json.dumps(result)),
                )
                connection.execute(
                    """INSERT INTO vision_observations(
                        observation_id, run_id, asset_id, label, instance_count, coverage_ratio, mean_confidence, metrics_json
                    ) VALUES (?, ?, ?, 'citrus', ?, ?, ?, ?)""",
                    (f"demo-observation-{camera_id}-{local_date}", run_id, asset_id, plants, coverage, confidence, json.dumps(result)),
                )
                connection.execute(
                    """INSERT INTO vision_daily_rollups(
                        camera_id, local_date, label, image_count, total_instances, avg_coverage_ratio,
                        avg_confidence, alert_count, source, calculated_at
                    ) VALUES (?, ?, 'citrus', 1, ?, ?, ?, ?, ?, ?)""",
                    (camera_id, local_date, plants, coverage, confidence, 1 if coverage < 0.59 else 0, SOURCE, calculated_at),
                )

    print(f"Seeded {len(SENSORS) * 7 * 24} noisy raw sensor readings and {len(CAMERAS)} SSD camera frames into {store.database_path}")


if __name__ == "__main__":
    seed()
