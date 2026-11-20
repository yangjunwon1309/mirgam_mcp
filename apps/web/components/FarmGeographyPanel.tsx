"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, PointerEvent as ReactPointerEvent } from "react";
import SavedFarmMap from "./SavedFarmMap";
import { useBeaconFleet } from "./beacon/BeaconFleetProvider";

type GeoPoint = [number, number];
type Geometry = { type: string; coordinates: unknown };
type ZoomImage = { min_x: number; max_x: number; min_y: number; max_y: number; pixel_left: number; pixel_top: number; pixel_right: number; pixel_bottom: number; width: number; height: number; image_available?: boolean };
type TilePyramid = { min_zoom: number; max_zoom: number; coverage_aligned?: boolean; generation?: string; zooms: Record<string, ZoomImage> };
type Boundary = { id: string; version: number; geojson: Geometry; area_m2: number; perimeter_m: number; edges: { from: number; to: number; length_m: number; azimuth_deg: number }[]; imagery?: { status: string; job_id: string | null; progress: number; error: string | null; available: boolean; tiles_available?: boolean; transform: { zoom?: number; width?: number; height?: number; tile_pyramid?: TilePyramid } | null } };
type FarmRoute = { id: string; boundary_id: string; label: string | null; geojson: Geometry; length_m: number };
type Farm = { id: string; name: string; address_input: string | null; pnu: string | null; latest_boundary: Boundary | null; routes: FarmRoute[] };
type SensorOption = { sensor_id: string; display_name: string; sensor_type: string };
type CameraOption = { camera_id: string; display_name: string };
type ParcelFeature = { type: "Feature"; geometry: Geometry; properties?: Record<string, unknown>; pnu?: string };
type FetchProtected = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type Props = {
  farmName: string;
  fetchProtected: FetchProtected;
  sensors: SensorOption[];
  cameras: CameraOption[];
  selectedSensorId: string | null;
  selectedCameraId: string | null;
  dashboardMode: "sensor" | "camera";
  onSelectSensor: (id: string) => void;
  onSelectCamera: (id: string) => void;
};

const API = "/api/backend/api/v1";
const ATTRIBUTION = "출처: 브이월드, 국토교통부";

function worldPixel([lon, lat]: GeoPoint, zoom: number): GeoPoint {
  const scale = 256 * 2 ** zoom;
  const clampedLat = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const sin = Math.sin((clampedLat * Math.PI) / 180);
  return [((lon + 180) / 360) * scale, ((0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale)];
}

function geoPoint([x, y]: GeoPoint, zoom: number): GeoPoint {
  const scale = 256 * 2 ** zoom;
  const lon = (x / scale) * 360 - 180;
  const n = Math.PI - (2 * Math.PI * y) / scale;
  const lat = (180 / Math.PI) * Math.atan(Math.sinh(n));
  return [lon, lat];
}

function normalizeGeoJsonGeometry(geometry: Geometry): Geometry {
  function normalizeCoordinates(value: unknown): unknown {
    if (!Array.isArray(value)) return value;
    if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
      const [x, y, ...rest] = value as number[];
      if (Math.abs(x) > 180 || Math.abs(y) > 90) {
        const lon = (x / 6378137) * (180 / Math.PI);
        const lat = (2 * Math.atan(Math.exp(y / 6378137)) - Math.PI / 2) * (180 / Math.PI);
        return [lon, lat, ...rest];
      }
      return value;
    }
    return value.map(normalizeCoordinates);
  }
  return { ...geometry, coordinates: normalizeCoordinates(geometry.coordinates) };
}

function polygonRings(geometry: Geometry | null | undefined): GeoPoint[][] {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return (geometry.coordinates as GeoPoint[][]) ?? [];
  if (geometry.type === "MultiPolygon") return ((geometry.coordinates as GeoPoint[][][]) ?? []).flat();
  return [];
}

function linePoints(geometry: Geometry | null | undefined): GeoPoint[] {
  if (!geometry || geometry.type !== "LineString") return [];
  return (geometry.coordinates as GeoPoint[]) ?? [];
}

function mapError(body: unknown, fallback: string) {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export default function FarmGeographyPanel(props: Props) {
  const { farmName, fetchProtected } = props;
  const fleet = useBeaconFleet();
  const farms = fleet.farms as unknown as Farm[];
  const selectedFarmId = fleet.farmId;
  const setSelectedFarmId = fleet.setFarmId;
  const reloadFarms = fleet.reloadFarms;
  const [isCreatingFarm, setIsCreatingFarm] = useState(false);
  const [farmDraftName, setFarmDraftName] = useState(farmName);
  const [address, setAddress] = useState("");
  const [geocoded, setGeocoded] = useState<GeoPoint | null>(null);
  const [pnu, setPnu] = useState<string | null>(null);
  const [parcel, setParcel] = useState<ParcelFeature | null>(null);
  const [center, setCenter] = useState<GeoPoint>([126.5, 33.3]);
  const [zoom, setZoom] = useState(16);
  const [minZoom, setMinZoom] = useState(13);
  const [maxZoom, setMaxZoom] = useState(19);
  const [layer, setLayer] = useState<"Satellite" | "Hybrid">("Satellite");
  const [mode, setMode] = useState<"pan" | "boundary" | "route" | "parcel">("pan");
  const [boundaryDraft, setBoundaryDraft] = useState<GeoPoint[]>([]);
  const [routeDraft, setRouteDraft] = useState<GeoPoint[]>([]);
  const [routeLabel, setRouteLabel] = useState("");
  const [setupOpen, setSetupOpen] = useState(false);
  const [mapSize, setMapSize] = useState({ width: 800, height: 420 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tileError, setTileError] = useState(false);
  const mapRef = useRef<HTMLDivElement | null>(null);
  const savedMapSectionRef = useRef<HTMLDivElement | null>(null);
  const pointerRef = useRef<{ x: number; y: number; moved: boolean; world: GeoPoint | null } | null>(null);
  const vertexDragRef = useRef<{ kind: "boundary" | "route"; index: number } | null>(null);
  const lastGeocodedFarmRef = useRef<string | null>(null);

  const selectedFarm = farms.find((farm) => farm.id === selectedFarmId) ?? null;
  const boundary = selectedFarm?.latest_boundary ?? null;

  const beacons = fleet.nodes.map((node) => ({ node_id: node.node_id, label: node.label, metadata: { location: node.metadata?.location } }));
  const beaconPlacementNodeId = fleet.placement?.nodeId ?? null;
  const receiveBeaconLocation = useCallback((nodeId: string, point: GeoPoint) => fleet.completePlacement(nodeId, point), [fleet.completePlacement]);
  const selectBeaconOnMap = useCallback((nodeId: string) => fleet.openData(nodeId), [fleet.openData]);
  useEffect(() => {
    if (fleet.placement) window.requestAnimationFrame(() => savedMapSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, [fleet.placement?.nodeId]);

  const setMapMode = useCallback((nextMode: "pan" | "boundary" | "route" | "parcel") => {
    pointerRef.current = null;
    vertexDragRef.current = null;
    setMode(nextMode);
  }, []);

  useEffect(() => {
    if (!selectedFarmId) return;
    setBoundaryDraft([]); setRouteDraft([]);
  }, [selectedFarmId]);

  useEffect(() => {
    let active = true;
    void fetchProtected(`${API}/health`).then(async (response) => {
      if (!response.ok) return;
      const data = await response.json();
      const configuredMin = Number(data.satellite_min_zoom);
      const configuredMax = Number(data.satellite_max_zoom);
      if (active && Number.isFinite(configuredMin)) setMinZoom(Math.max(3, Math.min(20, configuredMin)));
      if (active && Number.isFinite(configuredMax)) setMaxZoom(Math.max(3, Math.min(22, configuredMax)));
    }).catch(() => { /* Keep the configured default zoom if health is unavailable. */ });
    return () => { active = false; };
  }, [fetchProtected]);

  useEffect(() => {
    setZoom((current) => Math.max(minZoom, Math.min(current, maxZoom)));
  }, [maxZoom, minZoom]);

  useEffect(() => { setTileError(false); }, [center, layer, zoom]);

  useEffect(() => {
    const node = mapRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      setMapSize({ width: Math.max(1, entry.contentRect.width), height: Math.max(1, entry.contentRect.height) });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [setupOpen]);

  useEffect(() => {
    if (!selectedFarm) return;
    setFarmDraftName(selectedFarm.name);
    setAddress(selectedFarm.address_input ?? "");
    setPnu(selectedFarm.pnu ?? null);
    if (!boundary) {
      if (selectedFarm.address_input && lastGeocodedFarmRef.current !== selectedFarm.id) {
        const farmId = selectedFarm.id;
        lastGeocodedFarmRef.current = farmId;
        let active = true;
        void fetchProtected(`${API}/vworld/geocode?address=${encodeURIComponent(selectedFarm.address_input)}&type=parcel`)
          .then(async (response) => {
            const data = await response.json();
            if (!active || !response.ok) return;
            const location: GeoPoint = [Number(data.lon), Number(data.lat)];
            if (location.every(Number.isFinite)) {
              setGeocoded(location); setCenter(location); setZoom(maxZoom);
            }
          })
          .catch(() => { /* The farm remains editable and the map can be moved manually. */ });
        return () => { active = false; };
      }
      return;
    }
    const ring = polygonRings(boundary.geojson)[0] ?? [];
    if (!ring.length) return;
    const avg: GeoPoint = [ring.reduce((sum, point) => sum + point[0], 0) / ring.length, ring.reduce((sum, point) => sum + point[1], 0) / ring.length];
    setCenter(avg);
    setZoom((current) => Math.min(maxZoom, Math.max(current, 17)));
    setAddress(selectedFarm?.address_input ?? "");
    setBoundaryDraft([]);
    setRouteDraft([]);
  }, [boundary?.id, selectedFarm?.id, selectedFarm?.name, selectedFarm?.address_input, selectedFarm?.pnu, fetchProtected, maxZoom]);

  useEffect(() => {
    const jobId = boundary?.imagery?.job_id;
    if (!jobId || boundary?.imagery?.status === "done" || boundary?.imagery?.status === "failed") return;
    let active = true;
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const response = await fetchProtected(`${API}/jobs/${encodeURIComponent(jobId)}`);
        if (!response.ok) return;
        const job = await response.json();
        if (!active) return;
        await reloadFarms();
        if (job.status === "done" || job.status === "failed") {
          if (timer !== undefined) window.clearInterval(timer);
          if (job.status === "failed") setError(String(job.error || "위성영상 크롭에 실패했습니다."));
        }
      } catch { /* Keep the saved boundary visible while the worker is polled. */ }
    };
    timer = window.setInterval(() => { void refresh(); }, 2000);
    void refresh();
    return () => { active = false; if (timer !== undefined) window.clearInterval(timer); };
  }, [boundary?.imagery?.job_id, boundary?.imagery?.status, fetchProtected, reloadFarms]);

  const tiles = useMemo(() => {
    const centerWorld = worldPixel(center, zoom);
    const left = centerWorld[0] - mapSize.width / 2;
    const top = centerWorld[1] - mapSize.height / 2;
    const minX = Math.floor(left / 256);
    const maxX = Math.floor((left + mapSize.width) / 256);
    const minY = Math.floor(top / 256);
    const maxY = Math.floor((top + mapSize.height) / 256);
    const output: { x: number; y: number; left: number; top: number }[] = [];
    for (let y = minY; y <= maxY; y += 1) {
      if (y < 0 || y >= 2 ** zoom) continue;
      for (let x = minX; x <= maxX; x += 1) {
        if (x < 0 || x >= 2 ** zoom) continue;
        output.push({ x, y, left: x * 256 - left, top: y * 256 - top });
      }
    }
    return { output, left, top, centerWorld };
  }, [center, mapSize.height, mapSize.width, zoom]);

  const project = useCallback((point: GeoPoint): GeoPoint => {
    const world = worldPixel(point, zoom);
    return [world[0] - tiles.left, world[1] - tiles.top];
  }, [tiles.left, tiles.top, zoom]);

  const mapCoordinates = useCallback((clientX: number, clientY: number): GeoPoint => {
    const bounds = mapRef.current?.getBoundingClientRect();
    if (!bounds) return center;
    const world: GeoPoint = [tiles.left + (clientX - bounds.left), tiles.top + (clientY - bounds.top)];
    return geoPoint(world, zoom);
  }, [center, tiles.left, tiles.top, zoom]);

  async function geocodeAddress(event?: FormEvent) {
    event?.preventDefault();
    if (!address.trim()) return;
    setMapMode("pan");
    setBusy(true); setError(null); setParcel(null); setPnu(null);
    try {
      const response = await fetchProtected(`${API}/vworld/geocode?address=${encodeURIComponent(address.trim())}&type=parcel`);
      const data = await response.json();
      if (!response.ok) throw new Error(mapError(data, "주소를 찾지 못했습니다."));
      const location: GeoPoint = [Number(data.lon), Number(data.lat)];
      setGeocoded(location); setCenter(location); setZoom(maxZoom); setMapMode("pan");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "주소를 검색하지 못했습니다.");
    } finally { setBusy(false); }
  }

  async function createFarm() {
    if (!farmDraftName.trim()) return;
    setMapMode("pan");
    setBusy(true); setError(null);
    try {
      const response = await fetchProtected(`${API}/farms`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: farmDraftName.trim(), address_input: address.trim() || null, pnu }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(mapError(data, "농장을 등록하지 못했습니다."));
      if (geocoded) lastGeocodedFarmRef.current = data.id;
      setIsCreatingFarm(false);
      await reloadFarms();
      setSelectedFarmId(data.id);
      if (geocoded) setCenter(geocoded);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "농장을 등록하지 못했습니다.");
    } finally { setBusy(false); }
  }

  function selectFarm(id: string | null) {
    setMapMode("pan"); setBoundaryDraft([]); setRouteDraft([]);
    setIsCreatingFarm(!id); setSelectedFarmId(id);
    setGeocoded(null); setParcel(null); setPnu(farms.find((farm) => farm.id === id)?.pnu ?? null);
    lastGeocodedFarmRef.current = null;
    if (!id) { setFarmDraftName(farmName); setAddress(""); setSetupOpen(true); }
  }

  function startNewFarm() {
    setIsCreatingFarm(true); setSelectedFarmId(null);
    setFarmDraftName(farmName); setAddress(""); setPnu(null); setGeocoded(null); setParcel(null);
    setBoundaryDraft([]); setRouteDraft([]); setMapMode("pan"); setError(null); setSetupOpen(true);
  }

  async function updateFarm() {
    if (!selectedFarm || !farmDraftName.trim()) return;
    setMapMode("pan");
    setBusy(true); setError(null);
    try {
      const response = await fetchProtected(`${API}/farms/${encodeURIComponent(selectedFarm.id)}`, {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: farmDraftName.trim(), address_input: address.trim() || null, pnu }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(mapError(data, "농장 정보를 저장하지 못했습니다."));
      await reloadFarms();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "농장 정보를 저장하지 못했습니다.");
    } finally { setBusy(false); }
  }

  async function lookupParcel(point: GeoPoint) {
    setMapMode("pan");
    setBusy(true); setError(null);
    try {
      const response = await fetchProtected(`${API}/vworld/parcel?lon=${point[0]}&lat=${point[1]}`);
      const data = await response.json();
      if (!response.ok) throw new Error(mapError(data, "필지 정보를 찾지 못했습니다."));
      if (!data.geometry || typeof data.geometry !== "object") throw new Error("필지 경계 도형이 응답에 없습니다.");
      setParcel({ ...(data as ParcelFeature), geometry: normalizeGeoJsonGeometry(data.geometry as Geometry) });
      setGeocoded(point);
      const returnedPnu = typeof data.pnu === "string" ? data.pnu : typeof data.properties?.pnu === "string" ? data.properties.pnu : null;
      setPnu(returnedPnu);
      setMapMode("pan");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "필지 정보를 찾지 못했습니다.");
    } finally { setBusy(false); }
  }

  async function saveBoundary() {
    if (!selectedFarm || boundaryDraft.length < 3) return;
    setMapMode("pan");
    setBusy(true); setError(null);
    try {
      const response = await fetchProtected(`${API}/farms/${selectedFarm.id}/boundaries`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ coordinates: boundaryDraft, imagery_zoom: Math.min(maxZoom, zoom) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(mapError(data, "농장 경계를 저장하지 못했습니다."));
      setBoundaryDraft([]); setMapMode("pan"); await reloadFarms();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "농장 경계를 저장하지 못했습니다.");
    } finally { setBusy(false); }
  }

  async function saveRoute() {
    if (!selectedFarm || !boundary || routeDraft.length < 2) return;
    setMapMode("pan");
    setBusy(true); setError(null);
    try {
      const response = await fetchProtected(`${API}/farms/${selectedFarm.id}/routes`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ boundary_id: boundary.id, label: routeLabel.trim() || null, coordinates: routeDraft }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(mapError(data, "작업 경로를 저장하지 못했습니다."));
      setRouteDraft([]); setRouteLabel(""); setMapMode("pan"); await reloadFarms();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "작업 경로를 저장하지 못했습니다.");
    } finally { setBusy(false); }
  }

  async function deleteRoute(routeId: string) {
    if (!selectedFarm) return;
    const response = await fetchProtected(`${API}/routes/${encodeURIComponent(routeId)}`, { method: "DELETE" });
    if (response.ok) await reloadFarms();
    else setError("경로를 삭제하지 못했습니다.");
  }

  async function prepareBoundaryTiles() {
    if (!boundary) return;
    setMapMode("pan");
    setBusy(true); setError(null);
    try {
      const response = await fetchProtected(`${API}/boundaries/${encodeURIComponent(boundary.id)}/tiles/rebuild?force=true`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(mapError(data, "배율별 지도 이미지 작업을 시작하지 못했습니다."));
      await reloadFarms();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "배율별 지도 이미지 작업을 시작하지 못했습니다.");
    } finally { setBusy(false); }
  }

  function startBoundaryEdit() {
    if (mode === "boundary") {
      setMapMode("pan");
      return;
    }
    if (!boundaryDraft.length) {
      const old = boundary ? polygonRings(boundary.geojson)[0] ?? [] : [];
      const openRing = old.length > 1 && old[0][0] === old.at(-1)?.[0] && old[0][1] === old.at(-1)?.[1] ? old.slice(0, -1) : old;
      setBoundaryDraft(openRing.map((point) => [...point] as GeoPoint));
    }
    setRouteDraft([]); setMapMode("boundary"); setError(null);
  }

  function startRouteEdit() {
    setRouteDraft([]); setRouteLabel(""); setMapMode("route"); setError(null);
  }

  function onMapPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const canPan = mode === "pan" || mode === "parcel";
    pointerRef.current = { x: event.clientX, y: event.clientY, moved: false, world: canPan ? tiles.centerWorld : null };
    if (canPan) event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onMapPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const dragVertex = vertexDragRef.current;
    if (dragVertex) {
      const point = mapCoordinates(event.clientX, event.clientY);
      if (dragVertex.kind === "boundary") setBoundaryDraft((current) => current.map((item, index) => index === dragVertex.index ? point : item));
      else setRouteDraft((current) => current.map((item, index) => index === dragVertex.index ? point : item));
      return;
    }
    const pointer = pointerRef.current;
    if (!pointer || (mode !== "pan" && mode !== "parcel")) return;
    const dx = event.clientX - pointer.x; const dy = event.clientY - pointer.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) pointer.moved = true;
    if (!pointer.moved || !pointer.world) return;
    const nextWorld: GeoPoint = [pointer.world[0] - dx, pointer.world[1] - dy];
    setCenter(geoPoint(nextWorld, zoom));
  }

  function onMapPointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (vertexDragRef.current) { vertexDragRef.current = null; pointerRef.current = null; return; }
    const pointer = pointerRef.current; pointerRef.current = null;
    if (mode === "pan" || (pointer?.moved ?? false)) return;
    const point = mapCoordinates(event.clientX, event.clientY);
    if (mode === "boundary") setBoundaryDraft((current) => [...current, point]);
    else if (mode === "route") setRouteDraft((current) => [...current, point]);
    else if (mode === "parcel") void lookupParcel(point);
  }

  const onMapWheel = useCallback((event: WheelEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (busy) return;
    if (mode === "boundary") setMapMode("pan");
    const delta = event.deltaY < 0 ? 1 : -1;
    const next = Math.max(minZoom, Math.min(maxZoom, zoom + delta));
    if (next === zoom) return;
    const bounds = mapRef.current?.getBoundingClientRect();
    if (bounds) {
      const px = event.clientX - bounds.left; const py = event.clientY - bounds.top;
      const anchorGeo = geoPoint([tiles.left + px, tiles.top + py], zoom);
      const anchorNext = worldPixel(anchorGeo, next);
      setCenter(geoPoint([anchorNext[0] - px + mapSize.width / 2, anchorNext[1] - py + mapSize.height / 2], next));
    }
    setZoom(next);
  }, [busy, mapSize.height, mapSize.width, maxZoom, minZoom, mode, setMapMode, tiles.left, tiles.top, zoom]);

  useEffect(() => {
    const node = mapRef.current;
    if (!node) return;
    node.addEventListener("wheel", onMapWheel, { passive: false });
    return () => node.removeEventListener("wheel", onMapWheel);
  }, [onMapWheel]);

  function zoomBy(delta: number) {
    setMapMode("pan");
    setZoom((value) => Math.max(minZoom, Math.min(maxZoom, value + delta)));
  }

  function updateVertex(kind: "boundary" | "route", index: number, event: ReactPointerEvent<SVGElement>) {
    event.stopPropagation();
    if ((kind === "boundary" && mode !== "boundary") || (kind === "route" && mode !== "route")) return;
    vertexDragRef.current = { kind, index };
    event.currentTarget.setPointerCapture(event.pointerId);
    pointerRef.current = null;
  }

  const boundaryPoints = boundaryDraft.length ? boundaryDraft : polygonRings(boundary?.geojson)[0] ?? [];
  const draftLine = mode === "route" ? routeDraft : [];

  return <>
  <section className="plant-view farm-map-panel">
    <div className="farm-map-heading"><div><span className="farm-map-kicker">FIELD MAP</span><h2>농장 지도</h2><p>저장된 위성 타일을 이동하고 배율을 바꿔 농장 경계를 살펴봅니다.</p></div>
      <div className="farm-map-counts"><span>{boundary ? `경계 ${boundary.area_m2.toLocaleString("ko-KR")}m²` : "경계 미등록"}</span><span>경로 {selectedFarm?.routes.length ?? 0}</span></div>
    </div>

    <div className="farm-map-farm-row farm-map-main-select">
      <label>농장<select value={selectedFarmId ?? ""} onChange={(event) => selectFarm(event.target.value || null)}>
        <option value="">새 농장 등록</option>{farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.name}</option>)}
      </select></label>
      <button type="button" className="farm-map-primary" onClick={() => setSetupOpen(true)}>{selectedFarm ? "농장 설정 열기" : "농장 위치·경계 설정"}</button>
    </div>

    <div ref={savedMapSectionRef} className="farm-saved-map-section"><SavedFarmMap farmName={selectedFarm?.name ?? farmName} boundary={boundary} routes={selectedFarm?.routes ?? []} configuredMinZoom={minZoom} configuredMaxZoom={maxZoom} onOpenSetup={() => setSetupOpen(true)} onPrepareTiles={() => void prepareBoundaryTiles()} beacons={beacons.map((node) => ({ node_id: node.node_id, label: node.label, location: node.metadata?.location }))} placementNodeId={beaconPlacementNodeId} onBeaconLocationPicked={receiveBeaconLocation} onCancelPlacement={fleet.cancelPlacement} onSelectBeacon={selectBeaconOnMap} /></div>



    {setupOpen && <div className="farm-map-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) { setMapMode("pan"); setSetupOpen(false); } }}>
      <section className="farm-map-dialog" role="dialog" aria-modal="true" aria-label="농장 위치와 경계 설정"
        onClickCapture={(event) => {
          if (mode !== "boundary") return;
          const target = event.target;
          if (!(target instanceof Element)) return;
          const button = target.closest("button");
          if (!button || button.closest(".farm-map-tools")) return;
          if (button.closest(".farm-map-editor") && !button.hasAttribute("data-exit-boundary-edit")) return;
          setMapMode("pan");
        }}
        onFocusCapture={(event) => {
          if (mode === "boundary" && event.target instanceof HTMLElement && event.target.matches("input, select, textarea") && !event.target.closest(".farm-map-editor")) setMapMode("pan");
        }}>
        <div className="farm-map-dialog-header"><div><span className="farm-map-kicker">VWORLD SETUP</span><h2>농장 위치와 경계 설정</h2><p>농장 정보를 저장하고, 지도 도구를 골라 위치와 경계를 지정합니다.</p></div><button type="button" aria-label="설정 닫기" onClick={() => { setMapMode("pan"); setSetupOpen(false); }}>닫기 ×</button></div>
        <div className="farm-map-setup">
          <div className="farm-map-farm-row">
            <label>등록된 농장<select value={selectedFarmId ?? ""} onChange={(event) => selectFarm(event.target.value || null)}>
              <option value="">새 농장 등록</option>{farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.name}</option>)}
            </select></label>
            <button type="button" onClick={startNewFarm}>＋ 새 농장</button>
          </div>
          <div className="farm-map-entry-card">
            <div className="farm-map-entry-step"><span className="farm-map-step-number">01</span><div className="farm-map-step-content"><div><strong>{isCreatingFarm || !selectedFarm ? "농장 이름" : "농장 정보"}</strong><small>{isCreatingFarm || !selectedFarm ? "로그인한 농장명을 기본값으로 사용합니다." : "이름을 바꾸거나 저장된 주소·필지를 갱신할 수 있습니다."}</small></div><label>농장명<input value={farmDraftName} onChange={(event) => setFarmDraftName(event.target.value)} placeholder="예: 미르감 감귤 농장" /></label></div></div>
            <div className="farm-map-entry-step"><span className="farm-map-step-number">02</span><div className="farm-map-step-content"><div><strong>지번 주소로 위치 찾기</strong><small>주소를 검색하면 지도가 이동합니다. 주소를 모르면 지도를 직접 움직여도 됩니다.</small></div><form className="farm-map-address" onSubmit={geocodeAddress}><label>지번 주소<input value={address} onChange={(event) => setAddress(event.target.value)} placeholder="제주 서귀포시 남원읍 ..." /></label><button type="submit" disabled={busy || !address.trim()}>주소 검색</button></form></div></div>
            <div className="farm-map-entry-footer"><div className="farm-map-entry-status">{selectedFarm?.pnu && !pnu && <span>저장된 필지 PNU · {selectedFarm.pnu}</span>}{pnu && <span>선택 필지 PNU · {pnu}</span>}{geocoded && <span>지도 위치 · {geocoded[1].toFixed(5)}, {geocoded[0].toFixed(5)}</span>}{selectedFarm && !selectedFarm.address_input && <span>저장된 주소 없음</span>}</div>
              {!selectedFarm && <button className="farm-map-primary" type="button" disabled={busy || !farmDraftName.trim()} onClick={() => void createFarm()}>농장 등록</button>}
              {selectedFarm && <button className="farm-map-primary" type="button" disabled={busy || !farmDraftName.trim() || (farmDraftName.trim() === selectedFarm.name && (address.trim() || null) === selectedFarm.address_input && pnu === selectedFarm.pnu)} onClick={() => void updateFarm()}>농장 정보 저장</button>}
            </div>
            {parcel && <div className="farm-map-parcel-selection"><span>지도에서 선택한 필지: {pnu ?? "PNU 정보 없음"}</span><button type="button" onClick={() => { setParcel(null); setPnu(selectedFarm?.pnu ?? null); }}>선택 해제</button></div>}
          </div>

          <div className="farm-map-toolbar" role="toolbar" aria-label="VWorld 경계 편집 도구">
            <div className="farm-map-tools">
              <button type="button" aria-pressed={mode === "pan"} className={mode === "pan" ? "active" : ""} onClick={() => setMapMode("pan")}>지도 이동</button>
              <button type="button" aria-pressed={mode === "boundary"} className={mode === "boundary" ? "active" : ""} disabled={!selectedFarm} onClick={startBoundaryEdit}>{mode === "boundary" ? "경계 편집 종료" : boundary ? "경계 수정" : "경계 그리기"}</button>
              <button type="button" aria-pressed={mode === "route"} className={mode === "route" ? "active" : ""} disabled={!selectedFarm || !boundary} onClick={startRouteEdit}>경로 추가</button>
              <button type="button" aria-pressed={mode === "parcel"} className={mode === "parcel" ? "active" : ""} onClick={() => setMapMode("parcel")}>필지 참고선</button>
            </div>
            <div className="farm-map-layer-switch"><button type="button" className={layer === "Satellite" ? "active" : ""} onClick={() => setLayer("Satellite")}>위성</button><button type="button" className={layer === "Hybrid" ? "active" : ""} onClick={() => setLayer("Hybrid")}>위성 + 지명</button></div>
          </div>
          <div className="farm-map-toolbar-status" role="status"><strong>{mode === "boundary" ? "경계 편집 중" : mode === "route" ? "경로 입력 중" : mode === "parcel" ? "필지 선택 중" : "지도 탐색"}</strong><span>{mode === "boundary" ? "지도에서 꼭짓점을 추가하거나 점을 끌어 조정하세요. 다른 도구를 누르면 편집을 멈춥니다." : mode === "route" ? "지도 클릭 순서가 경로 진행 방향입니다." : mode === "parcel" ? "지도에서 필지를 눌러 참고선을 표시하세요." : boundaryDraft.length ? "경계 편집이 멈췄고 초안은 보존되어 있습니다. 경계 수정 버튼을 눌러 이어서 편집하세요." : "도구를 선택해 경계를 수정하거나 지도를 이동하세요."}</span></div>

          <div className={`farm-map-canvas ${mode !== "pan" ? "drawing" : ""}`} ref={mapRef} onPointerDown={onMapPointerDown} onPointerMove={onMapPointerMove} onPointerUp={onMapPointerUp} onPointerCancel={onMapPointerUp}>
            <div className="farm-map-tiles" aria-hidden="true">
              {tiles.output.map((tile) => <div key={`${tile.x}-${tile.y}`} className="farm-map-tile" style={{ left: tile.left, top: tile.top }}>
                <img src={`${API}/tiles/Satellite/${zoom}/${tile.x}/${tile.y}`} alt="" onError={() => setTileError(true)} />
                {layer === "Hybrid" && <img className="farm-map-hybrid" src={`${API}/tiles/Hybrid/${zoom}/${tile.x}/${tile.y}`} alt="" onError={() => setTileError(true)} />}
              </div>)}
            </div>
            <svg className="farm-map-overlay" viewBox={`0 0 ${mapSize.width} ${mapSize.height}`} preserveAspectRatio="none" aria-label="경계와 작업 경로 초안">
              {parcel && polygonRings(parcel.geometry).map((ring, index) => <polygon key={`parcel-${index}`} points={ring.map((point) => project(point).join(",")).join(" ")} className="farm-parcel-outline" />)}
              {boundaryPoints.length > 1 && <polygon points={boundaryPoints.map((point) => project(point).join(",")).join(" ")} className={boundaryDraft.length ? "farm-boundary-shape draft" : "farm-boundary-shape"} />}
              {mode === "boundary" && boundaryPoints.map((point, index) => { const [x, y] = project(point); return <g key={`boundary-point-${index}`} className="farm-vertex" onPointerDown={(event) => updateVertex("boundary", index, event)}><circle cx={x} cy={y} r="8" /><text x={x} y={y - 13}>{index + 1}</text></g>; })}
              {(selectedFarm?.routes ?? []).map((route) => { const points = linePoints(route.geojson).map(project); return <g key={route.id}><polyline points={points.map((point) => point.join(",")).join(" ")} className="farm-route-line" markerMid="url(#route-arrow)" markerEnd="url(#route-arrow)" /><text x={points[0]?.[0] ?? 0} y={(points[0]?.[1] ?? 0) - 9} className="farm-route-label">{route.label || "작업 경로"} · 진행 →</text></g>; })}
              {routeDraft.length > 1 && <polyline points={routeDraft.map((point) => project(point).join(",")).join(" ")} className="farm-route-line draft" markerMid="url(#route-arrow)" markerEnd="url(#route-arrow)" />}
              {draftLine.map((point, index) => { const [x, y] = project(point); return <g key={`draft-${mode}-${index}`} className="farm-vertex draft-vertex" onPointerDown={(event) => updateVertex(mode === "route" ? "route" : "boundary", index, event)}><circle cx={x} cy={y} r="8" /><text x={x} y={y - 13}>{index + 1}</text></g>; })}
              <defs><marker id="route-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" /></marker></defs>
              {geocoded && <g className="farm-geocode-pin" transform={`translate(${project(geocoded).join(" ")})`}><circle r="13" /><path d="M0 -8 L0 8 M-8 0 L8 0" /></g>}
            </svg>
            <div className="farm-map-zoom"><button type="button" onClick={() => zoomBy(1)} aria-label="확대">＋</button><span>Z{zoom}</span><button type="button" onClick={() => zoomBy(-1)} aria-label="축소">−</button><button type="button" onClick={() => { setMapMode("pan"); setCenter([126.5, 33.3]); setZoom(Math.min(16, maxZoom)); }} aria-label="제주 기본 위치">초기화</button></div>
            {mode === "parcel" && <div className="farm-parcel-hint">지도에서 필지를 누르면 노란 경계와 PNU가 표시됩니다.</div>}
            {tileError && <div className="farm-map-warning">VWorld 지도를 불러오지 못했습니다. 서버의 키와 WMTS 권한을 확인하세요.</div>}
            <div className="farm-map-attribution">{ATTRIBUTION}</div>
          </div>

          {mode === "boundary" && <div className="farm-map-editor"><div><strong>{boundaryDraft.length}개 경계 꼭짓점</strong><small>지도 클릭으로 꼭짓점을 추가하고, 점을 끌어 위치를 조정하세요.</small></div><div className="farm-map-vertex-list">{boundaryDraft.map((point, index) => <button key={`b-${index}`} type="button" onClick={() => setBoundaryDraft((current) => current.filter((_, i) => i !== index))}>점 {index + 1} ×</button>)}</div><div className="farm-map-actions"><button type="button" onClick={() => setBoundaryDraft((current) => current.slice(0, -1))} disabled={!boundaryDraft.length}>마지막 점 취소</button><button type="button" className="farm-map-primary" data-exit-boundary-edit onClick={() => void saveBoundary()} disabled={busy || boundaryDraft.length < 3}>경계 저장 · 지도 만들기</button><button type="button" data-exit-boundary-edit onClick={() => { setBoundaryDraft([]); setMapMode("pan"); }}>취소</button></div></div>}
          {mode === "route" && <div className="farm-map-editor"><label>경로 이름<input value={routeLabel} onChange={(event) => setRouteLabel(event.target.value)} placeholder="예: 1번 통로" /></label><div><strong>{routeDraft.length}개 경로 꼭짓점</strong><small>찍은 순서가 진행 방향입니다. 지도 점을 끌어 수정할 수 있습니다.</small></div><div className="farm-map-vertex-list">{routeDraft.map((point, index) => <button key={`r-${index}`} type="button" onClick={() => setRouteDraft((current) => current.filter((_, i) => i !== index))}>점 {index + 1} ×</button>)}</div><div className="farm-map-actions"><button type="button" onClick={() => setRouteDraft((current) => current.slice(0, -1))} disabled={!routeDraft.length}>마지막 점 취소</button><button type="button" className="farm-map-primary" data-exit-boundary-edit onClick={() => void saveRoute()} disabled={busy || routeDraft.length < 2}>경로 저장</button><button type="button" data-exit-boundary-edit onClick={() => { setRouteDraft([]); setMapMode("pan"); }}>취소</button></div></div>}
          {error && <p className="farm-map-error" role="alert">{error}</p>}
        </div>
      </section>
    </div>}

    {selectedFarm && <div className="farm-map-meta">
      {boundary && <div className="farm-map-boundary-row">
        <div className="farm-map-stat"><span>경계</span><strong>{boundary.area_m2.toLocaleString("ko-KR")} m²</strong><small>둘레 {boundary.perimeter_m.toFixed(1)} m</small></div>
        <details className="farm-map-edges"><summary>경계 변 세부 정보 · {boundary.edges.length}개</summary><div>{boundary.edges.map((edge) => <span key={`${edge.from}-${edge.to}`}>변 {edge.from + 1} · {edge.length_m.toFixed(1)}m · 방위 {edge.azimuth_deg.toFixed(0)}°</span>)}</div></details>
      </div>}
      {(selectedFarm.routes ?? []).map((route) => <div className="farm-map-route-item" key={route.id}><span><b>{route.label || "이름 없는 경로"}</b><small>{route.length_m.toFixed(1)} m · 진행 방향 표시</small></span><button type="button" onClick={() => void deleteRoute(route.id)}>삭제</button></div>)}
    </div>}

    <div className="farm-map-devices"><div><strong>기존 센서·카메라</strong><small>ESP32 Beacon은 지도에 표시되며 Beacon 관리 탭에서 설정할 수 있습니다.</small></div><div className="farm-device-picks">{props.sensors.map((sensor) => <button key={sensor.sensor_id} type="button" className={props.dashboardMode === "sensor" && props.selectedSensorId === sensor.sensor_id ? "active" : ""} onClick={() => props.onSelectSensor(sensor.sensor_id)}>◉ {sensor.display_name}</button>)}{props.cameras.map((camera) => <button key={camera.camera_id} type="button" className={props.dashboardMode === "camera" && props.selectedCameraId === camera.camera_id ? "active camera" : "camera"} onClick={() => props.onSelectCamera(camera.camera_id)}>▣ {camera.display_name}</button>)}{!props.sensors.length && !props.cameras.length && <small>등록된 센서·카메라가 없습니다.</small>}</div></div>
    {error && !setupOpen && <p className="farm-map-error" role="alert">{error}</p>}
  </section>

  </>;
}
