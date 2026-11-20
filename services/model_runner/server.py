#!/usr/bin/env python3
"""Docker-reachable local inference gateway with a single serialized worker.

Each request runs exactly one model in a child process. The process exits after
the call, releasing TensorRT/CUDA or PyTorch CPU allocations before the next job.
HTTPServer handles one request at a time, so the two models never execute together.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import struct
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STORAGE_ROOT = Path(os.getenv("MODEL_STORAGE_ROOT", ROOT / "storage")).resolve()
RTMDET_DIR = Path(os.getenv("RTMDET_MODEL_DIR", ROOT / ".local/models/rtmdet-tiny")).resolve()
TIMESTRAL_DIR = Path(os.getenv("TIMESTRAL_MODEL_DIR", ROOT / ".local/models/timestral-28m")).resolve()
RTMDET_ENGINE = Path(os.getenv(
    "RTMDET_ENGINE_PATH",
    RTMDET_DIR / "rtmdet-tiny-coco-fp16-ws64.engine",
)).resolve()
RTMDET_SCRIPT = Path(__file__).with_name("infer_rtmdet.py")
TIMESTRAL_SCRIPT = Path(__file__).with_name("forecast_timestral.py")


class InferenceOutOfMemoryError(RuntimeError):
    """Raised when a CUDA child cannot allocate shared Jetson memory."""


def docker_bridge_address(interface: str = "docker0") -> str:
    """Bind only to the Docker host-gateway interface, not the farm LAN."""
    request = struct.pack("256s", interface[:15].encode("ascii"))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        response = fcntl.ioctl(sock.fileno(), 0x8915, request)  # SIOCGIFADDR
    return socket.inet_ntoa(response[20:24])


def safe_image_path(relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path or Path(relative_path).is_absolute():
        raise ValueError("image path must be a relative camera asset path")
    candidate = (STORAGE_ROOT / relative_path).resolve()
    if STORAGE_ROOT not in candidate.parents or not candidate.is_file():
        raise FileNotFoundError("camera image is not present under the configured storage directory")
    return candidate


def _run_json(command: list[str], request: dict[str, object], *, timeout: int = 90) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "HF_HUB_OFFLINE": "1"},
    )
    if completed.returncode != 0:
        full_detail = completed.stderr.strip() or completed.stdout.strip()
        detail = full_detail[-1200:]
        memory_failure_markers = (
            "NvMapMemAllocInternalTagged",
            "cudaMalloc failed",
            "CUDA error: out of memory",
            "CUDA_ERROR_OUT_OF_MEMORY",
            "cuMemCreate",
        )
        if any(marker in full_detail for marker in memory_failure_markers):
            raise InferenceOutOfMemoryError(
                f"CUDA/NvMap shared-memory allocation failed (child exit {completed.returncode})"
            )
        raise RuntimeError(f"inference process exited with {completed.returncode}: {detail}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("inference process returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("inference process returned an unexpected JSON value")
    return value


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("model-runner: " + format % args + "\n")

    def _write_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._write_json(404, {"ok": False, "error": "not_found"})
            return
        self._write_json(200, {
            "ok": True,
            "service": "serialized-local-model-runner",
            "rtmdet_engine_available": RTMDET_ENGINE.is_file(),
            "timestral_cache_available": (TIMESTRAL_DIR / "hf-cache").is_dir(),
            "execution": "single request; subprocess exits after every inference",
        })

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/v1/detect", "/v1/forecast"}:
            self._write_json(404, {"ok": False, "error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("request body must be between 1 byte and 1 MB")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")

            if self.path == "/v1/detect":
                image = safe_image_path(body.get("image_relative_path"))
                request: dict[str, object] = {
                    "image_path": str(image),
                    "confidence_threshold": body.get("confidence_threshold", 0.30),
                    "classes": body.get("classes"),
                    "max_detections": body.get("max_detections", 100),
                }
                result = _run_json(
                    [sys.executable, str(RTMDET_SCRIPT)],
                    request,
                    timeout=60,
                )
            else:
                values = body.get("values")
                horizon = int(body.get("horizon", 24))
                if not isinstance(values, list) or len(values) < 16 or len(values) > 2880:
                    raise ValueError("forecast values must contain 16 to 2880 regularized samples")
                if not 1 <= horizon <= 48:
                    raise ValueError("forecast horizon must be between 1 and 48")
                request = {
                    "values": values,
                    "horizon": horizon,
                    "cache_dir": str(TIMESTRAL_DIR / "hf-cache"),
                }
                result = _run_json(
                    [str(TIMESTRAL_DIR / "venv/bin/python"), str(TIMESTRAL_SCRIPT)],
                    request,
                    timeout=120,
                )
            self._write_json(200, result)
        except (ValueError, FileNotFoundError) as exc:
            self._write_json(400, {"ok": False, "error": "invalid_request", "detail": str(exc)[:300]})
        except subprocess.TimeoutExpired:
            self._write_json(504, {"ok": False, "error": "inference_timeout"})
        except InferenceOutOfMemoryError as exc:
            self._write_json(503, {
                "ok": False,
                "error": "cuda_out_of_memory",
                "detail": (
                    f"{exc}. Jetson RAM is shared by CUDA, Gemma, Docker, and desktop processes; "
                    "reduce the Gemma context/batch or close memory-heavy processes before retrying."
                ),
            })
        except Exception as exc:
            self._write_json(503, {"ok": False, "error": "inference_failed", "detail": str(exc)[:500]})


def main() -> None:
    host = os.getenv("MODEL_RUNNER_BIND_HOST") or docker_bridge_address()
    port = int(os.getenv("MODEL_RUNNER_PORT", "8766"))
    server = HTTPServer((host, port), Handler)
    print(f"Serialized model runner listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
