"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

type GeoPoint = [number, number];
type Location = { site?: string | null; zone?: string | null; row?: string | null; position?: string | null; latitude?: number | null; longitude?: number | null };
type BeaconMetadata = { label?: string; location?: Location; installed_at?: string | null; hardware?: Record<string, unknown>; sensors?: SensorInfo[] };
type SensorInfo = { sensor_id?: string; type?: string; model?: string; address?: string | number; location?: string; enabled?: boolean; fields?: string[]; units?: Record<string, string> };
type BeaconNode = {
  node_id: string; state: string; online: boolean; registered: boolean; farm_id?: string | null; label: string;
  metadata: BeaconMetadata; interval_s: number; requested_data: string[]; last_seen?: number | null;
  last_ip?: string | null; last_rssi?: number | null; last_vbat_mv?: number | null; last_seq?: number | null;
  last_ch?: number | null; fw?: string | null; pending_commands: number; next_expected_at?: number | null;
};
type Reading = { value: number; unit: string; recorded_at: string; quality?: string | null };
type SensorEntry = { device: { sensor_id: string; display_name: string; sensor_type: string; unit: string; metadata: Record<string, unknown> }; latest_reading: Reading | null; readings: Reading[] };
type ImageEntry = { asset_id: string; captured_at: string; width?: number; height?: number; byte_size?: number; content_type?: string };
type CommandEntry = { command_id: number; command_type: string; state: string; reason?: string | null; created_at?: number | null; done_at?: number | null; result?: Record<string, unknown> | null; image_asset_id?: string | null };
type BeaconDetail = { node: BeaconNode; profile: { farm_id?: string | null; metadata: BeaconMetadata; interval_s: number; requested_data: string[] }; sensors: SensorEntry[]; images: ImageEntry[]; commands: CommandEntry[]; checkins: Record<string, unknown>[] };
type UsbPort = { port: string; kind: string; label?: string };
type Props = {
  onOpenData: (nodeId: string, sensorId?: string) => void;
  farmId: string | null;
  farmName: string;
  hasFarmBoundary: boolean;
  fetchProtected: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
  placementNodeId: string | null;
  pickedLocation: { nodeId: string; point: GeoPoint; nonce: number } | null;
  selectedMapBeaconId: string | null;
  onNodesChange: (nodes: BeaconNode[]) => void;
  onPlacementStart: (nodeId: string) => void;
  onPlacementCancel: () => void;
  onMapBeaconConsumed: () => void;
};

const BASE = "/api/backend/dashboard/beacons";

function formatTime(value?: string | number | null) {
  if (value == null) return "기록 없음";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return "기록 없음";
  return new Intl.DateTimeFormat("ko-KR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function addressHex(value?: string | number) {
  if (value === undefined || value === null || value === "") return "주소 미상";
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? `0x${number.toString(16).padStart(2, "0")} · ${number}` : String(value);
}

async function readResponse(response: Response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : "요청을 완료하지 못했습니다.";
    throw new Error(detail);
  }
  return data;
}

function locationSummary(location?: Location | null) {
  if (!location) return "설치 위치 미지정";
  const coordinates = typeof location.latitude === "number" && typeof location.longitude === "number"
    ? `${location.latitude.toFixed(5)}, ${location.longitude.toFixed(5)}`
    : null;
  return [...[location.site, location.zone, location.row, location.position].filter(Boolean), ...(coordinates ? [coordinates] : [])].join(" · ") || "설치 위치 미지정";
}

export default function BeaconDashboard(props: Props) {
  const { farmId, farmName, hasFarmBoundary, fetchProtected, onNodesChange, onMapBeaconConsumed, onPlacementCancel, onPlacementStart, onOpenData } = props;
  const [nodes, setNodes] = useState<BeaconNode[]>([]);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const [settingsNodeId, setSettingsNodeId] = useState<string | null>(null);
  const [returnToSettingsNodeId, setReturnToSettingsNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BeaconDetail | null>(null);
  const [energy, setEnergy] = useState<Record<string, unknown> | null>(null);
  const [selectedSensorId, setSelectedSensorId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [usbPorts, setUsbPorts] = useState<UsbPort[]>([]);
  const [usbReachable, setUsbReachable] = useState<boolean | null>(null);
  const [usbLoading, setUsbLoading] = useState(false);
  const [resettingPort, setResettingPort] = useState<string | null>(null);
  const [intervalText, setIntervalText] = useState("300");
  const [requestedSensor, setRequestedSensor] = useState(true);
  const [requestedImage, setRequestedImage] = useState(false);
  const [draft, setDraft] = useState<BeaconMetadata>({ label: "", location: {}, hardware: {}, sensors: [] });

  const loadNodes = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const response = await fetchProtected(`${BASE}${farmId ? `?farm_id=${encodeURIComponent(farmId)}` : ""}`, { cache: "no-store" });
      const data = await readResponse(response) as { reachable: boolean; error?: string; nodes: BeaconNode[] };
      setReachable(data.reachable);
      setNodes(data.nodes ?? []);
      onNodesChange((data.nodes ?? []).filter((node) => node.registered && node.farm_id === farmId));
      if (!data.reachable) setNotice(data.error || "Beacon 서버에 연결할 수 없습니다. 저장된 장치 정보만 표시합니다.");
      else setNotice(null);
    } catch (error) {
      setReachable(false);
      setNotice(error instanceof Error ? error.message : "장치 목록을 불러오지 못했습니다.");
    } finally { if (showSpinner) setLoading(false); }
  }, [farmId, fetchProtected, onNodesChange]);

  const loadUsbPorts = useCallback(async (showSpinner = false) => {
    if (showSpinner) setUsbLoading(true);
    try {
      const response = await fetchProtected(`${BASE}/usb`, { cache: "no-store" });
      const data = await readResponse(response) as { reachable: boolean; ports: UsbPort[] };
      setUsbReachable(data.reachable);
      setUsbPorts(data.ports ?? []);
    } catch {
      setUsbReachable(false);
      setUsbPorts([]);
    } finally { if (showSpinner) setUsbLoading(false); }
  }, [fetchProtected]);

  useEffect(() => { void loadNodes(true); void loadUsbPorts(true); const timer = window.setInterval(() => { void loadNodes(); }, 10000); return () => window.clearInterval(timer); }, [loadNodes, loadUsbPorts]);

  useEffect(() => {
    setSettingsNodeId(null);
    setReturnToSettingsNodeId(null);
    onPlacementCancel();
  }, [farmId, onPlacementCancel]);

  const { selectedMapBeaconId, pickedLocation, placementNodeId } = props;

  useEffect(() => {
    if (selectedMapBeaconId) {
      setSelectedNodeId(selectedMapBeaconId);
      onOpenData(selectedMapBeaconId);
      onMapBeaconConsumed();
    }
  }, [selectedMapBeaconId, onMapBeaconConsumed, onOpenData]);

  useEffect(() => {
    if (pickedLocation && pickedLocation.nodeId === returnToSettingsNodeId) {
      const [longitude, latitude] = pickedLocation.point;
      setDraft((current) => ({ ...current, location: { ...(current.location ?? {}), longitude, latitude } }));
      setNotice(`설치 위치를 선택했습니다 (${latitude.toFixed(6)}, ${longitude.toFixed(6)}). 저장을 눌러 반영하세요.`);
      setSettingsNodeId(pickedLocation.nodeId);
      setReturnToSettingsNodeId(null);
      onMapBeaconConsumed();
    } else if (returnToSettingsNodeId && !placementNodeId) {
      setSettingsNodeId(returnToSettingsNodeId);
      setReturnToSettingsNodeId(null);
    }
  }, [pickedLocation, onMapBeaconConsumed, placementNodeId, returnToSettingsNodeId]);

  useEffect(() => {
    if (!selectedNodeId) { setDetail(null); setEnergy(null); return; }
    let active = true;
    const loadDetail = async () => {
      try {
        const response = await fetchProtected(`${BASE}/${encodeURIComponent(selectedNodeId)}`, { cache: "no-store" });
        const data = await readResponse(response) as BeaconDetail;
        if (active) { setDetail(data); setSelectedSensorId((current) => current && data.sensors.some((sensor) => sensor.device.sensor_id === current) ? current : data.sensors[0]?.device.sensor_id ?? null); }
      } catch (error) { if (active) setNotice(error instanceof Error ? error.message : "장치 데이터를 불러오지 못했습니다."); }
    };
    const loadEnergy = async () => {
      try { const response = await fetchProtected(`${BASE}/${encodeURIComponent(selectedNodeId)}/energy`, { cache: "no-store" }); if (response.ok && active) setEnergy(await response.json()); }
      catch { /* Energy estimates are optional when the Beacon server is offline. */ }
    };
    void loadDetail(); void loadEnergy();
    const timer = window.setInterval(() => { void loadDetail(); }, 7000);
    return () => { active = false; window.clearInterval(timer); };
  }, [fetchProtected, selectedNodeId]);

  const selectedNode = nodes.find((node) => node.node_id === selectedNodeId) ?? detail?.node ?? null;
  const availableNodes = useMemo(() => nodes.filter((node) => !node.registered || node.farm_id === farmId), [farmId, nodes]);

  function openSettings(node: BeaconNode) {
    setSettingsNodeId(node.node_id);
    setDraft({ ...(node.metadata ?? {}), label: node.label ?? node.node_id, location: { ...(node.metadata?.location ?? {}), site: node.metadata?.location?.site ?? farmName }, hardware: { ...(node.metadata?.hardware ?? {}) }, sensors: [...(node.metadata?.sensors ?? [])] });
    setIntervalText(String(node.interval_s || 300));
    setRequestedSensor((node.requested_data ?? ["sensor"]).includes("sensor"));
    setRequestedImage((node.requested_data ?? []).includes("image"));
    setNotice(null);
  }

  function startMapPlacement(nodeId: string) {
    if (!hasFarmBoundary) {
      setNotice("Beacon 위치를 찍으려면 먼저 농장 지도에서 경계를 등록하세요.");
      return;
    }
    setReturnToSettingsNodeId(nodeId);
    setSettingsNodeId(null);
    onPlacementStart(nodeId);
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settingsNodeId || !farmId) return;
    if (typeof draft.location?.latitude !== "number" || typeof draft.location?.longitude !== "number") { setNotice("농장 지도에서 Beacon 설치 위치를 먼저 선택하세요."); return; }
    const interval = Number(intervalText);
    if (!Number.isInteger(interval) || interval < 60 || interval > 14400) { setNotice("수집 주기는 60~14,400초 사이의 정수로 입력하세요."); return; }
    const requested = [requestedSensor ? "sensor" : null, requestedImage ? "image" : null].filter((value): value is string => Boolean(value));
    setSaving(true); setNotice(null);
    try {
      await readResponse(await fetchProtected(`${BASE}/${encodeURIComponent(settingsNodeId)}/configure`, {
        method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({ farm_id: farmId, metadata: { ...draft, label: draft.label?.trim() || settingsNodeId, location: { ...draft.location, site: draft.location?.site ?? farmName } }, interval_s: interval, requested_data: requested, attach: true }),
      }));
      setSettingsNodeId(null); onPlacementCancel(); await loadNodes(true);
      setSelectedNodeId(settingsNodeId);
      setNotice("Beacon 연결 설정을 저장했습니다. 센서 명령은 다음 체크인 때 전달될 수 있습니다.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "연결 설정을 저장하지 못했습니다."); }
    finally { setSaving(false); }
  }

  async function command(nodeId: string, type: "sensor" | "image") {
    setNotice(null);
    try {
      const response = await fetchProtected(`${BASE}/${encodeURIComponent(nodeId)}/commands`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ type, fs: "VGA", q: 12, warm: 500 }),
      });
      const data = await readResponse(response);
      setNotice(`${type === "sensor" ? "센서 읽기" : "카메라 촬영"} 명령 #${data.command_id}을 대기열에 넣었습니다. 장치가 다음에 체크인할 때 실행됩니다.`);
      setSelectedNodeId(nodeId);
      window.setTimeout(() => { void loadNodes(); }, 800);
    } catch (error) { setNotice(error instanceof Error ? error.message : "명령을 요청하지 못했습니다."); }
  }

  async function action(nodeId: string, actionName: "detach" | "watch" | "session" | "hibernate") {
    if (actionName === "hibernate" && !window.confirm("Beacon을 절전 상태로 보낼까요? 다음 수동 깨우기 전까지 데이터 수집이 멈춥니다.")) return;
    try {
      await readResponse(await fetchProtected(`${BASE}/${encodeURIComponent(nodeId)}/actions/${actionName}`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(actionName === "watch" ? { minutes: 10 } : actionName === "session" ? { hold_s: 60 } : {}),
      }));
      setNotice(actionName === "detach" ? "장치 연결을 해제했습니다." : `${actionName} 요청을 보냈습니다.`);
      await loadNodes(true);
    } catch (error) { setNotice(error instanceof Error ? error.message : "장치 요청에 실패했습니다."); }
  }

  async function resetUsbPort(portId: string) {
    const beforeSeen = new Map(nodes.map((node) => [node.node_id, node.last_seen ?? 0]));
    setResettingPort(portId);
    setNotice(`${portId}로 ESP32 리셋 신호를 보내고 Wi-Fi 재접속을 확인합니다.`);
    try {
      await readResponse(await fetchProtected(`${BASE}/usb/${encodeURIComponent(portId)}/reset`, {
        method: "POST", headers: { "content-type": "application/json" }, body: "{}",
      }));
      const deadline = Date.now() + 45000;
      let confirmed = false;
      while (Date.now() < deadline) {
        await new Promise((resolve) => window.setTimeout(resolve, 1800));
        const data = await readResponse(await fetchProtected(`${BASE}${farmId ? `?farm_id=${encodeURIComponent(farmId)}` : ""}`, { cache: "no-store" })) as { reachable: boolean; nodes: BeaconNode[] };
        setReachable(data.reachable);
        setNodes(data.nodes ?? []);
        onNodesChange((data.nodes ?? []).filter((node) => node.registered && node.farm_id === farmId));
        const returned = (data.nodes ?? []).some((node) => Boolean(node.last_seen && node.last_seen > (beforeSeen.get(node.node_id) ?? 0) + 0.5));
        if (returned) { confirmed = true; break; }
      }
      setNotice(confirmed ? `${portId} 리셋 신호를 보낸 후 새 Beacon 체크인이 감지되었습니다. 포트와 장치의 연결 관계는 확인되지 않았습니다.` : `${portId}에 리셋 신호를 보냈습니다. 아직 새 체크인이 없습니다. Wi-Fi 설정과 서버 주소를 확인하세요.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "USB 리셋 또는 연결 확인에 실패했습니다.");
    } finally { setResettingPort(null); }
  }

  return <section className="beacon-dashboard" aria-label="ESP32 Beacon 관리 및 데이터">
    <header className="beacon-heading"><div><span className="farm-map-kicker">ESP32 · FARM NETWORK</span><h3>Beacon 센서 관리</h3><p>{farmId ? `${farmName} 장치 연결과 수신 데이터` : "Beacon을 연결하려면 먼저 농장을 등록하세요."}</p></div><div className="beacon-heading-actions"><span className={`beacon-link-state ${reachable ? "online" : reachable === false ? "offline" : ""}`}><i />{reachable ? "수신 서버 연결됨" : reachable === false ? "서버 연결 확인 필요" : "연결 확인 중"}</span><button type="button" onClick={() => { void loadNodes(true); void loadUsbPorts(true); }} disabled={loading || usbLoading}>{loading || usbLoading ? "확인 중…" : "상태 새로고침"}</button><button type="button" disabled={!selectedNode} onClick={() => { if (selectedNode) openSettings(selectedNode); }}>선택 장치 설정</button><button type="button" className="farm-map-primary" disabled={!farmId} onClick={() => { setDiscoveryOpen(true); void loadNodes(true); }}>＋ 연결 가능한 Beacon</button></div></header>

    {notice && <div className="beacon-notice" role="status">{notice}<button type="button" onClick={() => setNotice(null)} aria-label="알림 닫기">×</button></div>}
    {<section className="beacon-runtime-card" aria-label="Beacon 수신 서버와 USB 연결">
      <div className="beacon-runtime-summary"><span className={`beacon-runtime-icon ${reachable ? "online" : ""}`}>⌁</span><div><small>DOCKER SERVICE · NODE API</small><strong>ESP32 수신 서버</strong><span>Wi-Fi 체크인 :8080 · 관리 API는 내부 네트워크 전용</span></div><span className={`beacon-runtime-state ${reachable ? "online" : reachable === false ? "offline" : ""}`}><i />{reachable ? "실행 중" : reachable === false ? "연결 불가" : "확인 중"}</span></div>
      <div className="beacon-usb-area"><div className="beacon-usb-title"><div><strong>USB 직렬 포트</strong><small>ESP32에 연결한 USB 케이블과 리셋 신호를 확인합니다.</small></div><button type="button" onClick={() => void loadUsbPorts(true)} disabled={usbLoading}>{usbLoading ? "검색 중…" : "포트 새로고침"}</button></div>
        {usbReachable === false ? <p className="beacon-usb-empty">Beacon 컨테이너에 연결할 수 없습니다. Docker 서비스 상태를 확인하세요.</p> : usbPorts.length ? <div className="beacon-usb-ports">{usbPorts.map((port) => <article key={port.port}><span className="beacon-usb-port-icon">USB</span><div><strong>{port.label || `/dev/${port.port}`}</strong><small>/dev/{port.port} · {port.kind}</small></div><button type="button" onClick={() => void resetUsbPort(port.port)} disabled={resettingPort !== null}>{resettingPort === port.port ? "재접속 확인 중…" : "리셋 후 연결 확인"}</button></article>)}</div> : <p className="beacon-usb-empty">USB 직렬 포트(/dev/ttyUSB* 또는 /dev/ttyACM*)가 보이지 않습니다. ESP32를 Jetson USB에 연결한 뒤 포트를 새로고침하세요. USB 리셋은 보드만 재시작하며 Wi-Fi 설정은 변경하지 않습니다.</p>}
      </div>
    </section>}
    {<div className="beacon-layout">
      <div className="beacon-device-list"><div className="beacon-list-title"><strong>등록된 Beacon</strong><small>장치가 체크인한 시각과 상태를 표시합니다.</small></div>
        {nodes.filter((node) => node.registered && node.farm_id === farmId).map((node) => <button type="button" key={node.node_id} className={`beacon-device-card${selectedNodeId === node.node_id ? " active" : ""}`} onClick={() => setSelectedNodeId(node.node_id)}><span className={`beacon-device-dot${node.online ? " online" : ""}`} /><span className="beacon-card-copy"><strong>{node.label}</strong><small>{node.node_id} · {locationSummary(node.metadata?.location)}</small><small>{node.online ? "온라인" : "오프라인"} · 체크인 {formatTime(node.last_seen)}</small></span><span className="beacon-card-state">{node.pending_commands ? `${node.pending_commands} 대기` : node.state}</span></button>)}
        {!nodes.some((node) => node.registered && node.farm_id === farmId) && <div className="beacon-empty">아직 이 농장에 연결된 Beacon이 없습니다.<button type="button" onClick={() => setDiscoveryOpen(true)} disabled={!farmId}>현재 체크인한 장치 찾기</button></div>}
      </div>
      <div className="beacon-device-detail">{selectedNode ? <>
        <div className="beacon-detail-head"><div><strong>{selectedNode.label}</strong><small>{selectedNode.node_id} · {locationSummary(selectedNode.metadata?.location)}</small></div><button type="button" onClick={() => openSettings(selectedNode)}>설정</button></div>
        <div className="beacon-facts"><div><small>상태</small><strong>{selectedNode.online ? "온라인" : selectedNode.state}</strong></div><div><small>마지막 체크인</small><strong>{formatTime(selectedNode.last_seen)}</strong></div><div><small>RSSI · 배터리 보고</small><strong>{selectedNode.last_rssi ?? "—"} dBm · {selectedNode.last_vbat_mv ? `${(selectedNode.last_vbat_mv / 1000).toFixed(2)} V` : "—"}</strong></div><div><small>펌웨어 · 수집 주기</small><strong>{selectedNode.fw ?? "—"} · {selectedNode.interval_s}s</strong></div></div>
        <div className="beacon-quick-actions"><button type="button" onClick={() => onOpenData(selectedNode.node_id)}>데이터 서버 열기</button><button type="button" onClick={() => void command(selectedNode.node_id, "sensor")} disabled={!selectedNode.registered || !selectedNode.online}>센서 읽기 요청</button><button type="button" onClick={() => void command(selectedNode.node_id, "image")} disabled={!selectedNode.registered || !selectedNode.online}>카메라 촬영</button><button type="button" onClick={() => void action(selectedNode.node_id, "session")} disabled={!selectedNode.registered}>1분 응답 대기</button><button type="button" onClick={() => void action(selectedNode.node_id, "watch")} disabled={!selectedNode.registered}>10분간 자주 확인</button><button type="button" onClick={() => void action(selectedNode.node_id, "hibernate")} disabled={!selectedNode.registered}>절전</button><button type="button" onClick={() => void action(selectedNode.node_id, "detach")} disabled={!selectedNode.registered}>연결 해제</button></div>
        <div className="beacon-subheading"><strong>설치 센서</strong><span>{detail?.sensors.length ?? selectedNode.metadata?.sensors?.length ?? 0}종</span></div>
        {(detail?.sensors.length ?? 0) > 0 ? <div className="beacon-sensor-pills">{detail?.sensors.map((sensor) => <button type="button" key={sensor.device.sensor_id} onClick={() => { setSelectedSensorId(sensor.device.sensor_id); onOpenData(selectedNode.node_id, sensor.device.sensor_id); }}>{sensor.device.display_name} <b>{sensor.latest_reading ? `${sensor.latest_reading.value} ${sensor.latest_reading.unit}` : "수집 대기"}</b></button>)}</div> : <p className="beacon-muted">센서 결과가 도착하면 장치의 실제 센서 종류와 값이 여기에 표시됩니다.</p>}
        <div className="beacon-energy"><div><strong>전력 사용 추정</strong><small>Beacon 서버의 설정 가정에 따른 계산값이며 실측 전력은 아닙니다.</small></div><span>{typeof energy?.estimated_mAh_day === "number" ? `${energy.estimated_mAh_day} mAh/일` : "자료 없음"}</span>{typeof energy?.estimated_days_remaining === "number" && <small>추정 잔여 {energy.estimated_days_remaining}일</small>}</div>
      </> : <div className="beacon-empty">장치를 선택하거나 <button type="button" onClick={() => setDiscoveryOpen(true)}>새 Beacon을 찾으세요.</button></div>}</div>
    </div>}

    {discoveryOpen && <div className="beacon-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDiscoveryOpen(false); }}>
      <section className="beacon-modal beacon-discovery-modal" role="dialog" aria-modal="true" aria-labelledby="beacon-discovery-title">
        <header><div><span className="beacon-dialog-eyebrow">BEACON 장치 연결</span><h3 id="beacon-discovery-title">연결할 장치 선택</h3><p>같은 네트워크에서 서버에 체크인한 장치를 선택하세요.</p></div><button type="button" className="beacon-dialog-close" aria-label="닫기" onClick={() => setDiscoveryOpen(false)}>×</button></header>
        <div className="beacon-discovery-summary"><div><strong>사용 가능한 장치</strong><span>{availableNodes.length}개 발견</span></div><button type="button" onClick={() => void loadNodes(true)} disabled={loading}>{loading ? "확인 중…" : "↻ 새로고침"}</button></div>
        <div className="beacon-discovery-list">{availableNodes.map((node) => <button type="button" className="beacon-discovery-row" key={node.node_id} onClick={() => { setDiscoveryOpen(false); openSettings(node); }}>
          <span className="beacon-device-avatar" aria-hidden="true">⌁</span><span className="beacon-discovery-copy"><strong>{node.label}</strong><small>{node.node_id} · {node.last_ip ?? "IP 미확인"}</small><small>최근 체크인 {formatTime(node.last_seen)}</small></span><span className={`beacon-discovery-status${node.online ? " online" : ""}`}>{node.online ? "온라인" : "오프라인"}</span><span className="beacon-discovery-arrow" aria-hidden="true">›</span>
        </button>)}{!availableNodes.length && <div className="beacon-discovery-empty"><span>⌁</span><strong>아직 체크인한 장치가 없습니다</strong><p>Beacon의 전원과 Wi-Fi, 서버 주소를 확인한 뒤 다시 검색하세요.</p><button type="button" onClick={() => void loadNodes(true)}>다시 확인</button></div>}</div>
        <footer><button type="button" onClick={() => setDiscoveryOpen(false)}>닫기</button></footer>
      </section>
    </div>}

    {settingsNodeId && <div className="beacon-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) { setSettingsNodeId(null); onPlacementCancel(); } }}>
      <form className="beacon-modal beacon-settings-modal" role="dialog" aria-modal="true" aria-label="Beacon 연결 설정" onSubmit={saveSettings}>
        <header><div><span className="beacon-dialog-eyebrow">장치 속성</span><h3>Beacon 설정</h3><p>장치의 설치 위치와 수집 방식을 관리합니다.</p></div><button type="button" className="beacon-dialog-close" aria-label="닫기" onClick={() => { setSettingsNodeId(null); onPlacementCancel(); }}>×</button></header><div className="beacon-settings-identity"><span className="beacon-device-avatar" aria-hidden="true">⌁</span><div><strong>{draft.label || settingsNodeId}</strong><small>{settingsNodeId}</small></div><span className="beacon-identity-status">장치 정보</span></div>
        {notice && <div className="beacon-notice" role="status">{notice}</div>}
        <div className="beacon-settings-grid">
          <label>장치 표시 이름<input required maxLength={64} value={draft.label ?? ""} onChange={(event) => setDraft((current) => ({ ...current, label: event.target.value }))} placeholder="예: 북쪽 하우스 센서" /></label>
          <label>수집 주기<input type="number" min={60} max={14400} step={1} value={intervalText} onChange={(event) => setIntervalText(event.target.value)} /><small>60초~4시간 · 배터리 수명과 수집 간격을 함께 고려하세요.</small></label>
        </div>
        <fieldset className="beacon-data-options"><legend>수집할 데이터</legend><label><input type="checkbox" checked={requestedSensor} onChange={(event) => setRequestedSensor(event.target.checked)} />센서 측정</label><label><input type="checkbox" checked={requestedImage} onChange={(event) => setRequestedImage(event.target.checked)} />카메라 이미지</label><small>장치는 설정된 주기로 체크인합니다. 요청 작업은 다음 체크인 때 전달될 수 있습니다. 이미지는 전력과 저장 공간을 더 사용합니다.</small></fieldset>
        <section className="beacon-location-picker"><div><span className="beacon-step-label">설치 위치 · 필수</span><strong>농장 지도에서 위치를 선택하세요</strong><small>{typeof draft.location?.latitude === "number" && typeof draft.location?.longitude === "number" ? `선택한 좌표 ${draft.location.latitude.toFixed(6)}, ${draft.location.longitude.toFixed(6)}` : hasFarmBoundary ? "지도에서 클릭하면 Beacon 위치가 저장됩니다." : "먼저 농장 경계를 등록해야 지도에서 위치를 선택할 수 있습니다."}</small></div><button type="button" onClick={() => startMapPlacement(settingsNodeId)} disabled={!hasFarmBoundary}>{typeof draft.location?.latitude === "number" ? "지도에서 위치 변경" : "지도에서 위치 선택"}</button></section>
        <div className="beacon-inventory"><strong>장치가 보고한 센서</strong>{(draft.sensors ?? []).length ? (draft.sensors ?? []).map((sensor, index) => <span key={`${sensor.type}-${sensor.address}-${index}`}>{sensor.model ?? sensor.type ?? "센서"} · {addressHex(sensor.address)}{sensor.fields?.length ? ` · ${sensor.fields.join(", ")}` : ""}</span>) : <small>센서 측정을 한 번 요청하면 실제 연결된 센서가 여기에 표시됩니다.</small>}</div>
        <footer><button type="button" onClick={() => { setSettingsNodeId(null); onPlacementCancel(); }}>취소</button><button type="submit" className="farm-map-primary" disabled={saving || !farmId}>{saving ? "저장 중…" : "등록 및 저장"}</button></footer>
      </form>
    </div>}
  </section>;
}
