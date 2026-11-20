"""BFF client and low-rate collector for the loopback Beacon admin API."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from .beacon_store import BeaconStore


logger = logging.getLogger(__name__)
NODE_ID_PATTERN = re.compile(r"^tc-[0-9a-f]{6}$")
IMAGE_NAME_PATTERN = re.compile(r"^\d{8}-\d{6}_(\d+)\.jpg$")
ALLOWED_ACTIONS = {"detach", "watch", "session", "hibernate"}
ALLOWED_COMMANDS = {"sensor", "image"}
TERMINAL = {"done", "failed", "expired"}


class BeaconUnavailable(RuntimeError):
    pass


class BeaconAdminClient:
    def __init__(self, base_url: str):
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(connect=2.5, read=4.0, write=4.0, pool=2.0),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        try:
            response = await self.client.request(method, path, json=json_body)
        except httpx.RequestError as exc:
            raise BeaconUnavailable(f"Beacon 관리 서버에 연결할 수 없습니다 ({type(exc).__name__}).") from None
        if not response.is_success:
            try:
                detail = response.json().get("error")
            except (ValueError, AttributeError):
                detail = None
            message = str(detail)[:180] if detail else f"HTTP {response.status_code}"
            raise BeaconUnavailable(f"Beacon 관리 서버 응답 오류: {message}")
        if response.status_code == 204:
            return None
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            raise BeaconUnavailable("Beacon 관리 서버가 JSON이 아닌 응답을 반환했습니다.")
        try:
            return response.json()
        except ValueError:
            raise BeaconUnavailable("Beacon 관리 서버의 JSON 응답을 읽지 못했습니다.") from None

    async def list_nodes(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/admin/nodes")
        if not isinstance(payload, list):
            raise BeaconUnavailable("Beacon 노드 목록 형식이 올바르지 않습니다.")
        return [node for node in payload if isinstance(node, dict) and NODE_ID_PATTERN.fullmatch(str(node.get("id", "")))]

    async def node(self, node_id: str, nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not NODE_ID_PATTERN.fullmatch(node_id):
            raise ValueError("잘못된 beacon ID입니다.")
        for node in nodes if nodes is not None else await self.list_nodes():
            if node.get("id") == node_id:
                return node
        raise KeyError(node_id)

    async def post(self, node_id: str, action: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not NODE_ID_PATTERN.fullmatch(node_id):
            raise ValueError("잘못된 beacon ID입니다.")
        result = await self._request("POST", f"/admin/nodes/{node_id}/{action}", json_body=body or {})
        return result if isinstance(result, dict) else {}

    async def command(self, node_id: str, command_type: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if command_type not in ALLOWED_COMMANDS:
            raise ValueError("대시보드에서는 sensor 또는 image 명령만 요청할 수 있습니다.")
        return await self.post(node_id, "commands", {"type": command_type, "params": params or {}})

    async def get_command(self, command_id: int) -> dict[str, Any]:
        result = await self._request("GET", f"/admin/commands/{int(command_id)}")
        if not isinstance(result, dict):
            raise BeaconUnavailable("Beacon 명령 결과 형식이 올바르지 않습니다.")
        return result

    async def energy(self, node_id: str) -> dict[str, Any]:
        if not NODE_ID_PATTERN.fullmatch(node_id):
            raise ValueError("잘못된 beacon ID입니다.")
        result = await self._request("GET", f"/admin/nodes/{node_id}/energy")
        return result if isinstance(result, dict) else {}

    async def usb_ports(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "/admin/usb/ports")
        ports = result.get("ports") if isinstance(result, dict) else None
        if not isinstance(ports, list):
            raise BeaconUnavailable("Beacon USB 포트 목록 형식이 올바르지 않습니다.")
        return [port for port in ports if isinstance(port, dict)]

    async def reset_usb_port(self, port_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"tty(?:USB|ACM)\d+", port_id):
            raise ValueError("지원하지 않는 USB 직렬 포트입니다.")
        result = await self._request("POST", f"/admin/usb/{port_id}/reset", json_body={})
        return result if isinstance(result, dict) else {}


class BeaconController:
    def __init__(self, client: BeaconAdminClient, store: BeaconStore,
                 image_source_root: str | Path, data_root: str | Path,
                 poll_interval_seconds: int = 5):
        self.client = client
        self.store = store
        self.image_source_root = Path(image_source_root).resolve()
        self.data_root = Path(data_root).resolve()
        self.poll_interval_seconds = max(3, min(int(poll_interval_seconds), 60))
        self._remote_lock = asyncio.Lock()
        self._last_warning_at = 0.0

    async def list_nodes(self, account_id: int) -> dict[str, Any]:
        async with self._remote_lock:
            nodes = await self.client.list_nodes()
        summaries = self.store.update_node_snapshot(account_id, nodes)
        seen = {node["node_id"] for node in summaries}
        summaries.extend(node for node in self.store.cached_nodes(account_id) if node["node_id"] not in seen)
        return {"reachable": True, "nodes": summaries}

    async def configure(self, account_id: int, node_id: str, farm_id: str | None,
                        metadata: dict[str, Any], interval_s: int, requested_data: list[str],
                        attach: bool = True) -> dict[str, Any]:
        profile = self.store.save_profile(account_id, node_id, farm_id, metadata, interval_s, requested_data)
        if not attach:
            return {"profile": profile, "node": await self.node_summary(account_id, node_id)}
        async with self._remote_lock:
            nodes = await self.client.list_nodes()
            node = await self.client.node(node_id, nodes)
            if node.get("state") == "ATTACHED":
                await self.client.post(node_id, "interval", {"interval_s": interval_s})
                remote = node
            else:
                remote = await self.client.post(node_id, "attach", {
                    "label": profile["label"], "interval_s": interval_s,
                })
        return {"profile": profile, "node": self.store.update_node_snapshot(account_id, [remote])[0]}

    async def node_summary(self, account_id: int, node_id: str) -> dict[str, Any]:
        async with self._remote_lock:
            nodes = await self.client.list_nodes()
        summary = self.store.update_node_snapshot(account_id, nodes)
        item = next((node for node in summary if node["node_id"] == node_id), None)
        if item is None:
            item = next((node for node in self.store.cached_nodes(account_id) if node["node_id"] == node_id), None)
        if item is None:
            raise KeyError(node_id)
        return item

    async def action(self, account_id: int, node_id: str, action: str,
                     payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS and action != "interval":
            raise ValueError("지원하지 않는 beacon 관리 작업입니다.")
        if self.store.profile(account_id, node_id) is None:
            raise KeyError(node_id)
        async with self._remote_lock:
            return await self.client.post(node_id, action, payload or {})

    async def command(self, account_id: int, node_id: str, command_type: str,
                     params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.store.profile(account_id, node_id) is None:
            raise KeyError(node_id)
        async with self._remote_lock:
            remote = await self.client.command(node_id, command_type, params)
        command_id = remote.get("cmd_id")
        if not isinstance(command_id, int):
            raise BeaconUnavailable("Beacon 서버가 명령 ID를 반환하지 않았습니다.")
        self.store.record_command(account_id, node_id, command_type, params or {}, remote)
        return {"node_id": node_id, "command_id": command_id, "state": remote.get("state", "queued")}

    async def energy(self, account_id: int, node_id: str) -> dict[str, Any]:
        if self.store.profile(account_id, node_id) is None:
            raise KeyError(node_id)
        async with self._remote_lock:
            return await self.client.energy(node_id)

    async def usb_ports(self) -> list[dict[str, Any]]:
        async with self._remote_lock:
            return await self.client.usb_ports()

    async def reset_usb_port(self, port_id: str) -> dict[str, Any]:
        async with self._remote_lock:
            return await self.client.reset_usb_port(port_id)

    async def poll_once(self) -> None:
        try:
            async with self._remote_lock:
                nodes = await self.client.list_nodes()
            remote_by_id = {str(node["id"]): node for node in nodes}
            for pending in self.store.pending_commands():
                remote = await self.client.get_command(int(pending["command_id"]))
                if remote.get("node_id") != pending["node_id"]:
                    continue
                result = remote.get("result")
                if remote.get("state") == "done" and isinstance(result, dict) and result.get("kind") == "image":
                    local_file = self._copy_image_result(pending["node_id"], int(pending["command_id"]), result)
                    if local_file:
                        result = {**result, "local_file_path": str(local_file)}
                        remote = {**remote, "result": result}
                self.store.record_remote_command(remote)

            wall_now = time.time()
            for profile in self.store.due_collections(wall_now):
                node = remote_by_id.get(profile["node_id"])
                interval = max(60, int(profile.get("interval_s") or 300))
                if not node or node.get("state") != "ATTACHED" or not node.get("online"):
                    self.store.postpone_collection(profile["node_id"], wall_now, min(interval, 300))
                    continue
                # Reserve the next slot before creating commands to prevent an API
                # request and the background poller from scheduling duplicates.
                self.store.postpone_collection(profile["node_id"], wall_now, interval)
                for kind in profile.get("requested_data", []):
                    if kind not in ALLOWED_COMMANDS:
                        continue
                    params = {"fs": "VGA", "q": 12, "warm": 500} if kind == "image" else {}
                    try:
                        async with self._remote_lock:
                            command = await self.client.command(profile["node_id"], kind, params)
                        if isinstance(command.get("cmd_id"), int):
                            self.store.record_command(int(profile["account_id"]), profile["node_id"], kind, params, command)
                    except (BeaconUnavailable, ValueError):
                        self.store.postpone_collection(profile["node_id"], wall_now, 60)
                        break
        except BeaconUnavailable as exc:
            if time.monotonic() - self._last_warning_at > 60:
                logger.warning("Beacon collector cannot reach admin API (%s)", str(exc)[:160])
                self._last_warning_at = time.monotonic()
        except Exception:
            logger.exception("Beacon collector cycle failed; it will retry")

    async def run(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self.poll_interval_seconds)

    def _copy_image_result(self, node_id: str, command_id: int, result: dict[str, Any]) -> Path | None:
        reported = result.get("path")
        if not isinstance(reported, str) or not NODE_ID_PATTERN.fullmatch(node_id):
            return None
        filename = PurePosixPath(reported.replace("\\", "/")).name
        match = IMAGE_NAME_PATTERN.fullmatch(filename)
        if not match or int(match.group(1)) != command_id:
            logger.warning("Beacon image result has unexpected file name (node=%s, command=%s)", node_id, command_id)
            return None
        source = (self.image_source_root / node_id / filename).resolve()
        if self.image_source_root not in source.parents or not source.is_file():
            return None
        try:
            size = source.stat().st_size
            if size <= 0 or size > 2 * 1024 * 1024:
                return None
            with source.open("rb") as handle:
                if handle.read(2) != b"\xff\xd8":
                    return None
                handle.seek(-2, 2)
                if handle.read(2) != b"\xff\xd9":
                    return None
            destination = self.data_root / "raw" / "beacons" / node_id / f"{command_id}.jpg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".jpg.tmp")
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
            result["local_file_path"] = str(destination)
            result["bytes"] = size
            return destination
        except OSError as exc:
            logger.warning("Could not mirror Beacon JPEG (%s)", type(exc).__name__)
            return None
