"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

type ProtectedFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type GeoArea = { name: string; sgg: string; code: string; d: string; lx: number; ly: number; w: number; h: number; ncells: number };
type JejuMap = { width: number; height: number; inset: { x: number; y: number; w: number; h: number; label: string }; attribution: string; areas: GeoArea[] };
type AreaGrid = { nx: number; ny: number; source: string; grid: string };
type WeatherRow = { t: string; tmp: number | null; pty: number | null; sky: number | null; pop: number | null; reh: number | null; wsd: number | null; vec: number | null; pcp: string | null; wav: number | null };
type GridWeather = { now?: { base: string; row: WeatherRow | null }; forecast?: { pop: number | null } };
type WeatherCache = { source: "sqlite" | "live"; age_seconds: number; stale: boolean; refresh_error?: string };
type WeatherOverview = { ok: boolean; areas: Record<string, AreaGrid>; grids: Record<string, GridWeather>; errors: Record<string, string>; updated_at: string; source: string; cache?: WeatherCache };
type DailyWeather = { date: string; rain: { kinds: string; when: string } | null; pop: number | null; pcp: string | null; sky: number | null; tmin: number | null; tmax: number | null; wsd: number | null; wsdq: string | null; wav: number | null; partial_from: string | null };
type WeatherSection = { base: string; rows: WeatherRow[]; daily?: DailyWeather[] };
type WeatherDetail = { ok: boolean; area: string; grid: string; grid_source: string; current: WeatherSection; next6h: WeatherSection; forecast5d: WeatherSection; updated_at: string; cache?: WeatherCache };
type MetricKey = "tmp" | "pop" | "wsd" | "reh";
type MapBox = { x: number; y: number; w: number; h: number };
type MapGesture = { pointerId: number; startX: number; startY: number; startBox: MapBox; moved: boolean };

const DIR16 = ["북", "북북동", "북동", "동북동", "동", "동남동", "남동", "남남동", "남", "남남서", "남서", "서남서", "서", "서북서", "북서", "북북서"];
const PTY: Record<number, string> = { 1: "비", 2: "비/눈", 3: "눈", 4: "소나기", 5: "빗방울", 6: "빗방울·눈날림", 7: "눈날림" };
const SKY: Record<number, string> = { 1: "맑음", 2: "맑음", 3: "구름많음", 4: "흐림" };
const METRICS: { key: MetricKey; label: string; unit: string; min: number; max: number; colors: [number, number, number][] }[] = [
  { key: "tmp", label: "기온", unit: "°C", min: 6, max: 30, colors: [[46, 103, 175], [128, 182, 220], [230, 237, 221], [245, 181, 92], [209, 82, 48]] },
  { key: "pop", label: "강수확률", unit: "%", min: 0, max: 100, colors: [[239, 245, 235], [185, 215, 211], [94, 165, 192], [42, 115, 170], [26, 75, 132]] },
  { key: "wsd", label: "풍속", unit: "m/s", min: 0, max: 12, colors: [[240, 245, 233], [184, 213, 174], [125, 174, 130], [74, 133, 115], [34, 88, 90]] },
  { key: "reh", label: "습도", unit: "%", min: 40, max: 100, colors: [[249, 241, 221], [230, 208, 157], [183, 199, 164], [101, 159, 158], [44, 105, 133]] },
];
const MAX_MAP_ZOOM = 5;

function weatherValue(grid: GridWeather | undefined, metric: MetricKey): number | null {
  const row = grid?.now?.row;
  if (metric === "pop") return grid?.forecast?.pop ?? null;
  return row?.[metric] ?? null;
}

function metricColor(metric: MetricKey, value: number | null) {
  if (value == null) return "#d7ded7";
  const config = METRICS.find((item) => item.key === metric)!;
  const ratio = Math.max(0, Math.min(1, (value - config.min) / Math.max(1, config.max - config.min)));
  const scaled = ratio * (config.colors.length - 1);
  const index = Math.min(config.colors.length - 2, Math.floor(scaled));
  const blend = scaled - index;
  const color = config.colors[index].map((part, channel) => Math.round(part + (config.colors[index + 1][channel] - part) * blend));
  return `rgb(${color.join(",")})`;
}

function metricText(value: number | null, metric: MetricKey) {
  if (value == null) return "자료 없음";
  return `${metric === "tmp" || metric === "wsd" ? value.toFixed(1) : Math.round(value)}${METRICS.find((item) => item.key === metric)?.unit}`;
}

function metricGradient(metric: MetricKey) {
  const colors = METRICS.find((item) => item.key === metric)!.colors;
  return `linear-gradient(90deg,${colors.map((color, index) => `rgb(${color.join(",")}) ${(index / (colors.length - 1)) * 100}%`).join(",")})`;
}

function localDateTime(value: string | undefined, includeDate = false) {
  if (!value || value.length < 12) return "—";
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const hour = value.slice(8, 10);
  const minute = value.slice(10, 12);
  return includeDate ? `${month}/${day} ${hour}:${minute}` : `${hour}:${minute}`;
}

function dateLabel(value: string) {
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const weekday = "일월화수목금토"[new Date(year, month - 1, day).getDay()];
  return `${month}/${day}(${weekday})`;
}

function condition(row: WeatherRow | undefined) {
  if (!row) return "관측 자료 없음";
  const sky = row.sky == null ? "" : SKY[row.sky] ?? "";
  return row.pty ? `${PTY[row.pty] ?? "강수"}${sky ? ` · ${sky}` : ""}` : sky || "강수 없음";
}

function wind(row: WeatherRow | undefined) {
  if (!row?.wsd && row?.wsd !== 0) return "—";
  const direction = row.vec == null ? "" : `${DIR16[Math.floor(((row.vec % 360) + 360) % 360 / 22.5 + 0.5) % 16]}풍 `;
  return `${direction}${row.wsd.toFixed(1)}m/s`;
}

function temperatureLine(rows: WeatherRow[]) {
  const first = rows.find((row) => row.tmp != null);
  if (!first) return null;
  const forecastEnd = weatherTimestamp(first.t) + 24 * 60 * 60 * 1000;
  const points = rows.filter((row) => row.tmp != null && weatherTimestamp(row.t) <= forecastEnd);
  if (points.length < 2) return null;
  const values = points.map((row) => row.tmp as number);
  const low = Math.min(...values) - 1;
  const high = Math.max(...values) + 1;
  const span = Math.max(high - low, 1);
  const start = weatherTimestamp(points[0].t);
  const end = weatherTimestamp(points[points.length - 1].t);
  const timeSpan = Math.max(1, end - start);
  const coordinates = points.map((row) => `${((weatherTimestamp(row.t) - start) / timeSpan) * 300},${82 - (((row.tmp as number) - low) / span) * 62}`).join(" ");
  return { coordinates, low: low + 1, high: high - 1, points, start, end };
}

function weatherTimestamp(value: string) {
  return Date.UTC(Number(value.slice(0, 4)), Number(value.slice(4, 6)) - 1, Number(value.slice(6, 8)), Number(value.slice(8, 10)), Number(value.slice(10, 12)));
}

function kstTimestamp(now: number) {
  const kst = new Date(now + 9 * 60 * 60 * 1000);
  return Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth(), kst.getUTCDate(), kst.getUTCHours(), kst.getUTCMinutes());
}

function kstClockLabel(timestamp: number) {
  const date = new Date(timestamp);
  return `${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")}`;
}

function dayNightPeriods(start: number, end: number) {
  const periods: { start: number; end: number; kind: "day" | "night" }[] = [];
  let cursor = start;
  while (cursor < end) {
    const next = Math.min(end, (Math.floor(cursor / 3_600_000) + 1) * 3_600_000);
    const hour = new Date(cursor).getUTCHours();
    const kind = hour >= 6 && hour < 18 ? "day" : "night";
    const previous = periods[periods.length - 1];
    if (previous?.kind === kind) previous.end = next;
    else periods.push({ start: cursor, end: next, kind });
    cursor = next;
  }
  const span = Math.max(1, end - start);
  return periods.map((period) => ({ ...period, left: ((period.start - start) / span) * 100, width: ((period.end - period.start) / span) * 100 }));
}

function cameraBox(map: JejuMap, centerX: number, centerY: number, zoom: number): MapBox {
  const factor = Math.max(1, Math.min(MAX_MAP_ZOOM, zoom));
  const w = map.width / factor;
  const h = map.height / factor;
  return {
    x: Math.max(0, Math.min(map.width - w, centerX - w / 2)),
    y: Math.max(0, Math.min(map.height - h, centerY - h / 2)),
    w,
    h,
  };
}

export default function JejuWeatherDashboard({ fetchProtected }: { fetchProtected: ProtectedFetch }) {
  const [map, setMap] = useState<JejuMap | null>(null);
  const [overview, setOverview] = useState<WeatherOverview | null>(null);
  const [selectedArea, setSelectedArea] = useState("남원읍");
  const [detail, setDetail] = useState<WeatherDetail | null>(null);
  const [metric, setMetric] = useState<MetricKey>("tmp");
  const [camera, setCamera] = useState<MapBox | null>(null);
  const [isPanning, setIsPanning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clockNow, setClockNow] = useState(() => Date.now());
  const mapSvgRef = useRef<SVGSVGElement | null>(null);
  const mapShellRef = useRef<HTMLDivElement | null>(null);
  const cameraRef = useRef<MapBox | null>(null);
  const wheelTargetRef = useRef<MapBox | null>(null);
  const gestureRef = useRef<MapGesture | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const wheelAnimationFrameRef = useRef<number | null>(null);
  const suppressAreaClickRef = useRef(false);
  const areaRequestRef = useRef(0);

  const applyCamera = useCallback((next: MapBox) => {
    cameraRef.current = next;
    setCamera(next);
  }, []);

  const animateCamera = useCallback((target: MapBox) => {
    if (!map) return;
    if (animationFrameRef.current != null) cancelAnimationFrame(animationFrameRef.current);
    if (wheelAnimationFrameRef.current != null) cancelAnimationFrame(wheelAnimationFrameRef.current);
    wheelAnimationFrameRef.current = null;
    wheelTargetRef.current = null;
    const start = cameraRef.current ?? { x: 0, y: 0, w: map.width, h: map.height };
    const startedAt = performance.now();
    const duration = 440;
    const step = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      applyCamera({
        x: start.x + (target.x - start.x) * eased,
        y: start.y + (target.y - start.y) * eased,
        w: start.w + (target.w - start.w) * eased,
        h: start.h + (target.h - start.h) * eased,
      });
      if (progress < 1) animationFrameRef.current = requestAnimationFrame(step);
      else animationFrameRef.current = null;
    };
    animationFrameRef.current = requestAnimationFrame(step);
  }, [applyCamera, map]);

  useEffect(() => {
    if (!map) return;
    if (animationFrameRef.current != null) cancelAnimationFrame(animationFrameRef.current);
    if (wheelAnimationFrameRef.current != null) cancelAnimationFrame(wheelAnimationFrameRef.current);
    animationFrameRef.current = null;
    wheelAnimationFrameRef.current = null;
    wheelTargetRef.current = null;
    applyCamera({ x: 0, y: 0, w: map.width, h: map.height });
    return () => {
      if (animationFrameRef.current != null) cancelAnimationFrame(animationFrameRef.current);
      if (wheelAnimationFrameRef.current != null) cancelAnimationFrame(wheelAnimationFrameRef.current);
    };
  }, [applyCamera, map]);

  const zoomAtPoint = useCallback((clientX: number, clientY: number, scale: number) => {
    if (!map || !mapSvgRef.current) return;
    const current = cameraRef.current ?? { x: 0, y: 0, w: map.width, h: map.height };
    const rect = mapSvgRef.current.getBoundingClientRect();
    const rx = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const ry = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    const worldX = current.x + rx * current.w;
    const worldY = current.y + ry * current.h;
    const currentZoom = map.width / current.w;
    const nextZoom = Math.max(1, Math.min(MAX_MAP_ZOOM, currentZoom * scale));
    const nextW = map.width / nextZoom;
    const nextH = map.height / nextZoom;
    animateCamera({
      x: Math.max(0, Math.min(map.width - nextW, worldX - rx * nextW)),
      y: Math.max(0, Math.min(map.height - nextH, worldY - ry * nextH)),
      w: nextW,
      h: nextH,
    });
  }, [animateCamera, map]);

  const zoomMap = useCallback((scale: number) => {
    if (!map || !mapSvgRef.current) return;
    const rect = mapSvgRef.current.getBoundingClientRect();
    zoomAtPoint(rect.left + rect.width / 2, rect.top + rect.height / 2, scale);
  }, [map, zoomAtPoint]);

  const focusArea = useCallback((areaName: string) => {
    if (!map) return;
    const area = map.areas.find((item) => item.name === areaName);
    if (!area) return;
    animateCamera(cameraBox(map, area.lx, area.ly, 3.1));
  }, [animateCamera, map]);

  const selectArea = useCallback((areaName: string) => {
    setSelectedArea(areaName);
    focusArea(areaName);
  }, [focusArea]);

  const beginMapGesture = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    if (animationFrameRef.current != null) cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
    if (wheelAnimationFrameRef.current != null) cancelAnimationFrame(wheelAnimationFrameRef.current);
    wheelAnimationFrameRef.current = null;
    wheelTargetRef.current = null;
    const bounds = map;
    if (!bounds) return;
    const box = cameraRef.current ?? { x: 0, y: 0, w: bounds.width, h: bounds.height };
    gestureRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, startBox: box, moved: false };
  };

  const moveMapGesture = (event: ReactPointerEvent<SVGSVGElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId || !map || !mapSvgRef.current) return;
    const dx = event.clientX - gesture.startX;
    const dy = event.clientY - gesture.startY;
    if (!gesture.moved && Math.hypot(dx, dy) > 4) {
      gesture.moved = true;
      suppressAreaClickRef.current = true;
      setIsPanning(true);
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    if (!gesture.moved) return;
    const rect = mapSvgRef.current.getBoundingClientRect();
    applyCamera({
      ...gesture.startBox,
      x: Math.max(0, Math.min(map.width - gesture.startBox.w, gesture.startBox.x - dx * gesture.startBox.w / rect.width)),
      y: Math.max(0, Math.min(map.height - gesture.startBox.h, gesture.startBox.y - dy * gesture.startBox.h / rect.height)),
    });
  };

  const endMapGesture = (event: ReactPointerEvent<SVGSVGElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    gestureRef.current = null;
    setIsPanning(false);
    if (gesture.moved) window.setTimeout(() => { suppressAreaClickRef.current = false; }, 0);
  };

  const queueWheelZoom = useCallback((clientX: number, clientY: number, scale: number) => {
    if (!map || !mapSvgRef.current) return;
    if (animationFrameRef.current != null) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    const rect = mapSvgRef.current.getBoundingClientRect();
    const rx = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const ry = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    const base = wheelTargetRef.current ?? cameraRef.current ?? { x: 0, y: 0, w: map.width, h: map.height };
    const worldX = base.x + rx * base.w;
    const worldY = base.y + ry * base.h;
    const currentZoom = map.width / base.w;
    const nextZoom = Math.max(1, Math.min(MAX_MAP_ZOOM, currentZoom * scale));
    const nextW = map.width / nextZoom;
    const nextH = map.height / nextZoom;
    wheelTargetRef.current = {
      x: Math.max(0, Math.min(map.width - nextW, worldX - rx * nextW)),
      y: Math.max(0, Math.min(map.height - nextH, worldY - ry * nextH)),
      w: nextW,
      h: nextH,
    };
    if (wheelAnimationFrameRef.current != null) return;
    const step = () => {
      const target = wheelTargetRef.current;
      if (!target) {
        wheelAnimationFrameRef.current = null;
        return;
      }
      const current = cameraRef.current ?? target;
      const next = {
        x: current.x + (target.x - current.x) * 0.28,
        y: current.y + (target.y - current.y) * 0.28,
        w: current.w + (target.w - current.w) * 0.28,
        h: current.h + (target.h - current.h) * 0.28,
      };
      if (Math.abs(target.x - current.x) < 0.35 && Math.abs(target.y - current.y) < 0.35 && Math.abs(target.w - current.w) < 0.35) {
        applyCamera(target);
        wheelTargetRef.current = null;
        wheelAnimationFrameRef.current = null;
        return;
      }
      applyCamera(next);
      wheelAnimationFrameRef.current = requestAnimationFrame(step);
    };
    wheelAnimationFrameRef.current = requestAnimationFrame(step);
  }, [applyCamera, map]);

  const handleMapWheel = useCallback((event: WheelEvent) => {
    event.preventDefault();
    event.stopPropagation();
    const scale = Math.max(0.78, Math.min(1.28, Math.exp(-event.deltaY * 0.001)));
    queueWheelZoom(event.clientX, event.clientY, scale);
  }, [queueWheelZoom]);

  const loadOverview = useCallback(async () => {
    const response = await fetchProtected("/api/backend/dashboard/weather/jeju/map", { cache: "no-store" });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail ?? "제주 날씨를 불러오지 못했습니다.");
    setOverview(body as WeatherOverview);
  }, [fetchProtected]);

  const loadArea = useCallback(async (area: string) => {
    const requestId = ++areaRequestRef.current;
    setDetailLoading(true);
    try {
      const response = await fetchProtected(`/api/backend/dashboard/weather/jeju/area?area=${encodeURIComponent(area)}`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "선택 지역 예보를 불러오지 못했습니다.");
      if (requestId === areaRequestRef.current) {
        setDetail(body as WeatherDetail);
        setError(null);
      }
    } catch (cause) {
      if (requestId === areaRequestRef.current) {
        setDetail(null);
        setError(cause instanceof Error ? cause.message : "선택 지역 예보를 불러오지 못했습니다.");
      }
    } finally {
      if (requestId === areaRequestRef.current) setDetailLoading(false);
    }
  }, [fetchProtected]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await loadOverview();
      await loadArea(selectedArea);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "제주 날씨를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [loadArea, loadOverview, selectedArea]);

  useEffect(() => {
    let active = true;
    async function initialize() {
      try {
        const mapResponse = await fetch("/weather/jeju_areas.json", { cache: "force-cache" });
        if (!mapResponse.ok) throw new Error("제주 행정구역 지도 파일을 불러오지 못했습니다.");
        const mapData = await mapResponse.json();
        if (active) {
          setMap(mapData as JejuMap);
        }
        await loadOverview();
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "제주 날씨를 불러오지 못했습니다.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void initialize();
    return () => { active = false; };
  }, [loadOverview]);

  useEffect(() => {
    if (!map || !overview || !selectedArea) return;
    void loadArea(selectedArea);
  }, [loadArea, map, overview?.updated_at, selectedArea]);

  useEffect(() => {
    if (!overview) return;
    const timer = window.setInterval(() => { void refresh(); }, 20 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [overview?.updated_at, refresh]);

  useEffect(() => {
    const shell = mapShellRef.current;
    if (!shell) return;
    shell.addEventListener("wheel", handleMapWheel, { passive: false });
    return () => shell.removeEventListener("wheel", handleMapWheel);
  }, [handleMapWheel, map]);

  useEffect(() => {
    const timer = window.setInterval(() => setClockNow(Date.now()), 60 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  const areaRows = useMemo(() => (map?.areas ?? []).flatMap((area) => {
    const config = overview?.areas[area.name];
    if (!config) return [];
    const grid = overview?.grids?.[config.grid];
    return [{ name: area.name, config, row: grid?.now?.row ?? null }];
  }), [map, overview]);
  const temperatures = areaRows.filter((item) => item.row?.tmp != null);
  const warmest = temperatures.reduce<typeof temperatures[number] | null>((best, current) => !best || (current.row?.tmp ?? -Infinity) > (best.row?.tmp ?? -Infinity) ? current : best, null);
  const coolest = temperatures.reduce<typeof temperatures[number] | null>((best, current) => !best || (current.row?.tmp ?? Infinity) < (best.row?.tmp ?? Infinity) ? current : best, null);
  const rainyAreas = areaRows.filter((item) => (item.row?.pty ?? 0) > 0 || Boolean(item.row?.pcp && item.row.pcp !== "강수없음"));
  const selectedConfig = overview?.areas[selectedArea];
  const selectedGrid = selectedConfig ? overview?.grids[selectedConfig.grid] : undefined;
  const selectedDetail = detail?.area === selectedArea ? detail : null;
  const currentRow = selectedDetail?.current.rows[0] ?? selectedGrid?.now?.row ?? undefined;
  const nextRows = selectedDetail?.next6h.rows ?? [];
  const selectedForecast = selectedDetail?.forecast5d;
  const chart = useMemo(() => temperatureLine(selectedForecast?.rows ?? []), [selectedForecast]);
  const popupCurrent = currentRow;
  const currentTime = kstTimestamp(clockNow);
  const chartNowRatio = chart ? Math.max(0, Math.min(1, (currentTime - chart.start) / Math.max(1, chart.end - chart.start))) : null;
  const chartPeriods = chart ? dayNightPeriods(chart.start, chart.end) : [];
  const fullCamera = map ? { x: 0, y: 0, w: map.width, h: map.height } : null;
  const visibleCamera = camera ?? fullCamera;
  const mapZoom = map && visibleCamera ? map.width / visibleCamera.w : 1;
  const mapViewBox = visibleCamera ? `${visibleCamera.x} ${visibleCamera.y} ${visibleCamera.w} ${visibleCamera.h}` : undefined;
  const popupPop = selectedGrid?.forecast?.pop ?? nextRows.find((row) => row.pop != null)?.pop ?? null;

  return <div className="jeju-weather-view">
    <section className="weather-map-card">
      <div className="weather-section-title">
        <div><h2>제주 읍면동 날씨</h2></div>
        <div className="weather-freshness"><span className={overview ? "weather-live-dot" : "weather-muted-dot"}>●</span><span>{overview?.updated_at ? `갱신 ${localDateTime(overview.updated_at.replace(/[-:TZ+]/g, "").slice(0, 12), true)}${overview.cache?.stale ? " · 지연" : ""}` : loading ? "불러오는 중" : ""}</span><button type="button" onClick={() => void refresh()} disabled={loading || detailLoading}>새로고침</button></div>
      </div>
      <div className="weather-metrics" role="group" aria-label="지도 색상 기준">
        {METRICS.map((item) => <button key={item.key} type="button" className={metric === item.key ? "active" : ""} aria-pressed={metric === item.key} onClick={() => setMetric(item.key)}>{item.label}</button>)}
      </div>
      <div className="weather-place-chips" role="group" aria-label="남원읍 주변 대표 위치">
        {["남원읍", "공천포"].map((name) => <button key={name} type="button" className={selectedArea === name ? "active" : ""} aria-pressed={selectedArea === name} onClick={() => selectArea(name)}>{name}</button>)}
      </div>
      <div ref={mapShellRef} className="jeju-map-shell">
        {map && <div className="weather-map-zoom" role="group" aria-label="지도 확대/축소">
          <button type="button" onClick={() => zoomMap(1 / 1.35)} disabled={mapZoom <= 1.01} aria-label="지도 축소" title="지도 축소">−</button>
          <span>{Math.round(mapZoom * 100)}%</span>
          <button type="button" onClick={() => zoomMap(1.35)} disabled={mapZoom >= MAX_MAP_ZOOM - 0.01} aria-label="지도 확대" title="지도 확대">+</button>
          <button className="weather-map-zoom-reset" type="button" onClick={() => fullCamera && animateCamera(fullCamera)} disabled={mapZoom <= 1.01}>초기화</button>
        </div>}
        {map ? <svg ref={mapSvgRef} className={`jeju-map ${isPanning ? "panning" : ""}`} viewBox={mapViewBox} role="group" aria-label="제주 읍면동 날씨 지도" onPointerDown={beginMapGesture} onPointerMove={moveMapGesture} onPointerUp={endMapGesture} onPointerCancel={endMapGesture} onPointerLeave={endMapGesture}>
          <rect x="0" y="0" width={map.width} height={map.height} rx="18" fill="#e8f1ea" />
          <rect x={map.inset.x} y={map.inset.y} width={map.inset.w} height={map.inset.h} rx="10" fill="none" stroke="#9daf9d" strokeDasharray="7 6" />
          {map.areas.map((area) => {
            const config = overview?.areas[area.name];
            const grid = config ? overview?.grids[config.grid] : undefined;
            const value = weatherValue(grid, metric);
            return <g key={area.code} className={`jeju-map-area ${selectedArea === area.name ? "selected" : ""}`} role="button" tabIndex={0} aria-label={`${area.name}, ${metricText(value, metric)}`} onClick={() => { if (!suppressAreaClickRef.current) selectArea(area.name); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectArea(area.name); } }}>
              <path d={area.d} fill={metricColor(metric, value)} />
              <text x={area.lx} y={area.ly - 5} textAnchor="middle">{area.name}</text>
              {area.w > 62 && area.h > 32 && <text className="jeju-map-value" x={area.lx} y={area.ly + 10} textAnchor="middle">{metricText(value, metric)}</text>}
            </g>;
          })}
          <text className="jeju-map-inset-label" x={map.inset.x + 8} y={map.inset.y + map.inset.h - 8}>{map.inset.label}</text>
        </svg> : <div className="jeju-map-placeholder">{error ?? "제주 지도 준비 중…"}</div>}
        {map && <aside className="weather-map-popup" aria-live="polite">
          <div className="weather-map-popup-heading"><div><small>선택 지역</small><strong>{selectedArea}</strong></div><span>{popupCurrent ? condition({ ...popupCurrent, sky: popupCurrent.sky ?? nextRows[0]?.sky ?? null }) : detailLoading ? "조회 중" : "자료 없음"}</span></div>
          <div className="weather-map-popup-metrics">
            <div><small>기온</small><strong>{popupCurrent?.tmp == null ? "—" : `${popupCurrent.tmp.toFixed(1)}°C`}</strong></div>
            <div><small>강수확률</small><strong>{popupPop == null ? "—" : `${popupPop}%`}</strong></div>
            <div><small>풍속</small><strong>{wind(popupCurrent)}</strong></div>
            <div><small>습도</small><strong>{popupCurrent?.reh == null ? "—" : `${popupCurrent.reh}%`}</strong></div>
          </div>
        </aside>}
        <div className="weather-map-legend"><strong>{METRICS.find((item) => item.key === metric)?.label}</strong><div className="weather-legend-gradient" style={{ background: metricGradient(metric) }} /><div><span>{METRICS.find((item) => item.key === metric)?.min}{METRICS.find((item) => item.key === metric)?.unit}</span><span>{METRICS.find((item) => item.key === metric)?.max}{METRICS.find((item) => item.key === metric)?.unit}</span></div></div>
      </div>
      <div className="jeju-map-attribution">{map?.attribution}</div>
      {overview?.cache?.stale && <p className="weather-note">기상 자료 갱신이 지연되어 이전 자료를 표시 중입니다.</p>}
      <div className="weather-island-summary"><div><small>기상청 관측 격자</small><strong>{temperatures.length} / {areaRows.length} 지역</strong></div><div><small>강수 관측 지역</small><strong>{rainyAreas.length}곳</strong></div><div><small>가장 따뜻한 곳</small><strong>{warmest ? `${warmest.name} ${warmest.row?.tmp?.toFixed(1)}°C` : "—"}</strong></div><div><small>가장 서늘한 곳</small><strong>{coolest ? `${coolest.name} ${coolest.row?.tmp?.toFixed(1)}°C` : "—"}</strong></div></div>
    </section>

    <section className="weather-detail-card">
      <div className="weather-detail-heading"><div><h2>{selectedArea}</h2><p>{selectedArea === "공천포" ? "서귀포시 남원읍 신례리 · 공천포구 인근" : `제주특별자치도 ${map?.areas.find((area) => area.name === selectedArea)?.sgg ?? ""}`} · {selectedDetail?.updated_at ? `갱신 ${localDateTime(selectedDetail.updated_at.replace(/[-:TZ+]/g, "").slice(0, 12), true)}` : detailLoading ? "조회 중" : ""}</p></div>{detailLoading && <span className="weather-source-pill">조회 중</span>}</div>
      {selectedDetail?.cache?.stale && <p className="weather-note">기상 자료 갱신이 지연되어 이전 자료를 표시 중입니다.</p>}
      {overview?.errors?.[selectedConfig?.grid ?? ""] && <p className="weather-note">일부 관측 자료를 받지 못했습니다. {overview.errors[selectedConfig?.grid ?? ""]}</p>}
      {error && <p className="weather-error">{error}</p>}
      {!error && !currentRow && <p className="weather-empty">{detailLoading ? "선택 지역의 기상 정보를 가져오는 중입니다…" : "표시할 관측 자료가 없습니다."}</p>}
      {currentRow && <>
        <div className="weather-current-card"><div><small>현재 관측 · {localDateTime(currentRow.t, true)}</small><div className="weather-current-main"><strong>{currentRow.tmp == null ? "—" : `${currentRow.tmp.toFixed(1)}°`}</strong><span>{condition({ ...currentRow, sky: currentRow.sky ?? nextRows[0]?.sky ?? null })}</span></div></div><div className="weather-current-stats"><span>습도 <b>{currentRow.reh == null ? "—" : `${currentRow.reh}%`}</b></span><span>강수 <b>{currentRow.pcp ?? "없음"}</b></span><span>바람 <b>{wind(currentRow)}</b></span></div></div>
        <div className="weather-card"><div className="weather-card-heading"><h3>향후 6시간</h3><span>발표 {localDateTime(selectedDetail?.next6h.base)}</span></div><div className="weather-hours">{nextRows.map((row) => <div className="weather-hour" key={row.t}><small>{localDateTime(row.t, row.t.slice(0, 8) !== currentRow.t.slice(0, 8))}</small><span>{row.pty ? "🌧" : row.sky === 4 ? "☁" : row.sky === 3 ? "⛅" : "☀"}</span><b>{row.tmp == null ? "—" : `${Math.round(row.tmp)}°`}</b><small>{row.pcp ?? (row.pty ? condition(row) : "강수 없음")}</small></div>)}</div></div>
        {chart && <div className="weather-card"><div className="weather-card-heading"><h3>기온·강수확률</h3><span>단기예보 · {localDateTime(selectedForecast?.base)}</span></div><div className="weather-temp-plot"><span className="weather-temp-label weather-temp-high">{chart.high}°</span><svg className="weather-temp-chart" viewBox="0 0 300 96" preserveAspectRatio="none" aria-label="다음 24시간 기온과 강수확률 추이"><line x1="0" x2="300" y1="48" y2="48" />{chart.points.map((point) => {
          const x = ((weatherTimestamp(point.t) - chart.start) / Math.max(1, chart.end - chart.start)) * 300;
          const height = point.pop == null ? 0 : Math.max(2, point.pop * 0.38);
          return height ? <rect key={point.t} className="weather-pop-bar" x={x - 3.5} y={93 - height} width="7" height={height} rx="2" /> : null;
        })}{chartNowRatio != null && <line className="weather-now-line" x1={chartNowRatio * 300} x2={chartNowRatio * 300} y1="0" y2="96" />}<polyline points={chart.coordinates} /></svg><span className="weather-temp-label weather-temp-low">{chart.low}°</span></div><div className="weather-temp-axis"><span>{localDateTime(chart.points[0]?.t)}</span><span>{kstClockLabel((chart.start + chart.end) / 2)}</span><span>{localDateTime(chart.points[chart.points.length - 1]?.t)}</span></div><div className="weather-day-night-strip" aria-label="낮과 밤"><div className="weather-day-night-band">{chartPeriods.map((period) => <span key={`${period.start}-${period.end}`} className={`weather-day-night-segment ${period.kind}`} style={{ left: `${period.left}%`, width: `${period.width}%` }}>{period.width > 9 ? period.kind === "day" ? "낮" : "밤" : ""}</span>)}</div>{chartNowRatio != null && <i className={`weather-current-marker ${chartNowRatio < 0.08 ? "at-start" : chartNowRatio > 0.92 ? "at-end" : ""}`} style={{ left: `${chartNowRatio * 100}%` }}><b>현재 {kstClockLabel(currentTime)}</b></i>}</div><div className="weather-chart-legend"><i className="temperature" />기온 <i className="precipitation" />강수확률 <span>· 다음 24시간</span></div></div>}
        {!!selectedForecast?.daily?.length && <div className="weather-card"><div className="weather-card-heading"><h3>일별 예보</h3><span>강수확률·시간대별 전망 · 최대 5일</span></div><div className="weather-days">{selectedForecast.daily.map((day) => {
          const dayRows = selectedForecast.rows.filter((row) => row.t.startsWith(day.date) && (row.pop != null || row.pty != null));
          return <article className="weather-day" key={day.date}>
            <div className="weather-day-heading"><div><strong>{dateLabel(day.date)}</strong><small>{[day.sky == null ? "" : SKY[day.sky] ?? "", day.rain?.kinds ?? "강수 없음"].filter(Boolean).join(" · ")}</small></div><strong>{day.tmin == null ? "—" : `${Math.round(day.tmin)}°`} / {day.tmax == null ? "—" : `${Math.round(day.tmax)}°`}</strong><span>{day.pop == null ? "—" : `${day.pop}%`}</span></div>
            <div className="weather-day-chart" role="img" aria-label={`${dateLabel(day.date)} 시간대별 강수확률. 막대 높이가 강수확률을 나타냅니다.`}>
              <div className="weather-day-plot"><div className="weather-day-y-axis"><span>100%</span><span>50%</span><span>0%</span></div><div className="weather-day-rain-track">{dayRows.map((row) => {
                const hour = Number(row.t.slice(8, 10)) + Number(row.t.slice(10, 12)) / 60;
                const chance = row.pop ?? 0;
                const weatherText = row.pty ? PTY[row.pty] ?? "강수" : "강수 없음";
                return <i key={row.t} className={`weather-rain-marker ${row.pty ? "wet" : "dry"}`} style={{ left: `${(hour / 24) * 100}%`, height: `${Math.max(4, Math.min(100, chance) * 0.52)}px` }} title={`${hour.toFixed(0)}시 · ${weatherText} · 강수확률 ${chance}%`} />;
              })}</div></div>
              <div className="weather-day-axis"><span aria-hidden="true" /><div className="weather-day-axis-ticks"><span>00시</span><span>06시</span><span>12시</span><span>18시</span><span>24시</span></div></div>
              {dayRows.length === 0 && <small className="weather-day-no-data">시간대별 자료 없음</small>}
            </div>
          </article>;
        })}</div><div className="weather-day-legend"><i className="dry" />막대 높이 = 시간대별 강수확률 <i className="wet" />주황색 = 비·눈 예보</div></div>}
      </>}
    </section>
  </div>;
}
