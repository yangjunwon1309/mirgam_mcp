#!/usr/bin/env python3
"""Command-line client for the local beacon management API."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(base: str, path: str, method: str = "GET", payload=None, timeout: int = 15):
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(base.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024)
            content_type = response.headers.get("Content-Type", "")
            if "json" in content_type:
                return response.status, json.loads(raw.decode("utf-8"))
            return response.status, raw.decode("utf-8", "replace")
    except HTTPError as exc:
        raw = exc.read(64 * 1024).decode("utf-8", "replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"management API unavailable: {exc.reason}") from exc


def print_value(value):
    print(json.dumps(value, indent=2, ensure_ascii=False) if not isinstance(value, str) else value)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="beaconctl")
    parser.add_argument("--admin-url", default="http://127.0.0.1:8081")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("nodes")

    attach = commands.add_parser("attach")
    attach.add_argument("node_id")
    attach.add_argument("--label")
    attach.add_argument("--interval", type=int)

    for name in ("detach", "hibernate", "energy"):
        item = commands.add_parser(name)
        item.add_argument("node_id")

    interval = commands.add_parser("interval")
    interval.add_argument("node_id")
    interval.add_argument("seconds", type=int)

    watch = commands.add_parser("watch")
    watch.add_argument("node_id")
    watch.add_argument("--minutes", type=int, required=True)

    session = commands.add_parser("session")
    session.add_argument("node_id")
    session.add_argument("--hold", type=int, required=True)

    sensor = commands.add_parser("sensor")
    sensor.add_argument("node_id")
    sensor.add_argument("--wait", action="store_true")

    image = commands.add_parser("image")
    image.add_argument("node_id")
    image.add_argument("--fs", default="VGA")
    image.add_argument("--q", type=int, default=12)
    image.add_argument("--warm", type=int, default=500)
    image.add_argument("--wait", action="store_true")

    get_cmd = commands.add_parser("cmd")
    get_cmd.add_argument("cmd_id", type=int)

    args = parser.parse_args(argv)
    base = args.admin_url
    try:
        if args.action == "nodes":
            _, value = request_json(base, "/admin/nodes")
        elif args.action == "attach":
            payload = {}
            if args.label is not None:
                payload["label"] = args.label
            if args.interval is not None:
                payload["interval_s"] = args.interval
            _, value = request_json(base, f"/admin/nodes/{args.node_id}/attach", "POST", payload)
        elif args.action == "detach":
            _, value = request_json(base, f"/admin/nodes/{args.node_id}/detach", "POST", {})
        elif args.action == "hibernate":
            _, queued = request_json(base, f"/admin/nodes/{args.node_id}/hibernate", "POST", {})
            if queued.get("cmd_id"):
                _, value = request_json(base, f"/admin/commands/{queued['cmd_id']}")
                value["queued"] = queued
            else:
                value = queued
        elif args.action == "interval":
            _, value = request_json(
                base, f"/admin/nodes/{args.node_id}/interval", "POST",
                {"interval_s": args.seconds},
            )
        elif args.action == "watch":
            _, value = request_json(
                base, f"/admin/nodes/{args.node_id}/watch", "POST",
                {"minutes": args.minutes},
            )
        elif args.action == "session":
            _, value = request_json(
                base, f"/admin/nodes/{args.node_id}/session", "POST",
                {"hold_s": args.hold},
            )
        elif args.action in {"sensor", "image"}:
            params = {}
            if args.action == "image":
                params = {"fs": args.fs, "q": args.q, "warm": args.warm}
            _, queued = request_json(
                base, f"/admin/nodes/{args.node_id}/commands", "POST",
                {"type": args.action, "params": params},
            )
            if args.wait and queued.get("cmd_id"):
                _, value = request_json(
                    base, f"/admin/commands/{queued['cmd_id']}/wait?timeout=600", timeout=610
                )
            else:
                value = queued
        elif args.action == "cmd":
            _, value = request_json(base, f"/admin/commands/{args.cmd_id}")
        elif args.action == "energy":
            _, value = request_json(base, f"/admin/nodes/{args.node_id}/energy")
        else:
            parser.error("unsupported command")
        print_value(value)
        if isinstance(value, dict) and value.get("state") in {"failed", "expired"}:
            return 1
        return 0
    except RuntimeError as exc:
        print(f"beaconctl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
