"""Live 제주 읍면동 날씨 데이터를 위한 MCP dashboard tools."""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import kma_weather as weather
from . import weather_cache_store
from ..mcp_app import mcp


CACHE_TTL_SECONDS = 1200
QUAL_PCP = {1: "약한 비(<3mm)", 2: "보통 비(3~15mm)", 3: "강한 비(15mm+)"}
QUAL_SNO = {1: "약한 눈(<1cm)", 2: "눈(1cm+)"}
QUAL_WSD = {1: "약한 바람(<3m/s)", 2: "약간 강한 바람(4~9m/s)", 3: "강한 바람(9m/s+)"}


def _areas_config() -> dict:
    configured = os.environ.get("KMA_AREAS_PATH")
    path = Path(configured) if configured else Path(__file__).with_name("area_grids.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        areas = value["areas"]
        if not isinstance(areas, dict) or not areas:
            raise ValueError("empty area list")
        return areas
    except (OSError, ValueError, KeyError, TypeError):
        raise weather.fmt.KmaError("제주 지역 격자 설정을 읽을 수 없음") from None


def _integer(row: dict[str, str], key: str) -> int | None:
    value = weather.fmt._float(row.get(key))
    return int(value) if value is not None else None


def _weather_row(key: tuple[str, str], row: dict[str, str]) -> dict:
    temperature = row.get("T1H")
    if temperature is None:
        temperature = row.get("TMP")
    return {
        "t": key[0] + key[1],
        "tmp": weather.fmt._float(temperature),
        "pty": _integer(row, "PTY"),
        "sky": _integer(row, "SKY"),
        "pop": _integer(row, "POP"),
        "reh": _integer(row, "REH"),
        "wsd": weather.fmt._float(row.get("WSD")),
        "vec": _integer(row, "VEC"),
        "pcp": weather.fmt._precipitation(row.get("RN1", row.get("PCP"))),
        "pcpq": QUAL_PCP.get(_integer(row, "PCPQ")),
        "snoq": QUAL_SNO.get(_integer(row, "SNOQ")),
        "wsdq": QUAL_WSD.get(_integer(row, "WSDQ")),
        "wav": weather.fmt._float(row.get("WAV")),
    }


def _fetch_section(scope: str, nx: int, ny: int, now: datetime) -> dict:
    raw = weather._fetch(scope, nx, ny, now)
    items = weather.fmt._items(raw)
    rows = weather.fmt._by_time(items)
    if scope == "forecast5d" and items:
        base = datetime.strptime(items[0]["baseDate"] + items[0]["baseTime"], "%Y%m%d%H%M")
        extended_day = (base + timedelta(days=3 if base.hour < 17 else 4)).strftime("%Y%m%d")
        for (day, _), row in rows.items():
            if day < extended_day:
                continue
            for category in ("PCP", "SNO", "WSD"):
                value = row.get(category)
                if value is not None and value.isdigit() and int(value) in (1, 2, 3):
                    row[category + "Q"] = int(value)
                    row.pop(category, None)
    if not rows:
        return {"base": "", "rows": [], "daily": [] if scope == "forecast5d" else None}
    base = items[0].get("baseDate", "") + items[0].get("baseTime", "")
    result = {"base": base, "rows": [_weather_row(key, row) for key, row in rows.items()]}
    if scope == "forecast5d":
        result["daily"] = _daily_summary(rows)
    return result


def _daily_summary(rows: dict[tuple[str, str], dict[str, str]]) -> list[dict]:
    grouped: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
    for (day, clock), row in rows.items():
        grouped[day].append((clock, row))
    daily = []
    for day, entries in grouped.items():
        values = [row for _, row in entries]
        rain_rows = [(clock, row) for clock, row in entries if (_integer(row, "PTY") or 0) > 0]
        rain_kinds = list(dict.fromkeys(weather.fmt.PTY.get(_integer(row, "PTY"), "강수") for _, row in rain_rows))
        rain_hours = list(dict.fromkeys(f"{int(clock[:2])}시" for clock, _ in rain_rows))
        skies = [_integer(row, "SKY") for _, row in entries]
        skies = [value for value in skies if value is not None]
        temperatures = [weather.fmt._float(row.get("TMP")) for row in values]
        temperatures = [value for value in temperatures if value is not None]
        lows = [weather.fmt._float(row.get("TMN")) for row in values]
        highs = [weather.fmt._float(row.get("TMX")) for row in values]
        lows = [value for value in lows if value is not None]
        highs = [value for value in highs if value is not None]
        numeric_rain = [weather.fmt._float(row.get("PCP")) for row in values]
        numeric_rain = [value for value in numeric_rain if value is not None]
        qualitative_rain = [QUAL_PCP.get(int(row["PCPQ"])) for row in values if row.get("PCPQ")]
        wind = [weather.fmt._float(row.get("WSD")) for row in values]
        wind = [value for value in wind if value is not None]
        daily.append({
            "date": day,
            "rain": {"kinds": "/".join(rain_kinds), "when": "·".join(rain_hours)} if rain_rows else None,
            "pop": max((value for value in (_integer(row, "POP") for row in values) if value is not None), default=None),
            "pcp": f"{max(numeric_rain):g}mm" if numeric_rain else (qualitative_rain[-1] if qualitative_rain else None),
            "sky": Counter(skies).most_common(1)[0][0] if skies else None,
            "tmin": min(lows) if lows else (min(temperatures) if temperatures else None),
            "tmax": max(highs) if highs else (max(temperatures) if temperatures else None),
            "wsd": max(wind) if wind else None,
            "wsdq": next((QUAL_WSD.get(int(row["WSDQ"])) for row in values if row.get("WSDQ")), None),
            "wav": max((value for value in (weather.fmt._float(row.get("WAV")) for row in values) if value is not None), default=None),
            "partial_from": entries[0][0] if day == next(iter(grouped)) and entries[0][0] != "0000" else None,
        })
    return daily


def _grid_key(nx: int, ny: int) -> str:
    return f"{nx},{ny}"


def _cache_result(payload: dict, age_seconds: int, stale: bool, refresh_error: str | None = None) -> dict:
    result = dict(payload)
    result["cache"] = {
        "source": "sqlite",
        "age_seconds": age_seconds,
        "stale": stale,
    }
    if refresh_error:
        result["cache"]["refresh_error"] = refresh_error
    return result


def _live_result(payload: dict) -> dict:
    result = dict(payload)
    result["cache"] = {"source": "live", "age_seconds": 0, "stale": False}
    return result


def _build_map(now: datetime) -> dict:
    areas = _areas_config()
    grid_names = sorted({(int(area["nx"]), int(area["ny"])) for area in areas.values()})
    grids: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for index, (nx, ny) in enumerate(grid_names):
        key = _grid_key(nx, ny)
        try:
            section = _fetch_section("now", nx, ny, now)
            grids[key] = {"now": {"base": section["base"], "row": section["rows"][0] if section["rows"] else None}}
        except weather.fmt.KmaError as exc:
            failures[key] = str(exc)
            continue
        try:
            forecast = _fetch_section("forecast5d", nx, ny, now)
            first_probability = next((row["pop"] for row in forecast["rows"] if row["pop"] is not None), None)
            grids[key]["forecast"] = {"pop": first_probability}
        except weather.fmt.KmaError as exc:
            failures[key] = f"단기예보: {exc}"
        if index + 1 < len(grid_names):
            time.sleep(0.1)
    mapped_areas = {
        name: {"nx": int(value["nx"]), "ny": int(value["ny"]), "grid": _grid_key(int(value["nx"]), int(value["ny"])),
               "source": value.get("source", "unknown")}
        for name, value in areas.items()
    }
    return {
        "ok": bool(grids),
        "areas": mapped_areas,
        "grids": grids,
        "errors": failures,
        "updated_at": now.isoformat(timespec="seconds"),
        "source": "기상청 API허브 동네예보 · 현재 실황 · 5km 격자",
    }


@mcp.tool()
def get_jeju_weather_overview() -> str:
    """제주도 읍면동 전체의 현재 기상 요약을 지도 표시용 JSON으로 조회한다. 실시간 API 데이터이며 모의값이 아니다."""
    cached = weather_cache_store.get("jeju:overview")
    if cached and cached[1] < CACHE_TTL_SECONDS:
        return json.dumps(
            _cache_result(cached[0], cached[1], stale=False),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    if not os.environ.get("KMA_API_KEY"):
        if cached:
            return json.dumps(
                _cache_result(cached[0], cached[1], stale=True, refresh_error="KMA_API_KEY 가 설정되지 않음"),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return json.dumps({"ok": False, "error": "KMA_API_KEY 가 설정되지 않음 (.env 확인)"}, ensure_ascii=False)
    try:
        result = _build_map(datetime.now(weather.KST))
    except weather.fmt.KmaError as exc:
        result = {"ok": False, "error": str(exc)}
    if not result.get("ok") and result.get("errors"):
        # Preserve a safe, actionable KMA error for the UI when every grid failed.
        # The request helper strips URLs so this cannot expose authKey.
        first_error = next(iter(result["errors"].values()), None)
        if first_error:
            result["error"] = f"기상청 API 조회 실패: {first_error}"
    if result.get("ok"):
        weather_cache_store.put("jeju:overview", result)
        result = _live_result(result)
    elif cached:
        result = _cache_result(
            cached[0], cached[1], stale=True,
            refresh_error=str(result.get("error") or "기상청 자료 갱신 실패"),
        )
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


@mcp.tool()
def get_jeju_weather_area(area: str = "남원읍") -> str:
    """제주 지도에서 선택한 읍면동의 현재 관측, 향후 6시간, 최대 5일 예보를 대시보드용 JSON으로 조회한다."""
    cache_key = f"jeju:area:{area}"
    cached = weather_cache_store.get(cache_key)
    if cached and cached[1] < CACHE_TTL_SECONDS:
        return json.dumps(
            _cache_result(cached[0], cached[1], stale=False),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    if not os.environ.get("KMA_API_KEY"):
        if cached:
            return json.dumps(
                _cache_result(cached[0], cached[1], stale=True, refresh_error="KMA_API_KEY 가 설정되지 않음"),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return json.dumps({"ok": False, "error": "KMA_API_KEY 가 설정되지 않음 (.env 확인)"}, ensure_ascii=False)
    try:
        areas = _areas_config()
        config = areas.get(area)
        if config is None:
            return json.dumps({"ok": False, "error": "선택한 제주 지역을 찾을 수 없음"}, ensure_ascii=False)
        nx, ny = int(config["nx"]), int(config["ny"])
        now = datetime.now(weather.KST)
        result = {
            "ok": True,
            "area": area,
            "grid": _grid_key(nx, ny),
            "grid_source": config.get("source", "unknown"),
            "current": _fetch_section("now", nx, ny, now),
            "next6h": _fetch_section("next6h", nx, ny, now),
            "forecast5d": _fetch_section("forecast5d", nx, ny, now),
            "updated_at": now.isoformat(timespec="seconds"),
        }
    except weather.fmt.KmaError as exc:
        result = {"ok": False, "error": str(exc)}
    except (OSError, TypeError, ValueError, KeyError):
        result = {"ok": False, "error": "제주 날씨 응답을 처리할 수 없음"}
    if result.get("ok"):
        weather_cache_store.put(cache_key, result)
        result = _live_result(result)
    elif cached:
        result = _cache_result(
            cached[0], cached[1], stale=True,
            refresh_error=str(result.get("error") or "기상청 자료 갱신 실패"),
        )
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
