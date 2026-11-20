"""KMA village-weather MCP tool for Namwon-eup and Gongcheonpo, Jeju."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Lock
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from ..mcp_app import mcp
from . import kma_weather_format as fmt
from . import weather_cache_store


logger = logging.getLogger(__name__)
load_dotenv()

BASE_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0"
KST = ZoneInfo("Asia/Seoul")
# Namwon-eup follows the KMA example. Gongcheonpo (55, 33) is still a candidate
# grid and should be confirmed with KMA's lon/lat-to-village-grid conversion API.
PLACES: dict[str, tuple[int, int]] = {"남원읍": (56, 33), "공천포": (55, 33)}
SHORT_BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
CACHE_SECONDS = 600
_cache: dict[tuple[str, int, int, str, str], tuple[float, dict]] = {}
_cache_lock = Lock()


def base_realtime(now: datetime) -> tuple[str, str]:
    value = now - timedelta(minutes=10)
    return value.strftime("%Y%m%d"), value.strftime("%H00")


def base_ultra(now: datetime) -> tuple[str, str]:
    value = now - timedelta(minutes=15)
    if value.minute >= 30:
        value = value.replace(minute=30, second=0, microsecond=0)
    else:
        value = (value - timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)
    return value.strftime("%Y%m%d"), value.strftime("%H%M")


def base_short(now: datetime) -> tuple[str, str]:
    value = now - timedelta(minutes=10)
    hours = [hour for hour in SHORT_BASE_HOURS if hour <= value.hour]
    if not hours:
        value -= timedelta(days=1)
        return value.strftime("%Y%m%d"), "2300"
    return value.strftime("%Y%m%d"), f"{hours[-1]:02d}00"


OPS: dict[str, tuple[str, Callable[[datetime], tuple[str, str]], timedelta]] = {
    "now": ("getUltraSrtNcst", base_realtime, timedelta(hours=1)),
    "next6h": ("getUltraSrtFcst", base_ultra, timedelta(hours=1)),
    "forecast5d": ("getVilageFcst", base_short, timedelta(hours=3)),
}


def _call(operation: str, nx: int, ny: int, base_date: str, base_time: str) -> dict:
    key = os.environ.get("KMA_API_KEY")
    if not key:
        raise fmt.KmaError("KMA_API_KEY 가 설정되지 않음 (.env 확인)")
    query = urllib.parse.urlencode(
        {
            "pageNo": 1,
            "numOfRows": 1000,
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": nx,
            "ny": ny,
            "authKey": key,
        }
    )
    request_url = f"{BASE_URL}/{operation}?{query}"
    try:
        with urllib.request.urlopen(request_url, timeout=10) as response:
            try:
                return json.load(response)
            except (json.JSONDecodeError, UnicodeError):
                raise fmt.KmaError("예상한 응답 형식이 아님: JSON 파싱 실패") from None
    except fmt.KmaError:
        raise
    except urllib.error.HTTPError as exc:
        # Report only the status code; HTTPError text can contain the request URL
        # and therefore the API key in its query string.
        raise fmt.KmaError(f"요청 실패(HTTP {exc.code})") from None
    except Exception as exc:
        # The request URL contains authKey; do not include exception text in logs
        # or tool output because HTTP client exceptions can echo the full URL.
        raise fmt.KmaError(f"요청 실패({type(exc).__name__})") from None


def _cached_call(operation: str, nx: int, ny: int, base_date: str, base_time: str) -> dict:
    cache_key = (operation, nx, ny, base_date, base_time)
    persistent_key = f"api:{operation}:{nx}:{ny}:{base_date}:{base_time}"
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        expired = [key for key, value in _cache.items() if now - value[0] >= CACHE_SECONDS]
        for key in expired:
            _cache.pop(key, None)
    persistent = weather_cache_store.get(persistent_key)
    if persistent and persistent[1] < CACHE_SECONDS:
        value = persistent[0]
        fmt._items(value)
        with _cache_lock:
            _cache[cache_key] = (time.monotonic(), value)
        return value
    value = _call(operation, nx, ny, base_date, base_time)
    # Do not retain API errors such as NO_DATA: a later request may succeed
    # once that forecast run has finished propagating.
    fmt._items(value)
    weather_cache_store.put(persistent_key, value)
    with _cache_lock:
        if len(_cache) >= 128:
            _cache.pop(next(iter(_cache)))
        _cache[cache_key] = (time.monotonic(), value)
    return value


def _fetch(scope: str, nx: int, ny: int, now: datetime) -> dict:
    operation, base_fn, retry_step = OPS[scope]
    for attempt, request_time in enumerate((now, now - retry_step)):
        base_date, base_time = base_fn(request_time)
        try:
            raw = _cached_call(operation, nx, ny, base_date, base_time)
            fmt._items(raw)
            return raw
        except fmt.KmaError as exc:
            if not str(exc).startswith("03") or attempt == 1:
                raise
    raise fmt.KmaError("03 NO_DATA")


@mcp.tool()
def get_weather(
    place: Literal["남원읍", "공천포"] = "남원읍",
    scope: Literal["now", "next6h", "forecast5d", "all"] = "all",
) -> str:
    """제주 서귀포시 남원읍/공천포의 기상청 동네예보(5km 격자).

    scope: now=현재 관측, next6h=향후 6시간, forecast5d=최대 5일 예보, all=전부.
    """
    key = os.environ.get("KMA_API_KEY")
    if not key:
        return "기상청 API 오류: KMA_API_KEY 가 설정되지 않음 (.env 확인)"
    nx, ny = PLACES[place]
    now = datetime.now(KST)
    scopes = ("now", "next6h", "forecast5d") if scope == "all" else (scope,)
    formatters = {
        "now": fmt.format_current,
        "next6h": fmt.format_ultra,
        "forecast5d": fmt.format_short,
    }
    sections = [f"위치: 제주 서귀포시 {place}", fmt.LEGEND]
    try:
        for current_scope in scopes:
            sections.append(formatters[current_scope](_fetch(current_scope, nx, ny, now)))
    except fmt.KmaError as exc:
        return f"기상청 API 오류: {exc}"
    except Exception as exc:
        logger.error("KMA response formatting failed (error_type=%s)", type(exc).__name__)
        return "기상청 API 오류: 예상한 응답 형식이 아님"
    return "\n\n".join(sections)
