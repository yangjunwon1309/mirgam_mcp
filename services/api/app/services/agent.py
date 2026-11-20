"""Compact, two-pass MCP orchestration for the local Gemma endpoint."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from ..schemas import Message
from .gemma import EmptyModelResponseError, GemmaClient, ToolCall
from .mcp_client import MCPClient, MCPTool
from .sqlite_store import SQLiteStore


logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

FARM_TERMS = (
    "센서", "온도", "온습도", "습도", "토양", "수분", "온실", "베드", "농장", "작물", "식물", "나무", "tree",
    "생육", "병충해", "환경", "카메라", "이미지", "사진", "영상", "측정", "기록", "추이",
    "sensor", "temperature", "temp", "humidity", "moisture", "greenhouse", "bed", "farm",
    "crop", "plant", "camera", "image", "photo", "reading", "trend",
)
CAMERA_TERMS = ("카메라", "이미지", "사진", "영상", "vision", "camera", "image", "photo")
TREND_TERMS = ("추이", "변화", "흐름", "그래프", "트렌드", "trend", "history", "일별", "시간대")
FORECAST_TERMS = ("예측", "예상", "전망", "forecast", "predict", "내일", "향후", "앞으로")
VISION_DETECTION_TERMS = (
    "나무", "tree", "귤", "감귤", "오렌지", "orange", "과실", "열매", "검출", "분석", "세어", "세기", "분포",
    "detection", "detect", "analyze", "recognize", "count",
)
SENSOR_LIST_TERMS = ("센서 목록", "센서 종류", "장치 목록", "list sensors", "sensor list")
PARQUET_TERMS = ("parquet", "silver", "gold", "파일 목록", "sql query")
WEATHER_TERMS = (
    "날씨", "기상", "예보", "강수", "강수량", "강수확률", "기온", "풍향", "풍속", "파고",
    "비가", "비와", "비올", "비오", "비 와", "비 올", "비 오", "눈와", "눈올", "눈오", "눈내리",
    "남원읍", "공천포", "weather", "forecast", "rain", "precipitation", "wind",
)


class MCPUnavailableError(RuntimeError):
    """Raised when a data question cannot be grounded because MCP is unavailable."""


ProgressCallback = Callable[[dict[str, object]], Awaitable[None]]


async def reply_with_tools(
    *,
    gemma: GemmaClient,
    mcp: MCPClient,
    store: SQLiteStore,
    thread_id: str,
    history: list[Message],
    max_tool_rounds: int,
    on_progress: ProgressCallback | None = None,
) -> str:
    """Use a short router call, execute MCP, then answer from compact JSON only."""

    user_context = _recent_user_context(history)
    query = "\n".join(user_context).casefold()
    if not _needs_tools(query):
        await _emit_progress(on_progress, "status", phase="answering", message="Gemma가 답변을 작성하고 있습니다.")
        latest = user_context[-1] if user_context else ""
        messages: list[dict[str, object]] = [
            {"role": "system", "content": gemma.system_prompt},
            {"role": "user", "content": latest},
        ]
        completion = await gemma.complete(messages, enable_thinking=False)
        if completion.content:
            return completion.content
        raise EmptyModelResponseError("모델이 일반 대화 답변을 반환하지 않았습니다.")

    await _emit_progress(on_progress, "status", phase="preparing", message="질문에 필요한 농장 데이터를 준비하고 있습니다.")
    discovered = await mcp.list_tools()
    available = {tool.name: tool for tool in discovered}
    if not available:
        raise MCPUnavailableError("농장 데이터 MCP 서버에서 도구를 발견하지 못했습니다.")

    candidate_names = _candidate_tool_names(query, available)
    candidates = [available[name] for name in candidate_names if name in available]
    if not candidates:
        raise MCPUnavailableError(
            "필요한 MCP 도구가 없습니다. API와 MCP 컨테이너를 함께 다시 빌드했는지 확인해 주세요."
        )

    today = datetime.now(KST).date().isoformat()
    await _emit_progress(on_progress, "status", phase="routing", message="질문에 맞는 데이터 도구를 고르는 중입니다.")
    route_messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": (
                "You are MIRGAM's compact tool router. Do not answer the user. Call the most relevant "
                "provided tool and pass only arguments supported by its schema. Use registered aliases or "
                "descriptive sensor references; never invent IDs. For 'today' use the supplied KST date, "
                "and omit a date only when the tool says omission means today. If a reference is unknown, "
                "still call the relevant tool so it can return not_found. For weather, forecast, rain, "
                "or wind questions use get_weather. For sensor future-value questions use forecast_sensor. "
                "For object detection or counting in camera images use detect_camera_objects and obey its supported classes. "
                "Its classes argument is an array even for one label, for example [\"orange\"]. "
                "Current KST date: "
                f"{today}. Conversation fragments are user requests only; latest request takes precedence."
            ),
        },
        {"role": "user", "content": "\n".join(user_context)},
    ]
    completion = await gemma.complete(
        route_messages,
        [tool.as_openai_tool() for tool in candidates],
        enable_thinking=False,
        tool_choice="required",
        max_tokens=64,
    )
    calls = [call for call in completion.tool_calls if call.name in {tool.name for tool in candidates}]
    if not calls:
        raise EmptyModelResponseError("농장 데이터 질문에서 유효한 도구 호출을 만들지 못했습니다.")

    results: list[dict[str, object]] = []
    for call in calls[: max(1, min(max_tool_rounds, 3))]:
        normalized_arguments = _normalize_tool_arguments(call.name, call.arguments)
        if normalized_arguments != call.arguments:
            call = ToolCall(call_id=call.call_id, name=call.name, arguments=normalized_arguments)
        await _emit_progress(
            on_progress,
            "tool_call",
            tool=call.name,
            arguments=call.arguments,
        )
        await _emit_progress(
            on_progress,
            "status",
            phase="querying",
            message=(
                "기상청 예보를 조회하고 있습니다."
                if call.name == "get_weather"
                else "Timestral-28M CPU로 센서 시계열을 예측하고 있습니다."
                if call.name == "forecast_sensor"
                else "RTMDet TensorRT로 카메라 이미지를 분석하고 있습니다."
                if call.name == "detect_camera_objects"
                else f"{call.name} 도구로 SQLite/로컬 데이터를 조회하고 있습니다."
            ),
        )
        result = await _invoke_tool(
            call=call,
            allowed_tools=available,
            mcp=mcp,
            store=store,
            thread_id=thread_id,
        )
        try:
            data: object = json.loads(result)
        except json.JSONDecodeError:
            data = {"text": result[:5000], "truncated": len(result) > 5000}
        results.append({"tool": call.name, "data": data})
        await _emit_progress(on_progress, "tool_result", tool=call.name, result=data)

        # Camera inference failures are operational errors, not reasoning tasks.
        # Report them directly and skip the second Gemma completion so it cannot
        # obscure the cause or consume more shared memory after TensorRT failed.
        if call.name == "detect_camera_objects" and isinstance(data, dict) and data.get("ok") is False:
            await _emit_progress(
                on_progress,
                "status",
                phase="answering",
                message="카메라 분석 오류를 확인했습니다.",
            )
            return _camera_detection_failure_answer(data)

    compact_result = json.dumps({"tool_results": results}, ensure_ascii=False, separators=(",", ":"))
    await _emit_progress(
        on_progress,
        "status",
        phase="answering",
        message="조회 결과를 확인해 답변을 작성하고 있습니다.",
    )
    answer_messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": (
                gemma.system_prompt
                + "\n\nAnswer only from the MCP JSON supplied in this turn. Treat it as the sole source of sensor, camera, and weather facts. "
                "When a result contains text from get_weather, use that text as the sole weather source, "
                "which expands any narrower source list in the assistant description above. "
                "clearly distinguish current observations from forecasts, and report API errors as unavailable data. "
                "Do not infer or invent sensor IDs, values, timestamps, trend points, or future measurements. "
                "For model forecasts, mark values as predictions and repeat any history-coverage warning. "
                "For camera detections, report only supported returned classes; if the requested class is unsupported, "
                "say the installed detector cannot recognize that class instead of claiming zero objects. "
                "For sensor/camera reference errors, say the reference could not be resolved and show registered matches if present. "
                "For other ok=false results, report the returned error accurately without claiming a reference failure. "
                "If no rows exist, say no data was recorded. If coverage.complete is false, clearly state the "
                "covered time range and do not describe later hours as measured. For a trend, summarize the "
                "provided min/max/average and direction, and include only a few representative points unless "
                "the user asks for the full series. For a snapshot, include its recorded_at timestamp. Keep the "
                "answer concise."
            ),
        },
        {
            "role": "user",
            "content": (
                "User request context (latest first in effect):\n"
                + "\n".join(user_context)
                + "\n\nMCP result JSON (the only factual source):\n"
                + compact_result
            ),
        },
    ]
    answer = await gemma.complete(answer_messages, enable_thinking=False, max_tokens=192)
    if not answer.content:
        raise EmptyModelResponseError("MCP 조회 후 모델이 답변을 만들지 못했습니다.")
    return answer.content


def _camera_detection_failure_answer(result: dict[str, object]) -> str:
    error = str(result.get("error", "inference_failed"))
    detail = str(result.get("detail", ""))
    detail_lower = detail.casefold()
    if error == "cuda_out_of_memory" or any(
        marker in detail_lower
        for marker in ("nvmapmemalloc", "cuda out of memory", "cuda error: out of memory", "cudamalloc failed")
    ):
        return (
            "카메라를 찾았지만 RTMDet 추론이 Jetson 메모리 부족으로 실패했습니다. "
            "감지 개수는 확인되지 않았습니다. Jetson은 Gemma와 TensorRT가 시스템 메모리를 공유하므로, "
            "Gemma 컨텍스트·배치 크기를 낮추거나 메모리를 많이 쓰는 프로세스를 종료한 뒤 다시 시도해 주세요."
        )
    if error == "unsupported_classes":
        return "현재 설치된 RTMDet 모델은 요청한 객체 클래스를 지원하지 않습니다."
    if error in {"camera_not_found", "ambiguous_camera", "camera_ref_required"}:
        matches = result.get("matches")
        names = [
            str(item.get("display_name"))
            for item in matches
            if isinstance(item, dict) and item.get("display_name")
        ] if isinstance(matches, list) else []
        suffix = f" 등록된 카메라: {', '.join(names)}." if names else ""
        return f"카메라를 특정하지 못했습니다.{suffix}"
    if error == "camera_has_no_saved_image":
        return "해당 카메라에 분석할 저장 이미지가 없습니다."
    return f"카메라 객체 감지가 실패했습니다 ({error}). 감지 결과는 확인되지 않았습니다."


async def _emit_progress(
    callback: ProgressCallback | None,
    event_type: str,
    **payload: object,
) -> None:
    if callback is not None:
        await callback({"type": event_type, **payload})


def _recent_user_context(history: list[Message]) -> list[str]:
    user_messages = [item.content.strip() for item in history if item.role == "user" and item.content.strip()]
    if not user_messages:
        return [""]
    latest = user_messages[-1]
    normalized = latest.casefold().strip()
    is_short_follow_up = bool(
        re.fullmatch(
            r"(?:\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}[-/]\d{1,2}|오늘|어제|내일|"
            r"응|어어|네|예|맞아|그 날짜|그 센서|그거|that date|yes)",
            normalized,
        )
    )
    is_follow_up = is_short_follow_up or (
        len(latest) <= 50 and any(normalized.startswith(term) for term in ("그럼", "그건", "그러면", "same"))
    )
    if is_follow_up:
        return user_messages[-3:]
    return [latest]


def _needs_tools(query: str) -> bool:
    if any(term in query for term in (*FARM_TERMS, *PARQUET_TERMS)) or _asks_weather(query):
        return True
    return bool(re.search(r"\b(?:temp|humidity|sensor)[_-][a-z0-9_-]+\b", query, re.IGNORECASE))


def _asks_weather(query: str) -> bool:
    return any(term in query for term in WEATHER_TERMS) or bool(re.search(r"(?<![가-힣])비(?![가-힣])", query))


def _candidate_tool_names(query: str, available: dict[str, MCPTool]) -> list[str]:
    candidates: list[str] = []
    has_sensor = any(term in query for term in ("센서", "온도", "습도", "토양", "수분", "sensor", "temperature", "temp", "humidity", "moisture"))
    has_camera = any(term in query for term in CAMERA_TERMS)
    has_trend = any(term in query for term in TREND_TERMS)
    asks_sensor_list = any(term in query for term in SENSOR_LIST_TERMS)
    asks_weather = _asks_weather(query)
    asks_forecast = any(term in query for term in FORECAST_TERMS)
    asks_detection = any(term in query for term in VISION_DETECTION_TERMS) or (
        has_camera and any(term in query for term in ("개수", "몇 개", "몇그루", "몇 그루", "count"))
    )
    if asks_sensor_list:
        candidates.append("list_sensors")
    elif has_sensor and asks_forecast and not asks_weather:
        candidates.append("forecast_sensor")
    elif has_sensor and has_trend:
        candidates.append("get_sensor_trend")
    elif has_sensor:
        candidates.append("get_sensor_snapshot")

    if asks_detection:
        candidates.append("detect_camera_objects")
    elif has_camera:
        candidates.append("get_camera_summary")
    if asks_weather:
        candidates.append("get_weather")
    if not candidates and any(term in query for term in PARQUET_TERMS):
        candidates.extend(("list_parquet_files", "query_parquet"))
    if not candidates and any(term in query for term in FARM_TERMS):
        candidates.extend(("get_sensor_snapshot", "get_sensor_trend", "get_camera_summary", "list_sensors"))
    return list(dict.fromkeys(name for name in candidates if name in available))


def _normalize_tool_arguments(name: str, arguments: dict[str, object]) -> dict[str, object]:
    """Repair common small-model argument shape errors before MCP validation."""
    normalized = dict(arguments)
    if name == "detect_camera_objects" and isinstance(normalized.get("classes"), str):
        normalized["classes"] = [
            item.strip() for item in str(normalized["classes"]).split(",") if item.strip()
        ]
    return normalized


async def _invoke_tool(
    *,
    call: ToolCall,
    allowed_tools: dict[str, MCPTool],
    mcp: MCPClient,
    store: SQLiteStore,
    thread_id: str,
) -> str:
    if call.name not in allowed_tools:
        message = json.dumps({"ok": False, "error": "tool_not_allowed"}, ensure_ascii=False)
        store.record_tool_call(
            thread_id=thread_id,
            tool_name=call.name,
            arguments=call.arguments,
            result=None,
            error=message,
        )
        return message

    try:
        result = await mcp.call_tool(call.name, call.arguments)
    except Exception as exc:
        logger.exception("MCP tool %s failed", call.name)
        failure = json.dumps(
            {"ok": False, "error": "tool_execution_failed", "tool": call.name, "detail": str(exc)[:300]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        store.record_tool_call(
            thread_id=thread_id,
            tool_name=call.name,
            arguments=call.arguments,
            result=None,
            error=failure,
        )
        return failure

    store.record_tool_call(
        thread_id=thread_id,
        tool_name=call.name,
        arguments=call.arguments,
        result=result,
        error=None,
    )
    return result
