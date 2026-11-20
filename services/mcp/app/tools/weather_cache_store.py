"""Persistent cache for compact KMA dashboard responses in the shared SQLite DB."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path


logger = logging.getLogger(__name__)
DATABASE = Path(os.getenv("SQLITE_PATH", "/workspace/state/mirgam.db"))


def get(cache_key: str) -> tuple[dict, int] | None:
    """Return a cached object and its age in seconds, whether fresh or stale."""
    if not DATABASE.is_file():
        return None
    connection = None
    try:
        connection = sqlite3.connect(
            f"file:{DATABASE}?mode=ro", uri=True, timeout=5
        )
        connection.execute("PRAGMA busy_timeout = 5000")
        row = connection.execute(
            "SELECT payload_json, fetched_at_epoch FROM kma_weather_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            logger.warning("KMA SQLite cache read failed (error_type=%s)", type(exc).__name__)
        return None
    except sqlite3.Error as exc:
        logger.warning("KMA SQLite cache read failed (error_type=%s)", type(exc).__name__)
        return None
    finally:
        if connection is not None:
            connection.close()
    if row is None:
        return None
    try:
        payload = json.loads(row[0])
        if not isinstance(payload, dict):
            return None
        age_seconds = max(0, int(time.time() - float(row[1])))
        return payload, age_seconds
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("KMA SQLite cache entry is invalid (cache_key=%s)", cache_key)
        return None


def put(cache_key: str, payload: dict) -> None:
    """Persist a successful response; cache failures never break live requests."""
    connection = None
    try:
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        connection = sqlite3.connect(DATABASE, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS kma_weather_cache (
                cache_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                fetched_at_epoch REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO kma_weather_cache (cache_key, payload_json, fetched_at_epoch)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                fetched_at_epoch = excluded.fetched_at_epoch
            """,
            (cache_key, encoded, time.time()),
        )
        connection.execute(
            "DELETE FROM kma_weather_cache WHERE cache_key LIKE 'api:%' AND fetched_at_epoch < ?",
            (time.time() - 7 * 24 * 60 * 60,),
        )
        connection.commit()
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        logger.warning("KMA SQLite cache write failed (error_type=%s)", type(exc).__name__)
    finally:
        if connection is not None:
            connection.close()
