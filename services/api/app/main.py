"""FastAPI entry point for SQLite-backed chat and MCP tool orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from openai import APIConnectionError, APIStatusError

from .config import get_settings
from .farmmap.router import create_router
from .farmmap.store import FarmMapStore
from .farmmap.vworld import VWorldClient
from .schemas import (
    AuthenticatedUser, BeaconActionRequest, BeaconCommandRequest, BeaconConfigureRequest,
    BeaconIntervalRequest, ChatRequest, ChatResponse, LoginRequest, Message, Thread, ThreadDocument,
)
from .services.agent import MCPUnavailableError, ProgressCallback, reply_with_tools
from .services.beacon import BeaconAdminClient, BeaconController, BeaconUnavailable
from .services.beacon_store import BeaconStore
from .services.gemma import ContextWindowError, EmptyModelResponseError, GemmaClient
from .services.mirgam_accounts import (
    AccountDatabaseNotConfigured,
    AccountDatabaseUnavailable,
    MirgamAccountVerifier,
)
from .services.mcp_client import MCPClient
from .services.sqlite_store import SQLiteStore


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = SQLiteStore(settings.sqlite_path)
    store.initialize()
    app.state.thread_store = store
    beacon_store = BeaconStore(settings.sqlite_path, settings.data_root)
    beacon_store.initialize()
    app.state.beacon_store = beacon_store
    beacon_client = BeaconAdminClient(settings.beacon_admin_url)
    app.state.beacon = BeaconController(
        beacon_client, beacon_store, settings.beacon_image_dir, settings.data_root,
        settings.beacon_poll_interval_seconds,
    )
    farmmap_store = FarmMapStore(settings.sqlite_path, settings.data_root)
    farmmap_store.initialize()
    app.state.farmmap_store = farmmap_store
    app.state.settings = settings
    # Jetson unified memory is shared by llama.cpp and TensorRT. Keep an entire
    # chat turn atomic so a second dashboard request cannot run Gemma while
    # RTMDet is using GPU memory. Compose runs one API worker, so this
    # process-local lock covers all dashboard chat requests.
    app.state.model_inference_lock = asyncio.Lock()
    vworld_key = settings.vworld_key.get_secret_value() if settings.vworld_key else None
    app.state.vworld = VWorldClient(
        key=vworld_key,
        domain=settings.vworld_domain,
        store=farmmap_store,
        data_root=settings.data_root,
        tile_ttl_days=settings.tile_ttl_days,
    )
    app.state.gemma = GemmaClient(settings)
    app.state.mcp = MCPClient(settings.mcp_url)
    app.state.mirgam_accounts = MirgamAccountVerifier(settings.mirgam_database_url)
    simulator_task: asyncio.Task[None] | None = None
    beacon_task = asyncio.create_task(app.state.beacon.run())
    if settings.demo_simulator_enabled:
        async def simulate_demo_telemetry() -> None:
            while True:
                await asyncio.sleep(max(5, settings.demo_simulator_interval_seconds))
                try:
                    inserted = await asyncio.to_thread(store.append_demo_live_readings)
                    if inserted:
                        logger.debug("Appended %d demo sensor readings", inserted)
                except Exception:
                    logger.exception("Demo sensor simulator tick failed; it will retry")
        simulator_task = asyncio.create_task(simulate_demo_telemetry())
    try:
        yield
    finally:
        if simulator_task:
            simulator_task.cancel()
            try:
                await simulator_task
            except asyncio.CancelledError:
                pass
        beacon_task.cancel()
        try:
            await beacon_task
        except asyncio.CancelledError:
            pass
        await beacon_client.close()
        await app.state.gemma.client.close()
        app.state.mirgam_accounts.close()
        await app.state.vworld.close()


app = FastAPI(title="gemma-mcp-api", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_private_response_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/health" and not response.headers.get("cache-control"):
        response.headers["Cache-Control"] = "private, no-store"
    return response


def store(request: Request) -> SQLiteStore:
    return request.app.state.thread_store


def require_session(request: Request) -> AuthenticatedUser:
    settings = get_settings()
    session = store(request).get_auth_session(request.cookies.get(settings.auth_cookie_name))
    if session is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return AuthenticatedUser(**session)


app.include_router(create_router(require_session))


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings = get_settings()
    model_status = await request.app.state.gemma.status()
    mcp_tools = await request.app.state.mcp.list_tools()
    return {
        "status": "ok" if model_status["reachable"] else "degraded",
        "model": settings.gemma_model,
        "mcp_url": settings.mcp_url,
        "mcp": {"reachable": bool(mcp_tools), "tool_count": len(mcp_tools)},
        "llama": model_status,
    }


@app.post("/auth/login", response_model=AuthenticatedUser)
async def login(payload: LoginRequest, request: Request, response: Response) -> AuthenticatedUser:
    settings = get_settings()
    verifier: MirgamAccountVerifier = request.app.state.mirgam_accounts
    try:
        account = await asyncio.to_thread(
            verifier.verify, payload.identifier, payload.password.get_secret_value()
        )
    except AccountDatabaseNotConfigured as exc:
        raise HTTPException(
            status_code=503,
            detail="로그인 서비스가 설정되지 않았습니다. 서버의 MIRGAM_DATABASE_URL 설정을 확인해 주세요.",
        ) from exc
    except AccountDatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="계정 확인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc
    if account is None:
        raise HTTPException(status_code=401, detail="농장명 또는 사용자 ID와 비밀번호를 확인해 주세요.")

    token = await asyncio.to_thread(
        store(request).create_auth_session,
        account["account_id"],
        account["farm_name"],
        account["username"],
        settings.auth_session_ttl_seconds,
    )
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=max(60, settings.auth_session_ttl_seconds),
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    return AuthenticatedUser(**account)


@app.get("/auth/me", response_model=AuthenticatedUser)
async def authenticated_user(user: AuthenticatedUser = Depends(require_session)) -> AuthenticatedUser:
    return user


@app.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    settings = get_settings()
    token = request.cookies.get(settings.auth_cookie_name)
    await asyncio.to_thread(store(request).revoke_auth_session, token)
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"status": "ok"}


@app.get("/threads", response_model=list[Thread], dependencies=[Depends(require_session)])
async def list_threads(request: Request) -> list[Thread]:
    return store(request).list()


@app.get("/threads/{thread_id}", response_model=ThreadDocument, dependencies=[Depends(require_session)])
async def get_thread(thread_id: str, request: Request) -> ThreadDocument:
    try:
        return store(request).load(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Thread not found") from exc


@app.delete("/threads/{thread_id}", status_code=204, dependencies=[Depends(require_session)])
async def delete_thread(thread_id: str, request: Request) -> None:
    store(request).delete(thread_id)


@app.get("/dashboard/sensors", dependencies=[Depends(require_session)])
async def dashboard_sensors(request: Request) -> list[dict[str, object]]:
    return store(request).dashboard_sensors()


@app.get("/dashboard/sensors/{sensor_id}", dependencies=[Depends(require_session)])
async def dashboard_sensor_detail(sensor_id: str, request: Request, hours: int = 24) -> dict[str, object]:
    try:
        return store(request).dashboard_sensor_detail(sensor_id, hours)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Sensor not found") from exc


@app.get("/dashboard/cameras", dependencies=[Depends(require_session)])
async def dashboard_cameras(request: Request) -> list[dict[str, object]]:
    return store(request).dashboard_cameras()


@app.get("/dashboard/cameras/{camera_id}", dependencies=[Depends(require_session)])
async def dashboard_camera_detail(camera_id: str, request: Request) -> dict[str, object]:
    try:
        return store(request).dashboard_camera_detail(camera_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Camera not found") from exc


def _reject_beacon_secrets(value: object) -> None:
    forbidden = {"token", "access_token", "refresh_token", "password", "wifi_password", "ssid", "wifi_ssid",
                 "api_key", "apikey", "secret", "credentials", "authorization"}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in forbidden:
                raise HTTPException(status_code=422, detail="비밀번호·토큰 등 비밀값은 beacon 메타데이터에 저장할 수 없습니다.")
            _reject_beacon_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _reject_beacon_secrets(child)


@app.get("/dashboard/beacons", dependencies=[Depends(require_session)])
async def dashboard_beacons(request: Request, user: AuthenticatedUser = Depends(require_session)) -> dict[str, object]:
    controller: BeaconController = request.app.state.beacon
    try:
        return await controller.list_nodes(user.account_id)
    except BeaconUnavailable as exc:
        logger.info("Beacon list is unavailable (%s)", type(exc).__name__)
        return {"reachable": False, "error": str(exc),
                "nodes": request.app.state.beacon_store.cached_nodes(user.account_id)}


@app.get("/dashboard/beacons/usb", dependencies=[Depends(require_session)])
async def dashboard_beacon_usb(request: Request) -> dict[str, object]:
    try:
        ports = await request.app.state.beacon.usb_ports()
        return {"reachable": True, "ports": ports}
    except BeaconUnavailable as exc:
        return {"reachable": False, "error": str(exc), "ports": []}


@app.post("/dashboard/beacons/usb/{port_id}/reset", dependencies=[Depends(require_session)])
async def dashboard_beacon_usb_reset(port_id: str, request: Request) -> dict[str, object]:
    try:
        return await request.app.state.beacon.reset_usb_port(port_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BeaconUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.get("/dashboard/beacons/{node_id}", dependencies=[Depends(require_session)])
async def dashboard_beacon_detail(
    node_id: str, request: Request, user: AuthenticatedUser = Depends(require_session),
) -> dict[str, object]:
    controller: BeaconController = request.app.state.beacon
    try:
        node = await controller.node_summary(user.account_id, node_id)
        detail = request.app.state.beacon_store.detail(user.account_id, node_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="등록된 beacon을 찾지 못했습니다.") from exc
    except BeaconUnavailable as exc:
        profile = request.app.state.beacon_store.profile(user.account_id, node_id)
        if profile is None:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        node = next((item for item in request.app.state.beacon_store.cached_nodes(user.account_id)
                     if item["node_id"] == node_id), None)
        detail = request.app.state.beacon_store.detail(user.account_id, node_id)
    return {"node": node, **detail}


@app.put("/dashboard/beacons/{node_id}/configure", dependencies=[Depends(require_session)])
async def configure_dashboard_beacon(
    node_id: str, payload: BeaconConfigureRequest, request: Request,
    user: AuthenticatedUser = Depends(require_session),
) -> dict[str, object]:
    _reject_beacon_secrets(payload.metadata.model_dump(mode="json"))
    if not re.fullmatch(r"tc-[0-9a-f]{6}", node_id):
        raise HTTPException(status_code=422, detail="Beacon ID 형식이 올바르지 않습니다.")
    if request.app.state.farmmap_store.get_farm(user.account_id, payload.farm_id) is None:
        raise HTTPException(status_code=404, detail="로그인한 계정의 농장을 찾지 못했습니다.")
    controller: BeaconController = request.app.state.beacon
    try:
        return await controller.configure(
            user.account_id, node_id, payload.farm_id, payload.metadata.model_dump(mode="json"),
            payload.interval_s, payload.requested_data, payload.attach,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="서버에서 확인된 beacon이 아닙니다. 먼저 장치 목록을 새로고침해 주세요.") from exc
    except BeaconUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.post("/dashboard/beacons/{node_id}/actions/{action}", dependencies=[Depends(require_session)])
async def dashboard_beacon_action(
    node_id: str, action: str, request: Request, payload: BeaconActionRequest | BeaconIntervalRequest | None = None,
    user: AuthenticatedUser = Depends(require_session),
) -> dict[str, object]:
    controller: BeaconController = request.app.state.beacon
    body = payload.model_dump(exclude_none=True) if payload else {}
    try:
        return await controller.action(user.account_id, node_id, action, body)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="등록된 beacon을 찾지 못했습니다.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BeaconUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.post("/dashboard/beacons/{node_id}/commands", status_code=202, dependencies=[Depends(require_session)])
async def dashboard_beacon_command(
    node_id: str, payload: BeaconCommandRequest, request: Request,
    user: AuthenticatedUser = Depends(require_session),
) -> dict[str, object]:
    params = {"fs": payload.fs, "q": payload.q, "warm": payload.warm} if payload.type == "image" else {}
    try:
        return await request.app.state.beacon.command(user.account_id, node_id, payload.type, params)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="등록된 beacon을 찾지 못했습니다.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BeaconUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.get("/dashboard/beacons/{node_id}/energy", dependencies=[Depends(require_session)])
async def dashboard_beacon_energy(
    node_id: str, request: Request, user: AuthenticatedUser = Depends(require_session),
) -> dict[str, object]:
    try:
        return await request.app.state.beacon.energy(user.account_id, node_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="등록된 beacon을 찾지 못했습니다.") from exc
    except BeaconUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.get("/dashboard/beacons/{node_id}/history", dependencies=[Depends(require_session)])
async def dashboard_beacon_history(
    node_id: str, request: Request, limit: int = 100,
    user: AuthenticatedUser = Depends(require_session),
) -> list[dict[str, object]]:
    try:
        return request.app.state.beacon_store.list_history(user.account_id, node_id, limit)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/dashboard/beacons/{node_id}/commands/{command_id}", dependencies=[Depends(require_session)])
async def dashboard_beacon_command_status(
    node_id: str, command_id: int, request: Request,
    user: AuthenticatedUser = Depends(require_session),
) -> dict[str, object]:
    try:
        history = request.app.state.beacon_store.list_history(user.account_id, node_id, 200)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = next((item for item in history if item["command_id"] == command_id), None)
    if result is None:
        raise HTTPException(status_code=404, detail="명령을 찾지 못했습니다.")
    if result["state"] not in {"done", "failed", "expired"}:
        try:
            remote = await request.app.state.beacon.client.get_command(command_id)
            if remote.get("node_id") != node_id:
                raise HTTPException(status_code=404, detail="명령을 찾지 못했습니다.")
            if remote.get("state") in {"done", "failed", "expired"}:
                image_result = remote.get("result")
                if isinstance(image_result, dict) and image_result.get("kind") == "image":
                    local_file = request.app.state.beacon._copy_image_result(node_id, command_id, image_result)
                    if local_file:
                        remote = {**remote, "result": {**image_result, "local_file_path": str(local_file)}}
                request.app.state.beacon_store.record_remote_command(remote)
                history = request.app.state.beacon_store.list_history(user.account_id, node_id, 200)
                result = next((item for item in history if item["command_id"] == command_id), result)
        except BeaconUnavailable:
            pass
    return result


async def _weather_dashboard_tool(request: Request, name: str, arguments: dict[str, object]) -> dict[str, object]:
    try:
        raw = await request.app.state.mcp.call_tool(name, arguments)
    except Exception as exc:
        logger.warning("Weather dashboard MCP call failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="기상청 날씨 데이터를 가져오지 못했습니다. MCP 서버와 API 키를 확인해 주세요.") from None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=502, detail="기상청 응답을 처리할 수 없습니다.") from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="기상청 응답 형식이 예상과 다릅니다.")
    if not data.get("ok"):
        raise HTTPException(status_code=503, detail=str(data.get("error") or "기상청 날씨 데이터를 사용할 수 없습니다."))
    return data


@app.get("/dashboard/weather/jeju/map", dependencies=[Depends(require_session)])
async def dashboard_jeju_weather_map(request: Request) -> dict[str, object]:
    return await _weather_dashboard_tool(request, "get_jeju_weather_overview", {})


@app.get("/dashboard/weather/jeju/area", dependencies=[Depends(require_session)])
async def dashboard_jeju_weather_area(request: Request, area: str = "남원읍") -> dict[str, object]:
    return await _weather_dashboard_tool(request, "get_jeju_weather_area", {"area": area})


@app.get("/dashboard/assets/{asset_id}/preview", dependencies=[Depends(require_session)])
async def dashboard_asset_preview(asset_id: str, request: Request) -> FileResponse:
    try:
        file_path, media_type = store(request).asset_file(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Camera asset not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Camera asset file is missing") from exc
    return FileResponse(file_path, media_type=media_type)


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_session)])
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    return await _handle_chat(payload, request)


@app.post("/chat/stream", dependencies=[Depends(require_session)])
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    async def event_stream():
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

        async def publish(event: dict[str, object]) -> None:
            await queue.put(event)

        async def produce_response() -> None:
            try:
                result = await _handle_chat(payload, request, on_progress=publish)
                await queue.put({"type": "done", "thread_id": result.thread_id, "reply": result.reply})
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                await queue.put({"type": "error", "status": exc.status_code, "detail": detail})
            except Exception:
                logger.exception("Unexpected error while streaming chat response")
                await queue.put({"type": "error", "status": 500, "detail": "대화 처리 중 서버 오류가 발생했습니다."})
            finally:
                await queue.put(None)

        task = asyncio.create_task(produce_response())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


async def _handle_chat(
    payload: ChatRequest,
    request: Request,
    on_progress: ProgressCallback | None = None,
) -> ChatResponse:
    progress_events: list[dict[str, object]] = []

    async def collect_progress(event: dict[str, object]) -> None:
        progress_events.append(event)
        if on_progress is not None:
            await on_progress(event)

    thread_store = store(request)
    if payload.thread_id:
        try:
            document = thread_store.load(payload.thread_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread not found") from exc
    else:
        document = thread_store.create(payload.message)

    user_message = Message(role="user", content=payload.message, created_at=datetime.now(timezone.utc))
    thread_store.append_message(document.thread_id, user_message)
    document.messages.append(user_message)
    try:
        async with request.app.state.model_inference_lock:
            reply = await reply_with_tools(
                gemma=request.app.state.gemma,
                mcp=request.app.state.mcp,
                store=thread_store,
                thread_id=document.thread_id,
                history=document.messages,
                max_tool_rounds=get_settings().mcp_max_tool_rounds,
                on_progress=collect_progress if on_progress is not None else None,
            )
    except APIConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="Local llama.cpp server is unavailable. Start scripts/serve-gemma4-e2b.sh.",
        ) from exc
    except ContextWindowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except EmptyModelResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except MCPUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except APIStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Local llama.cpp returned {exc.status_code}.") from exc
    if on_progress is not None:
        await collect_progress({"type": "status", "phase": "complete", "message": "답변을 완료했습니다."})
    thread_store.append_message(
        document.thread_id,
        Message(
            role="assistant",
            content=reply,
            created_at=datetime.now(timezone.utc),
            trace=progress_events or None,
        ),
    )
    return ChatResponse(thread_id=document.thread_id, reply=reply)
