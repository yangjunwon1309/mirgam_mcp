"""Convert KMA village-forecast JSON responses into compact Korean text."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta


PTY = {0: "없음", 1: "비", 2: "비/눈", 3: "눈", 4: "소나기", 5: "빗방울", 6: "빗방울/눈날림", 7: "눈날림"}
SKY = {1: "맑음", 2: "맑음", 3: "구름많음", 4: "흐림"}
DIR16 = ["북", "북북동", "북동", "동북동", "동", "동남동", "남동", "남남동", "남", "남남서", "남서", "서남서", "서", "서북서", "북서", "북북서"]
WEEK = "월화수목금토일"
MISSING = {"-999", "-998", "-900"}
STRONG_WIND = 9.0
LEGEND = (
    "기상청 동네예보(5km 격자). 현재 관측은 실측, 나머지는 예보. "
    "풍향은 바람이 불어오는 방향이며 강수확률은 %, 강수량은 1시간 기준."
)


class KmaError(Exception):
    """A safe-to-display KMA response or request error."""


def _items(raw: object) -> list[dict]:
    data = raw
    if isinstance(raw, (str, bytes)):
        import json

        data = json.loads(raw)
    try:
        response = data["response"]
        header = response["header"]
    except (KeyError, TypeError):
        raise KmaError("예상한 응답 형식이 아님") from None
    if str(header.get("resultCode")) != "00":
        raise KmaError(f'{header.get("resultCode")} {header.get("resultMsg")}')
    items = (response.get("body") or {}).get("items")
    if not isinstance(items, dict):
        return []
    value = items.get("item")
    if value is None:
        return []
    return [value] if isinstance(value, dict) else list(value)


def _by_time(items: list[dict]) -> dict[tuple[str, str], dict[str, str]]:
    rows: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for item in items:
        value = item.get("fcstValue", item.get("obsrValue"))
        if value is None or str(value).strip() in MISSING:
            continue
        day = item.get("fcstDate") or item.get("baseDate")
        time = item.get("fcstTime") or item.get("baseTime")
        category = item.get("category")
        if day and time and category:
            rows[(str(day), str(time))][str(category)] = str(value).strip()
    return dict(sorted(rows.items()))


def _float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _number(value: float) -> str:
    return f"{value:g}"


def _day(value: str) -> str:
    day = datetime.strptime(value, "%Y%m%d")
    return f"{day.month}/{day.day}({WEEK[day.weekday()]})"


def _hour(value: str) -> str:
    return f"{int(value[:2])}시"


def _clock(value: str) -> str:
    return f"{value[:2]}:{value[2:4]}"


def _weather(row: dict[str, str]) -> str | None:
    precipitation = _float(row.get("PTY"))
    sky = _float(row.get("SKY"))
    sky_text = SKY.get(int(sky)) if sky is not None else None
    if precipitation:
        precip_text = PTY.get(int(precipitation), f"강수코드{int(precipitation)}")
        return f"{precip_text}·{sky_text}" if sky_text else precip_text
    return sky_text or ("강수 없음" if precipitation == 0 else None)


def _precipitation(value: str | None) -> str | None:
    if value is None:
        return None
    number = _float(value)
    if number is not None:
        return None if number == 0 else f"{_number(number)}mm"
    return None if value == "강수없음" else value


def _snow(value: str | None) -> str | None:
    if value is None:
        return None
    number = _float(value)
    if number is not None:
        return None if number == 0 else f"{_number(number)}cm"
    return None if value == "적설없음" else value


def _wind(row: dict[str, str]) -> str | None:
    speed, direction = _float(row.get("WSD")), _float(row.get("VEC"))
    if speed is None:
        return None
    result = f"{_number(speed)}m/s"
    if direction is not None:
        bearing = DIR16[int((direction % 360) / 22.5 + 0.5) % 16]
        result = f"{bearing}풍 {result}"
    if speed >= STRONG_WIND:
        result += "(강한 바람)"
    return result


def _line(row: dict[str, str], observation: bool = False) -> str:
    parts: list[str] = []
    weather = _weather(row)
    if weather:
        parts.append(weather)
    temperature = _float(row.get("T1H", row.get("TMP")))
    if temperature is not None:
        parts.append(f"기온 {_number(temperature)}°C")
    probability = _float(row.get("POP"))
    if probability is not None:
        parts.append(f"강수확률 {int(probability)}%")
    rain = _precipitation(row.get("RN1", row.get("PCP")))
    if rain:
        parts.append(("최근 1시간 강수 " if observation else "시간당 강수 ") + rain)
    snow = _snow(row.get("SNO"))
    if snow:
        parts.append(f"시간당 적설 {snow}")
    humidity = _float(row.get("REH"))
    if humidity is not None:
        parts.append(f"습도 {int(humidity)}%")
    wind = _wind(row)
    if wind:
        parts.append(f"바람 {wind}")
    wave = _float(row.get("WAV"))
    if wave is not None:
        parts.append(f"파고 {_number(wave)}m")
    lightning = _float(row.get("LGT"))
    if lightning:
        parts.append(f"낙뢰 있음(LGT={_number(lightning)})")
    return ", ".join(parts) or "제공된 기상 항목 없음"


def _grid(items: list[dict]) -> str:
    return f'{items[0]["nx"]},{items[0]["ny"]}' if items else "?"


def format_current(raw: object) -> str:
    items = _items(raw)
    rows = _by_time(items)
    if not rows:
        return "[현재 관측] 데이터 없음"
    (day, time), row = next(iter(rows.items()))
    return f"[현재 관측 · 격자 {_grid(items)}] {_day(day)} {_clock(time)}\n{_line(row, observation=True)}"


def format_ultra(raw: object) -> str:
    items = _items(raw)
    rows = _by_time(items)
    if not rows:
        return "[초단기예보] 데이터 없음"
    base_time = items[0].get("baseTime", "")
    lines = [f"[초단기예보 · 향후 6시간 · 격자 {_grid(items)} · 발표 {_clock(base_time)}]"]
    previous_day = None
    for (day, time), row in rows.items():
        label = f"{_day(day)} {_hour(time)}" if day != previous_day else _hour(time)
        lines.append(f"- {label}: {_line(row)}")
        previous_day = day
    return "\n".join(lines)


def _ranges(hours: list[str], indexes: list[int]) -> str:
    groups: list[list[int]] = []
    current = [indexes[0]]
    for index in indexes[1:]:
        previous_hour = int(hours[current[-1]][:2])
        next_hour = int(hours[index][:2])
        if next_hour == previous_hour + 1:
            current.append(index)
        else:
            groups.append(current)
            current = [index]
    groups.append(current)
    output = []
    for group in groups:
        start, end = int(hours[group[0]][:2]), int(hours[group[-1]][:2])
        output.append(f"{start}시" if start == end else f"{start}~{end}시")
    return ", ".join(output)


def _precipitation_sort_key(value: str) -> float:
    match = re.search(r"\d+(\.\d+)?", value or "")
    number = float(match.group()) if match else 0.0
    return number - 0.01 if "미만" in value else number


def _daily(rows: dict[tuple[str, str], dict[str, str]]) -> list[str]:
    days: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
    for (day, time), row in rows.items():
        days[day].append((time, row))
    if not days:
        return []
    first_day = next(iter(days))
    output: list[str] = []
    for day, entries in days.items():
        hours = [time for time, _ in entries]
        values = [row for _, row in entries]
        parts: list[str] = []
        rain_indexes = [i for i, row in enumerate(values) if (_float(row.get("PTY")) or 0) != 0]
        if rain_indexes:
            kinds = "/".join(dict.fromkeys(PTY.get(int(_float(values[i]["PTY"])), "강수") for i in rain_indexes))
            parts.append(f"{kinds} {_ranges(hours, rain_indexes)}")
        else:
            parts.append("강수 없음")
        probabilities = [_float(row.get("POP")) for row in values]
        probabilities = [value for value in probabilities if value is not None]
        if probabilities:
            parts.append(f"강수확률 최대 {int(max(probabilities))}%")
        rain_values = [row["PCP"] for row in values if _precipitation(row.get("PCP"))]
        if rain_values:
            parts.append("최대 시간당 강수 " + str(_precipitation(max(rain_values, key=_precipitation_sort_key))))
        snow_values = [row["SNO"] for row in values if _snow(row.get("SNO"))]
        if snow_values:
            parts.append("적설 있음 " + str(_snow(max(snow_values, key=_precipitation_sort_key))))
        day_sky = [int(_float(row["SKY"])) for time, row in entries if "SKY" in row and 6 <= int(time[:2]) <= 21]
        all_sky = [int(_float(row["SKY"])) for _, row in entries if "SKY" in row]
        common_sky = Counter(day_sky or all_sky).most_common(1)
        if common_sky:
            parts.append(f"하늘 {SKY.get(common_sky[0][0], '정보 없음')} 위주")
        minimums = [_float(row["TMN"]) for row in values if "TMN" in row]
        maximums = [_float(row["TMX"]) for row in values if "TMX" in row]
        temperatures = [_float(row["TMP"]) for row in values if "TMP" in row]
        low = min(minimums) if minimums else (min(temperatures) if temperatures else None)
        high = max(maximums) if maximums else (max(temperatures) if temperatures else None)
        if low is not None and high is not None:
            parts.append(f"기온 {_number(low)}°C" if low == high else f"기온 {_number(low)}~{_number(high)}°C")
        winds = [_float(row["WSD"]) for row in values if "WSD" in row]
        if winds:
            parts.append(f"최대풍속 {_number(max(winds))}m/s")
        waves = [_float(row["WAV"]) for row in values if "WAV" in row]
        if waves:
            parts.append(f"최대 파고 {_number(max(waves))}m")
        note = f" ({_hour(hours[0])} 이후 자료)" if day == first_day and hours[0] != "0000" else ""
        output.append(f"- {_day(day)}: " + ", ".join(parts) + note)
    return output


def format_short(raw: object, hourly_hours: int = 24) -> str:
    items = _items(raw)
    rows = _by_time(items)
    if not rows:
        return "[단기예보] 데이터 없음"
    base_time = items[0].get("baseTime", "")
    first_key = next(iter(rows))
    start = datetime.strptime(first_key[0] + first_key[1], "%Y%m%d%H%M")
    limit = start + timedelta(hours=hourly_hours)
    lines = [f"[단기예보 · 격자 {_grid(items)} · 발표 {_clock(base_time)}]", f"시각별 (앞 {hourly_hours}시간):"]
    previous_day = None
    for (day, time), row in rows.items():
        if datetime.strptime(day + time, "%Y%m%d%H%M") >= limit:
            break
        label = f"{_day(day)} {_hour(time)}" if day != previous_day else _hour(time)
        lines.append(f"- {label}: {_line(row)}")
        previous_day = day
    lines.append("일별 요약:")
    lines.extend(_daily(rows))
    return "\n".join(lines)
