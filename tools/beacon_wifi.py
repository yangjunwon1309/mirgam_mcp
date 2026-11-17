#!/usr/bin/env python3
"""Interactively update beacon Wi-Fi credentials and server host, then compile.

Credentials are read only from the user's terminal, never from CLI arguments,
and are not printed. This tool does not upload firmware to the board.
"""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware" / "beacon_node"
SECRETS = SKETCH / "secrets.h"
CONFIG = SKETCH / "config.h"
BUILD = ROOT / "firmware" / "build"
RESULTS = ROOT / "results"
BUILD_LOG = RESULTS / "wifi_rebuild.log"
ARDUINO_CLI = Path("/home/nano/bin/arduino-cli")
FQBN = "esp32:esp32:m5stack_timer_cam:PSRAM=enabled,UploadSpeed=500000"


def c_string_body(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("SSID/password must not contain control characters")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def redact_build_output(output: str, ssid: str, password: str) -> str:
    for secret in (ssid, password, c_string_body(ssid), c_string_body(password)):
        if secret:
            output = output.replace(secret, "<redacted>")
    return output


def ask_credentials() -> tuple[str, str]:
    ssid = input("New 2.4 GHz Wi-Fi SSID: ")
    if not ssid or len(ssid.encode("utf-8")) > 32:
        raise ValueError("SSID must contain 1..32 UTF-8 bytes")
    if re.search(r"(?:_|-)5g(?:hz)?$", ssid, re.IGNORECASE):
        answer = input("SSID name suggests 5 GHz. Confirm this same SSID is also available on 2.4 GHz? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            raise ValueError("choose the router's 2.4 GHz SSID; ESP32 Timer Camera cannot connect to 5 GHz")
    c_string_body(ssid)
    password = getpass.getpass("New Wi-Fi password (hidden): ")
    password_bytes = password.encode("utf-8")
    if password and not (8 <= len(password_bytes) <= 63 or re.fullmatch(r"[0-9A-Fa-f]{64}", password)):
        raise ValueError("password must be empty for an open network, 8..63 bytes, or a 64-digit hexadecimal key")
    c_string_body(password)
    return ssid, password


def ask_server_host(argument: str | None) -> str:
    value = argument if argument is not None else input("Jetson Wi-Fi IPv4 address (SERVER_HOST): ").strip()
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as exc:
        raise ValueError("SERVER_HOST must be a valid IPv4 address") from exc


def updated_config_text(host: str) -> str:
    text = CONFIG.read_text(encoding="utf-8")
    updated, replacements = re.subn(
        r'(?m)^#define SERVER_HOST "[^"\r\n]*"\s*$',
        f'#define SERVER_HOST "{host}"',
        text,
    )
    if replacements != 1:
        raise ValueError("config.h must contain exactly one SERVER_HOST definition")
    return updated


def write_secrets_atomic(text: str) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=".secrets.h.", dir=SECRETS.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp_name, SECRETS)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def run_compile(ssid: str, password: str) -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    command = [
        "/usr/bin/timeout", "300", str(ARDUINO_CLI), "compile", "--fqbn", FQBN,
        "--output-dir", str(BUILD), str(SKETCH),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=310,
            check=False,
        )
        output = redact_build_output(completed.stdout or "", ssid, password)
        BUILD_LOG.write_text(output, encoding="utf-8")
        print(f"compile exit={completed.returncode}; log={BUILD_LOG}")
        for line in output.splitlines():
            if line.startswith("Sketch uses ") or line.startswith("Global variables use "):
                print(line)
        return completed.returncode
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        BUILD_LOG.write_text(redact_build_output(partial, ssid, password), encoding="utf-8")
        print(f"compile timed out; log={BUILD_LOG}", file=sys.stderr)
        return 124
    except OSError as exc:
        print(f"cannot run arduino-cli: {exc}; credentials were written; log={BUILD_LOG}", file=sys.stderr)
        return 127


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Example: beacon_wifi.py --server-host 192.168.219.123; then enter the 2.4 GHz SSID and password at the prompts.",
    )
    parser.add_argument(
        "--server-host",
        help="Jetson's current Wi-Fi IPv4 address; prompt if omitted",
    )
    args = parser.parse_args(argv)

    try:
        if not CONFIG.is_file():
            raise ValueError("firmware/beacon_node/config.h is missing")
        if not ARDUINO_CLI.is_file():
            raise ValueError("/home/nano/bin/arduino-cli is missing")

        # Validate the non-secret host before prompting for or replacing credentials.
        host = ask_server_host(args.server_host)
        if SECRETS.exists():
            answer = input("Replace existing Wi-Fi credentials in secrets.h? [y/N]: ").strip().lower()
            if answer not in {"y", "yes"}:
                print("cancelled; no files changed")
                return 1

        ssid, password = ask_credentials()
        config_text = updated_config_text(host)
        secret_text = (
            "#pragma once\n"
            f'#define WIFI_SSID "{c_string_body(ssid)}"\n'
            f'#define WIFI_PASS "{c_string_body(password)}"\n'
        )
        write_secrets_atomic(secret_text)
        CONFIG.write_text(config_text, encoding="utf-8")
        print("Wi-Fi credentials and SERVER_HOST updated; credential values were not displayed.")
        compile_rc = run_compile(ssid, password)
        if compile_rc == 0:
            print("Build ready. On the Jetson host, run: bash /home/nano/beacon/firmware/flash.sh")
        return compile_rc
    except UnicodeDecodeError:
        print("beacon_wifi: terminal input was not valid UTF-8; use a UTF-8 terminal and retry. No credentials were written.", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"beacon_wifi: {exc}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("\nbeacon_wifi: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
