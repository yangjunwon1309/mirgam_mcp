#!/usr/bin/env python3
"""HTTP/1.1 beacon node API and loopback-only management API."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

if __package__:
    from .policy import decide_next, online_status
    from .store import Store
else:  # Support the documented `python3 server/beacon_server.py` invocation.
    from policy import decide_next, online_status
    from store import Store

NODE_ID_RE = re.compile(r"^tc-[0-9a-f]{6}$")
BOOT_VALUES = {"rtc", "cold", "deepsleep", "wdt", "other"}
PREV_RESULTS = {"ok", "wifi_fail", "http_fail", "awake_cap", "rtc_fail"}
IMAGE_SIZES = {"QVGA", "VGA", "SVGA", "XGA", "HD", "SXGA", "UXGA"}
COMMAND_TYPES = {"sensor", "image", "config", "hibernate"}
TERMINAL_STATES = {"done", "failed", "expired"}


class BeaconError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("configuration root must be a JSON object")
    for key, default in (("node_port", 8080), ("admin_port", 8081)):
        port = int(config.get(key, default))
        if not 0 <= port <= 65535:
            raise ValueError(f"{key} must be between 0 and 65535")
        config[key] = port
    config["default_interval_s"] = int(config.get("default_interval_s", 300))
    config["vbat_low_mv"] = int(config.get("vbat_low_mv", 3450))
    config["vbat_critical_mv"] = int(config.get("vbat_critical_mv", 3300))
    config["test_mode"] = bool(config.get("test_mode", False))
    config["test_min_next_s"] = int(config.get("test_min_next_s", 5))
    if "test_discovered_next_s" in config:
        config["test_discovered_next_s"] = int(config["test_discovered_next_s"])
    if "test_detached_next_s" in config:
        config["test_detached_next_s"] = int(config["test_detached_next_s"])
    config["max_image_bytes"] = int(config.get("max_image_bytes", 2 * 1024 * 1024))
    data_dir = Path(config.get("data_dir", "/mnt/nvme/beacon"))
    config["data_dir"] = str(data_dir)
    config["db_path"] = str(Path(config.get("db_path", data_dir / "beacon.db")))
    config["images_dir"] = str(Path(config.get("images_dir", data_dir / "images")))
    config.setdefault("energy", {})
    return config


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read width and height from baseline/progressive JPEG SOF markers."""
    if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
        return None
    index = 2
    sof = {0xC0, 0xC2}
    while index + 4 <= len(data) - 2:
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            return None
        marker = data[index]
        index += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if index + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            return None
        if marker in sof:
            if segment_length < 7:
                return None
            height = int.from_bytes(data[index + 3:index + 5], "big")
            width = int.from_bytes(data[index + 5:index + 7], "big")
            return (width, height) if width > 0 and height > 0 else None
        if marker == 0xDA:  # Start of scan: SOF must precede entropy-coded data.
            return None
        index += segment_length
    return None


def _int_field(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or value < low or value > high:
        raise BeaconError(400, f"invalid {name}")
    return value


def validate_checkin(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or body.get("v") != 1:
        raise BeaconError(400, "invalid check-in")
    if not isinstance(body.get("fw"), str) or not 1 <= len(body["fw"]) <= 48:
        raise BeaconError(400, "invalid fw")
    if body.get("boot") not in BOOT_VALUES:
        raise BeaconError(400, "invalid boot")
    body["seq"] = _int_field(body.get("seq"), "seq", 0, 0xFFFFFFFF)
    body["vbat_mv"] = _int_field(body.get("vbat_mv"), "vbat_mv", 0, 6000)
    body["rssi"] = _int_field(body.get("rssi"), "rssi", -127, 0)
    body["ch"] = _int_field(body.get("ch"), "ch", 0, 14)
    timing = body.get("t")
    if not isinstance(timing, dict):
        raise BeaconError(400, "invalid timing")
    for key, low, high in (
        ("wifi_ms", 0, 120000),
        ("fast", 0, 1),
        ("prev_awake_ms", 0, 600000),
    ):
        if key in timing:
            timing[key] = _int_field(timing[key], key, low, high)
    if timing.get("prev_result", "ok") not in PREV_RESULTS:
        raise BeaconError(400, "invalid prev_result")
    return body


class BeaconApplication:
    def __init__(self, config: dict[str, Any], store: Store | None = None):
        self.config = config
        self.store = store or Store(config["db_path"])
        self.images_dir = Path(config["images_dir"])
        self._conditions_lock = threading.Lock()
        self._conditions: dict[str, threading.Condition] = {}
        self._session_lock = threading.Lock()
        self._session_deadlines: dict[str, float] = {}
        self.results_condition = threading.Condition()

    def close(self) -> None:
        self.store.close()

    def log(self, node_id: str, action: str, result: str, started: float) -> None:
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "node": node_id or "-",
            "request": action,
            "result": result,
            "ms": round((time.monotonic() - started) * 1000, 1),
        }
        print(json.dumps(record, separators=(",", ":")), flush=True)

    def condition_for(self, node_id: str) -> threading.Condition:
        with self._conditions_lock:
            return self._conditions.setdefault(node_id, threading.Condition())

    def notify_node(self, node_id: str) -> None:
        condition = self.condition_for(node_id)
        with condition:
            condition.notify_all()

    def start_session(self, node_id: str, hold_s: int) -> None:
        with self._session_lock:
            if hold_s > 0:
                self._session_deadlines[node_id] = time.time() + min(180, hold_s)
            else:
                self._session_deadlines.pop(node_id, None)

    def hold_remaining(self, node_id: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._session_lock:
            deadline = self._session_deadlines.get(node_id, 0.0)
            remaining = max(0, int(math.ceil(deadline - now)))
            if remaining == 0:
                self._session_deadlines.pop(node_id, None)
            return min(180, remaining)

    @staticmethod
    def _format_command(command: dict[str, Any]) -> str:
        params = command.get("params") or {}
        fields: list[str] = []
        if command["type"] == "image":
            params = {"fs": "VGA", "q": 12, "warm": 500, **params}
        for key in sorted(params):
            value = params[key]
            key_text = str(key)
            value_text = str(value)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_text):
                continue
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", value_text):
                continue
            fields.append(f"{key_text}={value_text}")
        suffix = " " + " ".join(fields) if fields else ""
        return f"cmd={command['id']} {command['type']}{suffix}"

    def _response_text(
        self,
        node: dict[str, Any],
        next_s: int,
        hold_s: int,
        token: str | None,
        commands: list[dict[str, Any]],
    ) -> bytes:
        lines = ["v=1", f"next={next_s}"]
        if token:
            lines.append(f"tok={token}")
        lines.append(f"hold={hold_s}")
        lines.extend(self._format_command(command) for command in commands[:4])
        lines.append("end")
        response = ("\n".join(lines) + "\n").encode("ascii")
        if len(response) > 2048:
            # Command parameters are bounded by the management API. If a future
            # change violates that bound, fail closed by returning no commands.
            response = f"v=1\nnext={next_s}\nhold={hold_s}\nend\n".encode("ascii")
        return response

    def process_checkin(
        self, node_id: str, body: dict[str, Any], token: str, ip: str
    ) -> bytes:
        now = time.time()
        auth, node, issue_token = self.store.register_checkin(
            node_id, body, ip, token, now
        )
        if auth != "ok" or node is None:
            raise BeaconError(401, "unauthorized")
        next_s, hold_s, _base, _reason = decide_next(node, self.config, now=now)
        if hold_s:
            self.start_session(node_id, hold_s)
            self.store.consume_session_request(node_id)
        elif self.hold_remaining(node_id, now) == 0:
            self.start_session(node_id, 0)

        commands: list[dict[str, Any]] = []
        if node["state"] == "ATTACHED":
            if int(node.get("last_vbat_mv") or 0) < int(self.config["vbat_low_mv"]):
                self.store.fail_queued_images_low_battery(node_id, now)
            commands = self.store.dispatch_commands(node_id, now, limit=4)
        self.store.record_checkin(node_id, body, next_s, now)
        return self._response_text(node, next_s, hold_s, issue_token, commands)

    def authenticate(self, node_id: str, token: str) -> dict[str, Any]:
        node = self.store.get_node(node_id)
        if (
            node is None
            or not node.get("token")
            or not bool(node.get("token_sent"))
            or not token
            or not secrets_compare(str(node["token"]), token)
        ):
            raise BeaconError(401, "unauthorized")
        return node

    def process_poll(self, node_id: str, token: str, wait_s: int) -> bytes:
        node = self.authenticate(node_id, token)
        if node["state"] != "ATTACHED":
            raise BeaconError(401, "unauthorized")
        deadline = time.monotonic() + wait_s
        condition = self.condition_for(node_id)
        commands: list[dict[str, Any]] = []
        while True:
            now = time.time()
            node = self.store.get_node(node_id) or node
            if node["state"] != "ATTACHED":
                raise BeaconError(401, "unauthorized")
            if int(node.get("last_vbat_mv") or 0) < int(self.config["vbat_low_mv"]):
                self.store.fail_queued_images_low_battery(node_id, now)
            commands = self.store.dispatch_commands(node_id, now, limit=4)
            hold_s = self.hold_remaining(node_id, now)
            if commands or hold_s == 0:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            with condition:
                condition.wait(timeout=min(remaining, hold_s if hold_s else remaining))
        next_s = int(node.get("next_given") or node.get("interval_s") or 300)
        hold_s = self.hold_remaining(node_id)
        return self._response_text(node, next_s, hold_s, None, commands)

    def _safe_node(self, node: dict[str, Any]) -> dict[str, Any]:
        public = {key: value for key, value in node.items() if key != "token"}
        public["online"] = online_status(node)
        return public

    def _command_public(self, command: dict[str, Any]) -> dict[str, Any]:
        item = dict(command)
        result = self.store.get_command_result(int(command["id"]))
        item["result"] = result
        return item

    def energy_report(self, node_id: str) -> dict[str, Any] | None:
        node = self.store.get_node(node_id)
        if node is None:
            return None
        now = time.time()
        rows = self.store.energy_rows(node_id)
        day_rows = [row for row in rows if row["received_at"] >= now - 86400]
        counts = self.store.daily_command_counts(node_id, now - 86400)
        fast_values = [int(row["fast"]) for row in day_rows if row["fast"] is not None]
        fast_fraction = (sum(fast_values) / len(fast_values)) if fast_values else 0.0
        energy = self.config.get("energy", {})
        active_ma = float(energy.get("i_active_ma", 120.0))
        camera_ma = float(energy.get("i_cam_ma", 160.0))
        sensor_ma = float(energy.get("i_sensor_ma", 20.0))
        off_ua = float(energy.get("i_off_ua", 20.0))
        usable = float(energy.get("usable_mah", 1560.0))
        fast_s = float(energy.get("checkin_fast_s", 1.5))
        slow_s = float(energy.get("checkin_slow_s", 3.5))
        image_s = float(energy.get("image_active_s", 1.2))
        sensor_s = float(energy.get("sensor_active_s", 0.2))
        interval = int(node.get("interval_s") or self.config["default_interval_s"])
        checkins_per_day = 86400.0 / max(30, interval)
        checkin_seconds = fast_fraction * fast_s + (1.0 - fast_fraction) * slow_s
        e_checkin = active_ma * checkin_seconds / 3600.0
        e_image = camera_ma * image_s / 3600.0
        e_sensor = sensor_ma * sensor_s / 3600.0
        images_per_day = counts.get("image", 0)
        sensors_per_day = counts.get("sensor", 0)
        off_mah_day = off_ua * 24.0 / 1000.0
        daily = (
            checkins_per_day * e_checkin
            + images_per_day * e_image
            + sensors_per_day * e_sensor
            + off_mah_day
        )
        return {
            "node_id": node_id,
            "interval_s": interval,
            "observed_checkins_24h": len(day_rows),
            "fast_success_fraction_24h": round(fast_fraction, 4),
            "images_24h": images_per_day,
            "sensor_commands_24h": sensors_per_day,
            "estimated_mAh_day": round(daily, 4),
            "usable_mah": usable,
            "estimated_days_remaining": round(usable / daily, 2) if daily > 0 else None,
            "assumptions": {"i_off_ua": off_ua, "fast_connect_s": fast_s, "slow_connect_s": slow_s},
        }


def secrets_compare(left: str, right: str) -> bool:
    # compare_digest avoids timing-sensitive token comparisons.
    import hmac

    return hmac.compare_digest(left.encode("ascii", "ignore"), right.encode("ascii", "ignore"))


def _parse_json(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeaconError(400, "invalid JSON") from exc


class BeaconRequestHandler(BaseHTTPRequestHandler):
    server_version = "Beacon/1"
    protocol_version = "HTTP/1.1"
    app: BeaconApplication
    is_admin = False

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)
        self.close_connection = True

    def _send_json(self, status: int, value: Any) -> None:
        self._send(
            status,
            json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _read_body(self, limit: int) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise BeaconError(411, "Content-Length required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise BeaconError(400, "invalid Content-Length") from exc
        if length < 0:
            raise BeaconError(400, "invalid Content-Length")
        if length > limit:
            raise BeaconError(413, "request too large")
        data = self.rfile.read(length)
        if len(data) != length:
            raise BeaconError(400, "truncated request")
        return data

    def _node_id(self) -> str:
        node_id = self.headers.get("X-Node-Id", "")
        if not NODE_ID_RE.fullmatch(node_id):
            raise BeaconError(400, "invalid X-Node-Id")
        return node_id

    def _token(self) -> str:
        token = self.headers.get("X-Token", "")
        if len(token) > 64:
            raise BeaconError(401, "unauthorized")
        return token

    def _error(self, exc: BeaconError) -> None:
        if self.is_admin:
            self._send_json(exc.status, {"error": exc.message})
        else:
            self._send(exc.status, exc.message.encode("utf-8"), "text/plain; charset=utf-8")

    def do_GET(self) -> None:
        started = time.monotonic()
        node_id = "-"
        action = urlsplit(self.path).path
        outcome = "error"
        try:
            if self.is_admin:
                self._admin_get(urlsplit(self.path))
            else:
                node_id = self._node_id()
                if action != "/api/v1/poll":
                    raise BeaconError(404, "not found")
                query = parse_qs(urlsplit(self.path).query, strict_parsing=False)
                wait_values = query.get("wait", ["20"])
                try:
                    wait_s = int(wait_values[0])
                except ValueError as exc:
                    raise BeaconError(400, "invalid wait") from exc
                if not 0 <= wait_s <= 30:
                    raise BeaconError(400, "wait must be 0..30")
                response = self.app.process_poll(node_id, self._token(), wait_s)
                self._send(200, response, "text/plain; charset=utf-8")
            outcome = "ok"
        except BeaconError as exc:
            outcome = f"http_{exc.status}"
            self._error(exc)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError) as exc:
            outcome = f"io_{type(exc).__name__}"
        except Exception:
            logging.exception("GET handler failed")
            outcome = "internal_error"
            self._error(BeaconError(500, "internal error"))
        finally:
            self.app.log(node_id, action, outcome, started)

    def do_POST(self) -> None:
        started = time.monotonic()
        node_id = "-"
        action = urlsplit(self.path).path
        outcome = "error"
        try:
            if self.is_admin:
                self._admin_post(urlsplit(self.path))
            else:
                node_id = self._node_id()
                if action == "/api/v1/checkin":
                    body = validate_checkin(_parse_json(self._read_body(2048)))
                    response = self.app.process_checkin(
                        node_id, body, self._token(), self.client_address[0]
                    )
                    self._send(200, response, "text/plain; charset=utf-8")
                elif action == "/api/v1/result":
                    self._node_result(node_id, urlsplit(self.path))
                else:
                    raise BeaconError(404, "not found")
            outcome = "ok"
        except BeaconError as exc:
            outcome = f"http_{exc.status}"
            self._error(exc)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError) as exc:
            outcome = f"io_{type(exc).__name__}"
        except Exception:
            logging.exception("POST handler failed")
            outcome = "internal_error"
            self._error(BeaconError(500, "internal error"))
        finally:
            self.app.log(node_id, action, outcome, started)

    def _node_result(self, node_id: str, parsed: Any) -> None:
        self.app.authenticate(node_id, self._token())
        query = parse_qs(parsed.query, strict_parsing=True)
        try:
            cmd_id = int(query.get("cmd", [""])[0])
        except (ValueError, IndexError) as exc:
            raise BeaconError(400, "invalid cmd") from exc
        if cmd_id <= 0:
            raise BeaconError(400, "invalid cmd")
        command = self.app.store.get_command(cmd_id)
        if command is None or command["node_id"] != node_id:
            raise BeaconError(404, "unknown command")
        if command["state"] in TERMINAL_STATES and self.app.store.has_result(cmd_id):
            self._send(200, b"dup", "text/plain; charset=utf-8")
            return

        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        received = time.time()
        if content_type == "image/jpeg":
            if command["type"] != "image":
                raise BeaconError(404, "result type does not match command")
            image_data = self._read_body(int(self.app.config["max_image_bytes"]))
            size = len(image_data)
            dimensions = jpeg_dimensions(image_data)
            if dimensions is None:
                raise BeaconError(400, "invalid JPEG")
            warm_ms = self.headers.get("X-Warm-Ms")
            try:
                warm_value = int(warm_ms) if warm_ms is not None else None
            except ValueError as exc:
                raise BeaconError(400, "invalid X-Warm-Ms") from exc
            if warm_value is not None and not 0 <= warm_value <= 600000:
                raise BeaconError(400, "invalid X-Warm-Ms")
            stamp = datetime.fromtimestamp(received, timezone.utc).strftime("%Y%m%d-%H%M%S")
            directory = self.app.images_dir / node_id
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / f"{stamp}_{cmd_id}.jpg"
            temporary = destination.with_suffix(".jpg.tmp")
            temporary.write_bytes(image_data)
            os.replace(temporary, destination)
            result = self.app.store.save_image(
                node_id, cmd_id, received, str(destination), size,
                dimensions[0], dimensions[1], warm_value,
            )
            if result != "inserted":
                destination.unlink(missing_ok=True)
            self._finish_result_response(result)
            return

        if content_type != "application/json":
            raise BeaconError(415, "unsupported result content type")
        if command["type"] == "image" and command["state"] == "dispatched":
            # Camera initialization/capture errors are JSON results for image commands.
            pass
        elif command["type"] == "image":
            raise BeaconError(404, "image command is not dispatched")
        elif command["type"] not in {"sensor", "config", "hibernate"}:
            raise BeaconError(404, "result type does not match command")
        result_body = _parse_json(self._read_body(2048))
        if not isinstance(result_body, dict) or result_body.get("ok") not in (0, 1, False, True):
            raise BeaconError(400, "invalid result JSON")
        result = self.app.store.save_reading(node_id, cmd_id, received, result_body)
        self._finish_result_response(result)

    def _finish_result_response(self, result: str) -> None:
        if result == "not_found":
            raise BeaconError(404, "unknown command")
        with self.app.results_condition:
            self.app.results_condition.notify_all()
        # Wake a session poller for the node that owns this result.
        self._send(200, b"dup" if result == "dup" else b"ok", "text/plain; charset=utf-8")

    def _admin_get(self, parsed: Any) -> None:
        path = parsed.path
        if path == "/admin/nodes":
            self._send_json(200, [self.app._safe_node(node) for node in self.app.store.list_nodes()])
            return
        match = re.fullmatch(r"/admin/nodes/(tc-[0-9a-f]{6})/energy", path)
        if match:
            result = self.app.energy_report(match.group(1))
            if result is None:
                raise BeaconError(404, "unknown node")
            self._send_json(200, result)
            return
        match = re.fullmatch(r"/admin/commands/(\d+)(/wait)?", path)
        if match:
            cmd_id = int(match.group(1))
            if match.group(2):
                query = parse_qs(parsed.query)
                try:
                    wait_s = int(query.get("timeout", ["600"])[0])
                except ValueError as exc:
                    raise BeaconError(400, "invalid timeout") from exc
                if not 0 <= wait_s <= 600:
                    raise BeaconError(400, "timeout must be 0..600")
                deadline = time.monotonic() + wait_s
                with self.app.results_condition:
                    while True:
                        command = self.app.store.get_command(cmd_id)
                        if command is None:
                            raise BeaconError(404, "unknown command")
                        if command["state"] in TERMINAL_STATES:
                            self._send_json(200, self.app._command_public(command))
                            return
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            self._send_json(200, self.app._command_public(command))
                            return
                        self.app.results_condition.wait(timeout=remaining)
            command = self.app.store.get_command(cmd_id)
            if command is None:
                raise BeaconError(404, "unknown command")
            self._send_json(200, self.app._command_public(command))
            return
        raise BeaconError(404, "not found")

    def _admin_post(self, parsed: Any) -> None:
        path = parsed.path
        match = re.fullmatch(r"/admin/nodes/(tc-[0-9a-f]{6})/(attach|detach|hibernate|interval|watch|session|commands)", path)
        if not match:
            raise BeaconError(404, "not found")
        node_id, action = match.groups()
        raw_length = self.headers.get("Content-Length")
        body = _parse_json(self._read_body(2048)) if raw_length is not None and raw_length != "0" else {}
        if not isinstance(body, dict):
            raise BeaconError(400, "JSON object required")
        now = time.time()

        if action == "attach":
            interval = body.get("interval_s", self.app.config["default_interval_s"])
            minimum = int(self.app.config["test_min_next_s"]) if self.app.config["test_mode"] else 60
            interval = _int_field(interval, "interval_s", minimum, 14400)
            label = body.get("label")
            if label is not None and (not isinstance(label, str) or len(label) > 64):
                raise BeaconError(400, "invalid label")
            node = self.app.store.attach(node_id, label, interval)
            if node is None:
                raise BeaconError(404, "unknown node")
            self._send_json(200, self.app._safe_node(node))
            self.app.notify_node(node_id)
            return

        if action == "detach":
            if not self.app.store.detach(node_id, now):
                raise BeaconError(404, "unknown node")
            self.app.start_session(node_id, 0)
            self.app.notify_node(node_id)
            self._send_json(200, {"node_id": node_id, "state": "DETACHED"})
            return

        node = self.app.store.get_node(node_id)
        if node is None:
            raise BeaconError(404, "unknown node")
        if node["state"] != "ATTACHED":
            raise BeaconError(409, "node is not ATTACHED")

        if action == "hibernate":
            cmd_id = self.app.store.create_command(node_id, "hibernate", {}, now)
            if cmd_id is None:
                raise BeaconError(409, "node is not ATTACHED")
            self.app.notify_node(node_id)
            self._send_json(202, {"cmd_id": cmd_id, "state": "queued"})
            return
        if action == "interval":
            minimum = int(self.app.config["test_min_next_s"]) if self.app.config["test_mode"] else 60
            value = _int_field(body.get("interval_s"), "interval_s", minimum, 14400)
            if not self.app.store.set_interval(node_id, value):
                raise BeaconError(409, "node is not ATTACHED")
            self.app.notify_node(node_id)
            self._send_json(200, {"node_id": node_id, "interval_s": value})
            return
        if action == "watch":
            minutes = _int_field(body.get("minutes"), "minutes", 1, 30)
            until = now + minutes * 60
            if not self.app.store.set_watch(node_id, until):
                raise BeaconError(409, "node is not ATTACHED")
            self._send_json(200, {"node_id": node_id, "watch_until": until})
            return
        if action == "session":
            hold_s = _int_field(body.get("hold_s"), "hold_s", 0, 180)
            if not self.app.store.set_session(node_id, hold_s):
                raise BeaconError(409, "node is not ATTACHED")
            if hold_s == 0:
                self.app.start_session(node_id, 0)
            self.app.notify_node(node_id)
            self._send_json(200, {"node_id": node_id, "hold_s": hold_s})
            return
        if action == "commands":
            command_type = body.get("type")
            params = body.get("params", {})
            if command_type not in COMMAND_TYPES or not isinstance(params, dict):
                raise BeaconError(400, "invalid command")
            clean_params: dict[str, Any] = {}
            if command_type == "image":
                fs = params.get("fs", "VGA")
                q = params.get("q", 12)
                warm = params.get("warm", 500)
                if fs not in IMAGE_SIZES:
                    raise BeaconError(400, "invalid image fs")
                clean_params = {
                    "fs": fs,
                    "q": _int_field(q, "q", 4, 40),
                    "warm": _int_field(warm, "warm", 0, 3000),
                }
            elif command_type == "config":
                if set(params) - {"fast"}:
                    raise BeaconError(400, "only config fast is supported")
                if "fast" in params:
                    clean_params["fast"] = _int_field(params["fast"], "fast", 0, 1)
            elif params:
                raise BeaconError(400, f"{command_type} command takes no parameters")
            cmd_id = self.app.store.create_command(node_id, command_type, clean_params, now)
            if cmd_id is None:
                raise BeaconError(409, "node is not ATTACHED")
            self.app.notify_node(node_id)
            self._send_json(202, {"cmd_id": cmd_id, "state": "queued"})
            return

        raise BeaconError(404, "not found")


def make_server(host: str, port: int, app: BeaconApplication, is_admin: bool) -> ThreadingHTTPServer:
    handler = type(
        "AdminHandler" if is_admin else "NodeHandler",
        (BeaconRequestHandler,),
        {"app": app, "is_admin": is_admin},
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.allow_reuse_address = True
    return server


def serve(config_path: str) -> int:
    config = load_config(config_path)
    app = BeaconApplication(config)
    node_server = make_server("0.0.0.0", config["node_port"], app, False)
    admin_server = make_server("127.0.0.1", config["admin_port"], app, True)
    servers = (node_server, admin_server)
    threads = [
        threading.Thread(target=server.serve_forever, name=f"beacon-{server.server_port}", daemon=True)
        for server in servers
    ]
    for thread in threads:
        thread.start()
    print(
        f"BEACON_READY node=0.0.0.0:{node_server.server_port} "
        f"admin=127.0.0.1:{admin_server.server_port} config={config_path}",
        flush=True,
    )
    stopped = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stopped.set()
        for server in servers:
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, request_stop)
    try:
        stopped.wait()
    except KeyboardInterrupt:
        request_stop(signal.SIGINT, None)
    finally:
        for server in servers:
            server.server_close()
        app.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="server/config.json")
    args = parser.parse_args(argv)
    try:
        return serve(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"beacon-server: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
