"""Scheduling and low-battery policy for beacon check-ins."""

from __future__ import annotations

import random
import time
from typing import Any, Mapping


def base_schedule(
    node: Mapping[str, Any], config: Mapping[str, Any], now: float | None = None
) -> tuple[int, int, str]:
    """Return (base next seconds, hold seconds, reason) before jitter."""
    now = time.time() if now is None else now
    state = node.get("state", "DISCOVERED")
    if state == "DISCOVERED":
        if config.get("test_mode") and config.get("test_discovered_next_s") is not None:
            return int(config["test_discovered_next_s"]), 0, "test_discovered"
        return 900, 0, "discovered"
    if state == "DETACHED":
        if config.get("test_mode") and config.get("test_detached_next_s") is not None:
            return int(config["test_detached_next_s"]), 0, "test_detached"
        return 3600, 0, "detached"
    if state == "HIBERNATING":
        return 3600, 0, "hibernating"
    if state != "ATTACHED":
        return 900, 0, "unknown_state"

    interval = int(node.get("interval_s") or config.get("default_interval_s", 300))
    session = min(180, max(0, int(node.get("session_req_s") or 0)))
    if session:
        return interval, session, "session"
    watch_until = node.get("watch_until")
    if watch_until is not None and float(watch_until) > now:
        return 60, 0, "watch"

    vbat_mv = node.get("last_vbat_mv")
    if vbat_mv is not None and int(vbat_mv) < int(config.get("vbat_critical_mv", 3300)):
        return 14400, 0, "low_battery_critical"
    if vbat_mv is not None and int(vbat_mv) < int(config.get("vbat_low_mv", 3450)):
        return min(14400, interval * 4), 0, "low_battery"
    return interval, 0, "interval"


def jittered_next(
    base_s: int,
    config: Mapping[str, Any],
    rng: Any | None = None,
) -> int:
    """Apply the required uniform ±10% jitter and protocol bounds."""
    rng = random if rng is None else rng
    test_mode = bool(config.get("test_mode", False))
    minimum = 5 if test_mode else 30
    value = int(round(rng.uniform(0.9 * base_s, 1.1 * base_s)))
    return max(minimum, min(15300, value))


def decide_next(
    node: Mapping[str, Any],
    config: Mapping[str, Any],
    rng: Any | None = None,
    now: float | None = None,
) -> tuple[int, int, int, str]:
    """Return (jittered next, hold, unjittered base, policy reason)."""
    base, hold, reason = base_schedule(node, config, now=now)
    return jittered_next(base, config, rng=rng), hold, base, reason


def online_status(node: Mapping[str, Any], now: float | None = None) -> str:
    now = time.time() if now is None else now
    last_seen = node.get("last_seen")
    next_given = node.get("next_given")
    if last_seen is None or next_given is None:
        return "offline"
    return "online" if now <= float(last_seen) + int(next_given) * 1.5 + 60 else "offline"
