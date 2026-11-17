#!/usr/bin/env python3
"""Stdlib-only multi-node protocol simulator for the beacon server."""

from __future__ import annotations

import argparse
import base64
import json
import math
import random
import sqlite3
import statistics
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.policy import base_schedule


# A valid, self-contained 8x8 JPEG generated once and embedded for simulation.
SIM_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd3eHqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq6/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA//9k="
)
SIM_JPEG = SIM_JPEG[:-2] + b"\xff\xd9"  # Restore the required JPEG EOI marker.


def http_request(base: str, path: str, method: str = "GET", body: bytes | None = None,
                 headers: dict[str, str] | None = None, timeout: float = 8.0):
    request = Request(base.rstrip("/") + path, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read(8192)
    except HTTPError as exc:
        return exc.code, exc.read(8192)
    except (URLError, TimeoutError, OSError) as exc:
        return 0, str(exc).encode("utf-8", "replace")


def json_request(base: str, path: str, method: str = "GET", payload=None):
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    status, raw = http_request(base, path, method, body, headers, timeout=5)
    try:
        value = json.loads(raw.decode("utf-8")) if raw else None
    except json.JSONDecodeError:
        value = None
    return status, value


def parse_response(raw: bytes) -> tuple[dict[str, str], list[tuple[int, str, dict[str, str]]]] | None:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    lines = text.splitlines()
    if not lines or lines[-1] != "end":
        return None
    values: dict[str, str] = {}
    commands = []
    for line in lines:
        if line == "end":
            continue
        if line.startswith("cmd="):
            parts = line[4:].split()
            if len(parts) < 2:
                return None
            try:
                cmd_id = int(parts[0])
            except ValueError:
                return None
            params = {}
            for part in parts[2:]:
                if "=" in part:
                    key, value = part.split("=", 1)
                    params[key] = value
            commands.append((cmd_id, parts[1], params))
        elif "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values, commands


class Simulation:
    def __init__(self, args):
        self.args = args
        self.stop = threading.Event()
        self.initial_actions_done = threading.Event()
        self.first_checkins = 0
        self.first_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.states: dict[str, str] = {}
        self.intervals: dict[str, int] = {}
        self.watch_until: dict[str, float] = {}
        self.stats_lock = threading.Lock()
        self.stats = {
            "checkins": 0, "wifi_failures": 0, "http_failures": 0,
            "truncated_responses": 0, "result_upload_losses": 0,
            "duplicate_result_replies": 0, "longpoll_disconnects": 0,
            "fast_successes": 0, "fast_attempts": 0,
            "awake_ms": [], "next_records": [], "command_ids": [],
            "attached_ids": [], "nonattached_command_rejections": 0,
            "admin_actions": [], "node_errors": [],
        }
        self.policy_config = {
            "test_mode": True,
            "test_min_next_s": 5,
            "test_discovered_next_s": 5,
            "test_detached_next_s": 5,
            "default_interval_s": 300,
            "vbat_low_mv": 3450,
            "vbat_critical_mv": 3300,
        }

    def record(self, key: str, value=1):
        with self.stats_lock:
            if isinstance(self.stats.get(key), list):
                self.stats[key].append(value)
            else:
                self.stats[key] = self.stats.get(key, 0) + value

    def set_state(self, node_id: str, state: str, interval: int | None = None):
        with self.state_lock:
            self.states[node_id] = state
            if interval is not None:
                self.intervals[node_id] = interval

    def expected_policy_base(self, node_id: str, vbat_mv: int) -> tuple[int, str]:
        with self.state_lock:
            state = self.states.get(node_id, "DISCOVERED")
            interval = self.intervals.get(node_id, 300)
        node = {
            "state": state, "interval_s": interval, "session_req_s": 0,
            "watch_until": None, "last_vbat_mv": vbat_mv,
        }
        node["watch_until"] = self.watch_until.get(node_id)
        base, _hold, reason = base_schedule(node, self.policy_config)
        return base, state if reason != "watch" else "watch"

    def exercise_admin(self):
        if not self.args.exercise_admin:
            self.initial_actions_done.set()
            return
        deadline = time.monotonic() + 25
        discovered = set()
        while time.monotonic() < deadline and not self.stop.is_set():
            status, value = json_request(self.args.admin_url, "/admin/nodes")
            if status == 200 and isinstance(value, list):
                discovered = {item["id"] for item in value}
                if len(discovered) >= self.args.n:
                    break
            time.sleep(0.25)
        if len(discovered) < self.args.n:
            self.stats["node_errors"].append(f"only {len(discovered)} of {self.args.n} nodes discovered")

        attached = [f"tc-{index:06x}" for index in range(1, min(16, self.args.n) + 1)]
        for index, node_id in enumerate(attached):
            status, value = json_request(
                self.args.admin_url, f"/admin/nodes/{node_id}/attach", "POST",
                {"label": f"sim-{index + 1}", "interval_s": 5},
            )
            self.stats["admin_actions"].append({"action": "attach", "node": node_id, "status": status})
            if status == 200:
                self.set_state(node_id, "ATTACHED", 5)
                self.record("attached_ids", node_id)

        detached = attached[12:16]
        for node_id in detached:
            status, _ = json_request(
                self.args.admin_url, f"/admin/nodes/{node_id}/detach", "POST", {}
            )
            self.stats["admin_actions"].append({"action": "detach", "node": node_id, "status": status})
            if status == 200:
                self.set_state(node_id, "DETACHED", 300)

        for node_id in attached[:12]:
            command_types = ["sensor"]
            if int(node_id[-2:], 16) - 1 < 8:
                command_types.append("image")
            if 8 <= int(node_id[-2:], 16) - 1 < 12:
                command_types.append("config")
            for command_type in command_types:
                params = {"fs": "VGA", "q": 12, "warm": 500} if command_type == "image" else (
                    {"fast": 1} if command_type == "config" else {}
                )
                status, value = json_request(
                    self.args.admin_url, f"/admin/nodes/{node_id}/commands", "POST",
                    {"type": command_type, "params": params},
                )
                self.stats["admin_actions"].append({"action": command_type, "node": node_id, "status": status})
                if status == 202 and isinstance(value, dict):
                    self.record("command_ids", int(value["cmd_id"]))

        for node_id in attached[:3]:
            status, _ = json_request(
                self.args.admin_url, f"/admin/nodes/{node_id}/session", "POST", {"hold_s": 30}
            )
            self.stats["admin_actions"].append({"action": "session", "node": node_id, "status": status})
        if len(attached) > 3:
            self.watch_node = attached[3]
            status, value = json_request(
                self.args.admin_url, f"/admin/nodes/{self.watch_node}/watch", "POST", {"minutes": 1}
            )
            self.stats["admin_actions"].append({"action": "watch", "node": self.watch_node, "status": status})
            if status == 200 and isinstance(value, dict):
                self.watch_until[self.watch_node] = float(value["watch_until"])

        # These requests must be rejected and must not create command rows.
        for node_id in (f"tc-{max(17, self.args.n):06x}", detached[0] if detached else attached[0]):
            status, _ = json_request(
                self.args.admin_url, f"/admin/nodes/{node_id}/commands", "POST",
                {"type": "sensor", "params": {}},
            )
            self.stats["admin_actions"].append({"action": "reject_nonattached", "node": node_id, "status": status})
            if status == 409:
                self.record("nonattached_command_rejections")

        self.initial_actions_done.set()

    def run_nodes(self):
        nodes = [SimNode(self, index) for index in range(1, self.args.n + 1)]
        for node in nodes:
            node.start()
        self.exercise_admin()
        deadline = time.monotonic() + self.args.duration
        while time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        self.stop.set()
        self.initial_actions_done.set()
        for node in nodes:
            node.join(timeout=5)
        return nodes

    def write_report(self):
        data = dict(self.stats)
        data["attached_ids"] = sorted(set(data["attached_ids"]))
        data["command_ids"] = sorted(set(data["command_ids"]))
        db_path = Path(self.args.db) if self.args.db else None
        db_checks = {}
        if db_path and db_path.is_file():
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            command_ids = data["command_ids"]
            if command_ids:
                marks = ",".join("?" for _ in command_ids)
                rows = db.execute(
                    f"SELECT id,node_id,state,reason,created_at,done_at,expires_at FROM commands WHERE id IN ({marks})",
                    command_ids,
                ).fetchall()
            else:
                rows = []
            processed = [
                row for row in rows
                if row["state"] in ("done", "failed")
                and row["reason"] != "no_result"
                and row["done_at"] is not None
                and row["done_at"] <= row["expires_at"]
            ]
            nonattached_dispatched = db.execute(
                "SELECT COUNT(*) FROM commands c JOIN nodes n ON n.id=c.node_id "
                "WHERE n.state IN ('DISCOVERED','DETACHED') AND c.state IN ('dispatched','done')"
            ).fetchone()[0]
            duplicate_rows = db.execute(
                "SELECT COUNT(*) FROM (SELECT cmd_id FROM readings GROUP BY cmd_id HAVING COUNT(*)>1)"
            ).fetchone()[0]
            duplicate_images = db.execute(
                "SELECT COUNT(*) FROM (SELECT cmd_id FROM images GROUP BY cmd_id HAVING COUNT(*)>1)"
            ).fetchone()[0]
            db_checks = {
                "commands_created": len(command_ids),
                "commands_found": len(rows),
                "commands_processed_before_expiry": len(processed),
                "command_processing_ratio": round(len(processed) / len(command_ids), 4) if command_ids else None,
                "nonattached_dispatched_commands": int(nonattached_dispatched),
                "duplicate_result_rows": int(duplicate_rows + duplicate_images),
            }
            db.close()

        next_records = data["next_records"]
        next_valid = sum(1 for item in next_records if item["within_policy_jitter"])
        fast_rate = (
            data["fast_successes"] / data["fast_attempts"] if data["fast_attempts"] else None
        )
        report = {
            "run": {"n": self.args.n, "duration_s": self.args.duration, "seed": self.args.seed},
            "faults": {
                "wifi_failure_rate": 0.05,
                "result_upload_loss_rate_per_attempt": 0.10,
                "truncated_response_rate": 0.02,
                "longpoll_disconnect_rate": 0.02,
                "observed_wifi_failures": data["wifi_failures"],
                "observed_result_upload_losses": data["result_upload_losses"],
                "observed_truncated_responses": data["truncated_responses"],
                "observed_longpoll_disconnects": data["longpoll_disconnects"],
                "observed_duplicate_result_replies": data["duplicate_result_replies"],
            },
            "protocol": {
                "checkins": data["checkins"],
                "fast_path_success_rate": round(fast_rate, 4) if fast_rate is not None else None,
                "median_prev_awake_ms": statistics.median(data["awake_ms"]) if data["awake_ms"] else None,
                "next_values_checked": len(next_records),
                "next_values_within_policy_jitter": next_valid,
                "all_next_values_within_policy_jitter": next_valid == len(next_records) and bool(next_records),
                "nonattached_command_rejections_http_409": data["nonattached_command_rejections"],
                "next_records": next_records,
            },
            "database": db_checks,
            "scenario": {
                "command_ids": data["command_ids"],
                "attached_ids": data["attached_ids"],
            },
            "acceptance": {
                "AC2_command_completion_ge_99_percent": (
                    db_checks.get("command_processing_ratio") is not None
                    and db_checks["command_processing_ratio"] >= 0.99
                    and db_checks.get("duplicate_result_rows", 1) == 0
                ),
                "AC3_no_discovered_or_detached_dispatch": (
                    db_checks.get("nonattached_dispatched_commands") == 0
                    and data["nonattached_command_rejections"] == 2
                ),
                "AC4_all_next_within_policy_jitter": next_valid == len(next_records) and bool(next_records),
            },
            "admin_actions": data["admin_actions"],
            "warnings": data["node_errors"],
        }
        target = Path(self.args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"sim_report": str(target), "acceptance": report["acceptance"]}, indent=2))
        return report


class SimNode(threading.Thread):
    def __init__(self, simulation: Simulation, index: int):
        super().__init__(name=f"sim-{index:02d}", daemon=True)
        self.sim = simulation
        self.index = index
        self.node_id = f"tc-{index:06x}"
        self.rng = random.Random(simulation.args.seed * 1000 + index)
        self.token: str | None = None
        self.seq = 0
        self.next_saved = 5 if simulation.args.test_mode else 300
        self.fail_count = 0
        self.first_reported = False
        self.prev_awake_ms = 0
        self.prev_result = "ok"
        self.stopped = False

    def headers(self):
        values = {"X-Node-Id": self.node_id}
        if self.token:
            values["X-Token"] = self.token
        return values

    def report_first(self):
        if self.first_reported:
            return
        self.first_reported = True
        with self.sim.first_lock:
            self.sim.first_checkins += 1

    def should_truncate(self) -> bool:
        # Avoid dropping the one-time token delivery; inject truncation after
        # authentication is established so normal token recovery stays testable.
        return self.token is not None and self.rng.random() < 0.02

    def record_next(self, value: int, vbat_mv: int):
        base, state = self.sim.expected_policy_base(self.node_id, vbat_mv)
        minimum = 5 if self.sim.args.test_mode else 30
        low = max(minimum, math.floor(base * 0.9 + 0.5))
        high = min(15300, math.floor(base * 1.1 + 0.5))
        self.sim.record("next_records", {
            "node_id": self.node_id, "state": state, "base_s": base,
            "next_s": value, "within_policy_jitter": low <= value <= high,
        })

    def request_checkin(self):
        fast = 1 if self.rng.random() < 0.9 else 0
        vbat = self.rng.randint(3720, 4140)
        rssi = self.rng.randint(-78, -42)
        self.seq = (self.seq + 1) & 0xFFFFFFFF
        self.sim.record("fast_attempts")
        if fast:
            self.sim.record("fast_successes")
        body = {
            "v": 1, "fw": "beacon-sim-0.1.0",
            "boot": "cold" if self.seq == 1 else "rtc", "seq": self.seq,
            "vbat_mv": vbat, "rssi": rssi, "ch": self.rng.randint(1, 11),
            "t": {
                "wifi_ms": self.rng.randint(60, 180) if fast else self.rng.randint(300, 800),
                "fast": fast, "prev_awake_ms": self.prev_awake_ms,
                "prev_result": self.prev_result,
            },
        }
        payload = json.dumps(body, separators=(",", ":")).encode()
        self.prev_awake_ms = 0
        started = time.monotonic()
        status, raw = http_request(
            self.sim.args.server, "/api/v1/checkin", "POST", payload,
            {**self.headers(), "Content-Type": "application/json"}, timeout=8,
        )
        self.report_first()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        self.prev_awake_ms = elapsed_ms
        if status == 401:
            self.token = None
            self.prev_result = "http_fail"
            self.sim.record("http_failures")
            return None, vbat
        if status != 200:
            self.prev_result = "http_fail"
            self.sim.record("http_failures")
            return None, vbat

        parsed = parse_response(raw)
        if self.should_truncate():
            self.sim.record("truncated_responses")
            parsed = None
        if parsed is None:
            self.prev_result = "http_fail"
            return None, vbat
        values, commands = parsed
        try:
            next_s = int(values["next"])
            if not 30 <= next_s <= 15300 and not self.sim.args.test_mode:
                return None, vbat
            if self.sim.args.test_mode and not 5 <= next_s <= 15300:
                return None, vbat
        except (KeyError, ValueError):
            return None, vbat
        if "tok" in values:
            self.token = values["tok"]
        self.next_saved = next_s
        self.record_next(next_s, vbat)
        self.sim.record("checkins")
        self.prev_result = "ok"
        return (values, commands), vbat

    def command_result(self, cmd_id: int, command_type: str, params: dict[str, str]):
        if command_type == "sensor":
            if self.index % 4 == 0:
                body = {"ok": 0, "err": "sensor_absent"}
            else:
                body = {"ok": 1, "sensors": [{
                    "type": "sht30", "addr": 68,
                    "t_c": round(self.rng.uniform(15, 30), 2),
                    "rh": round(self.rng.uniform(35, 85), 1),
                }]}
            return "application/json", json.dumps(body, separators=(",", ":")).encode(), {}
        if command_type == "image":
            return "image/jpeg", SIM_JPEG, {
                "X-Warm-Ms": params.get("warm", "500"),
                "X-Init-Ms": str(self.rng.randint(80, 240)),
                "X-Fs": params.get("fs", "VGA"),
                "X-Q": params.get("q", "12"),
            }
        if command_type == "config":
            return "application/json", b'{"ok":1}', {}
        if command_type == "hibernate":
            return "application/json", b'{"ok":1}', {}
        return "application/json", b'{"ok":0,"err":"unknown_command"}', {}

    def upload_result(self, cmd_id: int, command_type: str, params: dict[str, str]) -> bool:
        content_type, body, extra = self.command_result(cmd_id, command_type, params)
        headers = {**self.headers(), "Content-Type": content_type, **extra}
        path = f"/api/v1/result?cmd={cmd_id}"
        for attempt in range(2):
            if self.rng.random() < 0.10:
                self.sim.record("result_upload_losses")
                continue
            status, response = http_request(
                self.sim.args.server, path, "POST", body, headers, timeout=10
            )
            if status == 200:
                if response.strip() == b"dup":
                    self.sim.record("duplicate_result_replies")
                    return True
                # Model an ACK lost after the server has committed: the retry
                # must receive 200 dup and must not create a second result row.
                if attempt == 0 and self.rng.random() < 0.10:
                    continue
                return True
            self.sim.record("http_failures")
        self.prev_result = "http_fail"
        return False

    def execute_commands(self, commands):
        for cmd_id, command_type, params in commands:
            started = time.monotonic()
            success = self.upload_result(cmd_id, command_type, params)
            awake_ms = int((time.monotonic() - started) * 1000)
            self.prev_awake_ms = max(self.prev_awake_ms, awake_ms)
            self.sim.record("awake_ms", awake_ms)
            if not success:
                self.prev_result = "http_fail"
            if command_type == "hibernate" and success:
                self.stopped = True
                return

    def disconnect_longpoll(self, wait_s: int):
        parsed = urlsplit(self.sim.args.server)
        import http.client
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=wait_s + 5)
        headers = self.headers()
        connection.request("GET", f"/api/v1/poll?wait={wait_s}", headers=headers)
        connection.close()
        self.sim.record("longpoll_disconnects")

    def poll_session(self, hold_s: int):
        deadline = time.monotonic() + min(180, hold_s)
        while not self.sim.stop.is_set() and not self.stopped:
            remaining = int(math.ceil(deadline - time.monotonic()))
            if remaining <= 0:
                return
            wait_s = min(20, remaining)
            if self.rng.random() < 0.02:
                try:
                    self.disconnect_longpoll(wait_s)
                except OSError:
                    pass
                self.prev_result = "http_fail"
                return
            status, raw = http_request(
                self.sim.args.server, f"/api/v1/poll?wait={wait_s}",
                headers=self.headers(), timeout=wait_s + 6,
            )
            if status != 200:
                self.prev_result = "http_fail"
                self.sim.record("http_failures")
                return
            parsed = parse_response(raw)
            if self.should_truncate():
                self.sim.record("truncated_responses")
                parsed = None
            if parsed is None:
                self.prev_result = "http_fail"
                return
            values, commands = parsed
            self.execute_commands(commands)
            try:
                remaining_hold = int(values.get("hold", "0"))
            except ValueError:
                remaining_hold = 0
            if remaining_hold <= 0:
                return

    def run(self):
        while not self.sim.stop.is_set() and not self.stopped:
            awake_started = time.monotonic()
            if self.rng.random() < 0.05:
                self.fail_count += 1
                self.prev_result = "wifi_fail"
                self.sim.record("wifi_failures")
                backoff = min(self.next_saved * (2 ** min(self.fail_count, 3)), 3600)
                self.sim.stop.wait(max(1, backoff))
                continue
            self.fail_count = 0
            result, vbat = self.request_checkin()
            if not self.sim.initial_actions_done.is_set():
                self.sim.initial_actions_done.wait(timeout=30)
            if result is None:
                next_s = self.next_saved
            else:
                values, commands = result
                self.execute_commands(commands)
                try:
                    hold_s = int(values.get("hold", "0"))
                except ValueError:
                    hold_s = 0
                if hold_s > 0:
                    self.poll_session(hold_s)
                next_s = self.next_saved
            self.prev_awake_ms = max(
                self.prev_awake_ms,
                int((time.monotonic() - awake_started) * 1000),
            )
            self.sim.stop.wait(max(1, next_s))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--server", required=True)
    parser.add_argument("--admin-url", default="http://127.0.0.1:8081")
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--exercise-admin", action="store_true")
    parser.add_argument("--db")
    parser.add_argument("--report", default="results/sim_report.json")
    args = parser.parse_args(argv)
    if not 1 <= args.n <= 200 or not 1 <= args.duration <= 86400:
        parser.error("--n must be 1..200 and --duration must be 1..86400")
    simulation = Simulation(args)
    simulation.run_nodes()
    report = simulation.write_report()
    return 0 if all(report["acceptance"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
