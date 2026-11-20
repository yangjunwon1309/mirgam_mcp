"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

type GeoPoint = [number, number];
type Geometry = { type: string; coordinates: unknown };
type ZoomImage = {
  min_x: number; max_x: number; min_y: number; max_y: number;
  pixel_left: number; pixel_top: number; pixel_right: number; pixel_bottom: number;
  width: number; height: number;
};
type TilePyramid = { min_zoom: number; max_zoom: number; coverage_aligned?: boolean; generation?: string; zooms: Record<string, ZoomImage> };
type Boundary = {
  id: string;
  geojson: Geometry;
  area_m2: number;
  perimeter_m: number;
  imagery?: { status: string; job_id?: string | null; progress: number; error: string | null; tiles_available?: boolean; transform?: { tile_pyramid?: TilePyramid } | null };
};
type FarmRoute = { id: string; label: string | null; geojson: Geometry; length_m: number };
type BeaconMarker = { node_id: string; label: string; location?: { latitude?: number | null; longitude?: number | null } | null };
type Props = {
  farmName: string;
  boundary: Boundary | null;
  routes: FarmRoute[];
  configuredMinZoom: number;
  configuredMaxZoom: number;
  onOpenSetup: () => void;
  onPrepareTiles: () => void;
  beacons: BeaconMarker[];
  placementNodeId: string | null;
  onBeaconLocationPicked: (nodeId: string, point: GeoPoint) => void;
  onCancelPlacement: () => void;
  onSelectBeacon: (nodeId: string) => void;
};

const TILE_API = "/api/backend/api/v1/tiles/Satellite";
const ATTRIBUTION = "출처: 브이월드, 국토교통부";

function worldPixel([lon, lat]: GeoPoint, zoom: number): GeoPoint {
  const scale = 256 * 2 ** zoom;
  const safeLat = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const sin = Math.sin((safeLat * Math.PI) / 180);
  return [((lon + 180) / 360) * scale, (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale];
}

function geoPoint([x, y]: GeoPoint, zoom: number): GeoPoint {
  const scale = 256 * 2 ** zoom;
  const lon = (x / scale) * 360 - 180;
  const n = Math.PI - (2 * Math.PI * y) / scale;
  return [lon, (180 / Math.PI) * Math.atan(Math.sinh(n))];
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

export default function SavedFarmMap({ farmName, boundary, routes, configuredMinZoom, configuredMaxZoom, onOpenSetup, onPrepareTiles, beacons, placementNodeId, onBeaconLocationPicked, onCancelPlacement, onSelectBeacon }: Props) {
  const [center, setCenter] = useState<GeoPoint>([126.5, 33.3]);
  const [zoom, setZoom] = useState(16);
  const [size, setSize] = useState({ width: 800, height: 420 });
  const [tileError, setTileError] = useState(false);
  const [tileRetryKey, setTileRetryKey] = useState(0);
  const mapRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ x: number; y: number; world: GeoPoint; moved: boolean } | null>(null);

  const pyramid = boundary?.imagery?.transform?.tile_pyramid ?? null;
  const minZoom = Math.max(pyramid?.min_zoom ?? 13, configuredMinZoom);
  const maxZoom = Math.min(pyramid?.max_zoom ?? 19, configuredMaxZoom);
  const tileZoom = Math.max(minZoom, Math.min(maxZoom, Math.round(zoom)));
  const zoomCoverage = pyramid?.zooms[String(tileZoom)] ?? null;
  const boundaryReady = Boolean(boundary && boundary.imagery?.tiles_available && pyramid?.coverage_aligned && zoomCoverage);

  useEffect(() => {
    if (!boundary) return;
    setTileError(false);
    const ring = polygonRings(boundary.geojson)[0] ?? [];
    if (ring.length) {
      const centerLon = ring.reduce((sum, point) => sum + point[0], 0) / ring.length;
      const centerLat = ring.reduce((sum, point) => sum + point[1], 0) / ring.length;
      setCenter([centerLon, centerLat]);
    }
    setZoom(Math.max(minZoom, Math.min(maxZoom, 17)));
  }, [boundary?.id, minZoom, maxZoom]);

  useEffect(() => {
    if (boundary?.imagery?.status === "queued" || boundary?.imagery?.status === "running") setTileError(false);
  }, [boundary?.imagery?.status]);

  useEffect(() => { setTileError(false); }, [tileZoom, boundary?.id]);

  useEffect(() => {
    const node = mapRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: Math.max(1, entry.contentRect.width), height: Math.max(1, entry.contentRect.height) });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const constrainCenter = useCallback((point: GeoPoint, atZoom: number): GeoPoint => {
    if (!pyramid) return point;
    const level = Math.max(minZoom, Math.min(maxZoom, Math.round(atZoom)));
    const image = pyramid.zooms[String(level)];
    if (!image) return point;
    const scale = 2 ** (atZoom - level);
    const halfWidth = size.width / (2 * scale);
    const halfHeight = size.height / (2 * scale);
    const world = worldPixel(point, level);
    const minX = image.pixel_left + halfWidth;
    const maxX = image.pixel_right - halfWidth;
    const minY = image.pixel_top + halfHeight;
    const maxY = image.pixel_bottom - halfHeight;
    const x = minX > maxX ? (image.pixel_left + image.pixel_right) / 2 : Math.max(minX, Math.min(maxX, world[0]));
    const y = minY > maxY ? (image.pixel_top + image.pixel_bottom) / 2 : Math.max(minY, Math.min(maxY, world[1]));
    return geoPoint([x, y], level);
  }, [maxZoom, minZoom, pyramid, size.height, size.width]);

  useEffect(() => {
    if (!pyramid) return;
    setCenter((current) => constrainCenter(current, zoom));
  }, [constrainCenter, pyramid, zoom]);

  const mapLayer = useMemo(() => {
    const scale = 2 ** (zoom - tileZoom);
    const centerAtZoom = worldPixel(center, zoom);
    const centerAtTileZoom = worldPixel(center, tileZoom);
    const tileLeft = centerAtTileZoom[0] - size.width / (2 * scale);
    const tileTop = centerAtTileZoom[1] - size.height / (2 * scale);
    const tileRight = tileLeft + size.width / scale;
    const tileBottom = tileTop + size.height / scale;
    const minX = Math.max(0, Math.floor(tileLeft / 256));
    const maxX = Math.min(2 ** tileZoom - 1, Math.floor(tileRight / 256));
    const minY = Math.max(0, Math.floor(tileTop / 256));
    const maxY = Math.min(2 ** tileZoom - 1, Math.floor(tileBottom / 256));
    const visibleTiles: { x: number; y: number; left: number; top: number; size: number }[] = [];
    for (let y = minY; y <= maxY; y += 1) {
      for (let x = minX; x <= maxX; x += 1) {
        visibleTiles.push({
          x, y,
          left: x * 256 * scale - (centerAtZoom[0] - size.width / 2),
          top: y * 256 * scale - (centerAtZoom[1] - size.height / 2),
          size: 256 * scale,
        });
      }
    }
    return {
      tiles: visibleTiles,
      overlayLeft: centerAtZoom[0] - size.width / 2,
      overlayTop: centerAtZoom[1] - size.height / 2,
    };
  }, [center, size.height, size.width, tileZoom, zoom]);

  const project = useCallback((point: GeoPoint): GeoPoint => {
    const world = worldPixel(point, zoom);
    return [world[0] - mapLayer.overlayLeft, world[1] - mapLayer.overlayTop];
  }, [mapLayer.overlayLeft, mapLayer.overlayTop, zoom]);

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !boundary) return;
    if (event.target instanceof Element && event.target.closest("button")) return;
    dragRef.current = { x: event.clientX, y: event.clientY, world: worldPixel(center, zoom), moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const previous = dragRef.current;
    if (!previous || !pyramid) return;
    const deltaX = event.clientX - previous.x;
    const deltaY = event.clientY - previous.y;
    if (!previous.moved && Math.hypot(deltaX, deltaY) < 4) return;
    previous.moved = true;
    setCenter(constrainCenter(geoPoint([previous.world[0] - deltaX, previous.world[1] - deltaY], zoom), zoom));
  }

  function endDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const previous = dragRef.current;
    dragRef.current = null;
    if (!previous || previous.moved || !placementNodeId || !mapRef.current) return;
    const bounds = mapRef.current.getBoundingClientRect();
    const pixelX = Math.max(0, Math.min(size.width, event.clientX - bounds.left));
    const pixelY = Math.max(0, Math.min(size.height, event.clientY - bounds.top));
    const worldCenter = worldPixel(center, zoom);
    const point = geoPoint([
      worldCenter[0] - size.width / 2 + pixelX,
      worldCenter[1] - size.height / 2 + pixelY,
    ], zoom);
    onBeaconLocationPicked(placementNodeId, point);
  }

  const onWheel = useCallback((event: WheelEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (!boundaryReady || !mapRef.current) return;
    const bounds = mapRef.current.getBoundingClientRect();
    const px = event.clientX - bounds.left;
    const py = event.clientY - bounds.top;
    const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaMode === 2 ? event.deltaY * size.height : event.deltaY;
    const nextZoom = Math.max(minZoom, Math.min(maxZoom, zoom - delta * 0.0025));
    if (Math.abs(nextZoom - zoom) < 0.001) return;
    const currentLeft = worldPixel(center, zoom)[0] - size.width / 2;
    const currentTop = worldPixel(center, zoom)[1] - size.height / 2;
    const anchor = geoPoint([currentLeft + px, currentTop + py], zoom);
    const nextAnchor = worldPixel(anchor, nextZoom);
    const nextCenter = geoPoint([nextAnchor[0] - px + size.width / 2, nextAnchor[1] - py + size.height / 2], nextZoom);
    setCenter(constrainCenter(nextCenter, nextZoom));
    setZoom(nextZoom);
  }, [boundaryReady, center, constrainCenter, maxZoom, minZoom, size.height, size.width, zoom]);

  useEffect(() => {
    const node = mapRef.current;
    if (!node) return;
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [onWheel]);

  function zoomBy(delta: number) {
    const nextZoom = Math.max(minZoom, Math.min(maxZoom, zoom + delta));
    setCenter((current) => constrainCenter(current, nextZoom));
    setZoom(nextZoom);
  }

  const rings = polygonRings(boundary?.geojson);

  return <div className="farm-saved-map-wrap">
    <div className="farm-saved-map-toolbar"><div><strong>{boundary ? `경계 ${boundary.area_m2.toLocaleString("ko-KR")}m²` : "농장 경계가 없습니다"}</strong><small>{boundaryReady ? "Z13에 포함된 주변 지역 안에서 이동하고 휠로 확대·축소합니다." : boundary?.imagery?.status === "failed" ? boundary.imagery.error || "지도 범위 준비에 실패했습니다." : "농장 설정에서 위치와 경계를 등록하면 지도가 준비됩니다."}</small></div><button type="button" onClick={onOpenSetup}>{boundary ? "농장 위치·경계 수정" : "농장 위치·경계 설정"}</button></div>
    <div className={`farm-saved-map-canvas${placementNodeId ? " placing-beacon" : ""}`} ref={mapRef} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={() => { dragRef.current = null; }}>
      <div className="farm-saved-map-tiles" aria-hidden="true">
        {boundaryReady && mapLayer.tiles.map((tile) => <img key={`${tileZoom}-${tile.x}-${tile.y}-${tileRetryKey}`} src={`${TILE_API}/${tileZoom}/${tile.x}/${tile.y}?v=${encodeURIComponent(pyramid?.generation ?? boundary?.imagery?.job_id ?? "")}&r=${tileRetryKey}`} alt="" draggable={false} style={{ left: tile.left, top: tile.top, width: tile.size, height: tile.size }} onError={() => setTileError(true)} />)}
      </div>
      {boundaryReady && <svg className="farm-saved-map-overlay" viewBox={`0 0 ${size.width} ${size.height}`} preserveAspectRatio="none" aria-label="저장된 농장 경계와 작업 경로">
        {rings.map((ring, index) => <polygon key={`boundary-${index}`} points={ring.map((point) => project(point).join(",")).join(" ")} className="farm-boundary-shape" />)}
        {routes.map((route) => { const points = linePoints(route.geojson).map(project); return <g key={route.id}><polyline points={points.map((point) => point.join(",")).join(" ")} className="farm-route-line" markerMid="url(#saved-route-arrow)" markerEnd="url(#saved-route-arrow)" /><text x={points[0]?.[0] ?? 0} y={(points[0]?.[1] ?? 0) - 9} className="farm-route-label">{route.label || "작업 경로"} · 진행 →</text></g>; })}
        <defs><marker id="saved-route-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" /></marker></defs>
      </svg>}
      {boundary && beacons.map((beacon) => {
        const lat = beacon.location?.latitude;
        const lon = beacon.location?.longitude;
        if (typeof lat !== "number" || typeof lon !== "number" || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
        const [x, y] = project([lon, lat]);
        if (x < -30 || y < -30 || x > size.width + 30 || y > size.height + 30) return null;
        return <button key={beacon.node_id} type="button" className={`farm-beacon-map-marker${placementNodeId === beacon.node_id ? " placing" : ""}`} style={{ left: x, top: y }} title={`${beacon.label} · ${beacon.node_id}`} onPointerDown={(event) => { if (!placementNodeId) event.stopPropagation(); }} onClick={(event) => { event.stopPropagation(); if (!placementNodeId) onSelectBeacon(beacon.node_id); }}><span>⌁</span><small>{beacon.label}</small></button>;
      })}
      {placementNodeId && <div className="farm-beacon-placement-hint">{boundary ? "Beacon을 설치할 지점을 지도에서 클릭하세요" : "위치를 선택하려면 먼저 농장 경계를 등록하세요"} <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={onCancelPlacement}>취소</button></div>}
      <div className="farm-saved-map-controls"><button type="button" onClick={() => zoomBy(1)} disabled={!boundaryReady} aria-label="확대">＋</button><span>Z{zoom.toFixed(1)}</span><button type="button" onClick={() => zoomBy(-1)} disabled={!boundaryReady} aria-label="축소">−</button></div>
      <div className="farm-map-attribution">{ATTRIBUTION}</div>
      {tileError && boundaryReady && <div className="farm-saved-map-retry"><span>위성 지도를 불러오지 못했습니다.</span><button type="button" onClick={() => { setTileError(false); setTileRetryKey((value) => value + 1); }}>다시 불러오기</button></div>}
      {!boundary && <div className="farm-saved-map-empty"><strong>{farmName}의 지도 경계를 등록하세요</strong><small>VWorld 팝업에서 농장 주소를 찾고 경계 꼭짓점을 지정할 수 있습니다.</small><button type="button" onClick={onOpenSetup}>위치·경계 설정</button></div>}
      {boundary && !boundaryReady && <div className="farm-saved-map-empty"><strong>{boundary.imagery?.status === "failed" ? "지도 범위 준비에 실패했습니다" : boundary.imagery?.status === "done" ? "기존 지도의 범위를 다시 설정합니다" : "농장 주변 지도를 준비하고 있습니다"}</strong><small>{boundary.imagery?.status === "running" ? `${Math.round((boundary.imagery.progress ?? 0) * 100)}% 완료` : boundary.imagery?.status === "failed" ? boundary.imagery.error : boundary.imagery?.status === "done" ? "기존 경계를 유지하면서 Z13 화면에 주변 지역이 포함되도록 다시 설정합니다." : "Z13 주변 범위를 기준으로 Z13–19 위성 타일을 준비합니다."}</small>{boundary.imagery?.status !== "queued" && boundary.imagery?.status !== "running" && <button type="button" onClick={boundary.imagery?.status === "done" || boundary.imagery?.status === "failed" || boundary.imagery?.status === "not_requested" ? onPrepareTiles : onOpenSetup}>{boundary.imagery?.status === "done" || boundary.imagery?.status === "failed" || boundary.imagery?.status === "not_requested" ? "지도 범위 준비" : "농장 설정"}</button>}</div>}
    </div>
  </div>;
}
