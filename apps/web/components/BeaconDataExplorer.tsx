"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Reading = { value: number; unit: string; recorded_at: string; quality?: string | null };
type SensorEntry = { device: { sensor_id: string; display_name: string; sensor_type: string; unit: string; metadata: Record<string, unknown> }; latest_reading: Reading | null; readings: Reading[] };
type ImageEntry = { asset_id: string; captured_at: string; width?: number; height?: number; byte_size?: number; content_type?: string };
type CommandEntry = { command_id: number; command_type: string; state: string; reason?: string | null; created_at?: number | null; done_at?: number | null; params?: Record<string, unknown> | null; result?: Record<string, unknown> | null };
type BeaconDetail = { node: { node_id: string; label: string }; profile: { metadata: { location?: { site?: string | null; zone?: string | null; row?: string | null } } }; sensors: SensorEntry[]; images: ImageEntry[]; commands: CommandEntry[]; checkins: Record<string, unknown>[] };
type BeaconNode = { node_id: string; label: string; online: boolean; registered: boolean; farm_id?: string | null; last_seen?: number | null; metadata?: { location?: { site?: string | null; zone?: string | null; row?: string | null } } };
type Props = { farmId: string | null; farmName: string; nodes: BeaconNode[]; fetchProtected: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>; initialNodeId: string | null; initialSensorId: string | null };
type SelectedFile = { kind: "sensor"; id: string } | { kind: "image"; id: string } | { kind: "checkins" } | { kind: "commands" };

const BASE = "/api/backend/dashboard/beacons";

function timeLabel(value?: string | number | null) {
  if (value == null) return "시간 정보 없음";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? "시간 정보 없음" : new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function prettyBytes(value?: number) {
  if (!value || value < 1) return "크기 미상";
  return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

async function responseJson(response: Response) {
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof value?.detail === "string" ? value.detail : "저장된 기록을 불러오지 못했습니다.");
  return value;
}

export default function BeaconDataExplorer({ farmId, farmName, nodes, fetchProtected, initialNodeId, initialSensorId }: Props) {
  const availableNodes = useMemo(() => nodes.filter((node) => node.registered && (!farmId || node.farm_id === farmId)), [farmId, nodes]);
  const [nodeId, setNodeId] = useState<string | null>(initialNodeId ?? availableNodes[0]?.node_id ?? null);
  const [detail, setDetail] = useState<BeaconDetail | null>(null);
  const [selectedFile, setSelectedFile] = useState<SelectedFile | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ root: true, ...(initialNodeId ? { [initialNodeId]: true } : {}) });
  const [search, setSearch] = useState("");
  const [fileFilter, setFileFilter] = useState<"all" | "sensor" | "image" | "events">("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const initialApplied = useRef(false);

  useEffect(() => {
    if (!initialApplied.current && initialNodeId && availableNodes.some((node) => node.node_id === initialNodeId)) {
      initialApplied.current = true;
      setNodeId(initialNodeId);
      setExpanded((current) => ({ ...current, [initialNodeId]: true }));
      return;
    }
    if (nodeId && availableNodes.some((node) => node.node_id === nodeId)) return;
    setNodeId(availableNodes[0]?.node_id ?? null);
    setDetail(null);
    setSelectedFile(null);
  }, [availableNodes, initialNodeId, nodeId]);


  useEffect(() => {
    if (!nodeId) { setDetail(null); return; }
    let active = true;
    const load = async (spinner = false) => {
      if (spinner) setLoading(true);
      try {
        const result = await responseJson(await fetchProtected(`${BASE}/${encodeURIComponent(nodeId)}`, { cache: "no-store" })) as BeaconDetail;
        if (active) {
          setDetail(result);
          setError(null);
          setSelectedFile((current) => {
            if (current?.kind === "checkins" || current?.kind === "commands") return current;
            if (current?.kind === "sensor" && result.sensors.some((entry) => entry.device.sensor_id === current.id)) return current;
            if (current?.kind === "image" && result.images.some((entry) => entry.asset_id === current.id)) return current;
            if (initialSensorId && result.sensors.some((entry) => entry.device.sensor_id === initialSensorId)) return { kind: "sensor", id: initialSensorId };
            if (result.sensors[0]) return { kind: "sensor", id: result.sensors[0].device.sensor_id };
            if (result.images[0]) return { kind: "image", id: result.images[0].asset_id };
            return { kind: "checkins" };
          });
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "데이터 서버에 연결할 수 없습니다.");
      } finally { if (active && spinner) setLoading(false); }
    };
    void load(true);
    const timer = window.setInterval(() => void load(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [fetchProtected, initialSensorId, nodeId, reloadKey]);

  const selectedNode = availableNodes.find((node) => node.node_id === nodeId) ?? null;
  const sensor = selectedFile?.kind === "sensor" ? detail?.sensors.find((item) => item.device.sensor_id === selectedFile.id) ?? null : null;
  const image = selectedFile?.kind === "image" ? detail?.images.find((item) => item.asset_id === selectedFile.id) ?? null : null;
  const filteredNodes = availableNodes.filter((node) => `${node.label} ${node.node_id}`.toLowerCase().includes(search.toLowerCase()));

  function toggleFolder(key: string) { setExpanded((current) => ({ ...current, [key]: !current[key] })); }
  function openNode(nextId: string) {
    if (nextId !== nodeId) { setDetail(null); setSelectedFile(null); }
    setNodeId(nextId);
    setExpanded((current) => ({ ...current, root: true, [nextId]: true }));
  }

  return <section className="beacon-data-explorer" aria-label="Beacon 데이터 서버">
    <header className="beacon-data-heading">
      <div><span className="farm-map-kicker">LOCAL DATA SERVER</span><h3>데이터 서버</h3><p>{farmName}의 Beacon 수신 데이터를 장치별 폴더와 파일로 찾아봅니다.</p></div>
      <div className="beacon-storage-badges"><span><i />SQLite 측정 기록</span><span><i />SSD 이미지 파일</span></div>
    </header>
    <div className="beacon-file-browser">
      <aside className="beacon-file-tree" aria-label="저장 데이터 파일 목록">
        <label className="beacon-tree-search"><span aria-hidden="true">⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Beacon 검색" /></label>
        <label className="beacon-filter">자료 종류 <select value={fileFilter} onChange={(event) => setFileFilter(event.target.value as typeof fileFilter)}><option value="all">전체</option><option value="sensor">센서</option><option value="image">이미지</option><option value="events">연결 · 작업</option></select></label>
        <button type="button" className="beacon-tree-folder beacon-tree-root" onClick={() => toggleFolder("root")}><span>{expanded.root ? "▾" : "▸"}</span><b>농장 데이터</b><small>{farmName}</small></button>
        {expanded.root && <div className="beacon-tree-level">
          <div className="beacon-tree-folder static"><span>▾</span><b>beacons</b></div>
          {filteredNodes.map((node) => {
            const isOpen = Boolean(expanded[node.node_id]);
            const isSelected = nodeId === node.node_id;
            return <div className="beacon-tree-node" key={node.node_id}>
              <button type="button" className={`beacon-tree-folder${isSelected ? " selected" : ""}`} onClick={() => isOpen && isSelected ? toggleFolder(node.node_id) : openNode(node.node_id)}><span>{isOpen ? "▾" : "▸"}</span><b>{node.label}</b><small className={node.online ? "online" : ""}>{node.online ? "온라인" : "오프라인"}</small></button>
              {isOpen && isSelected && detail && <div className="beacon-tree-level beacon-tree-files">
                {fileFilter !== "image" && fileFilter !== "events" && <><button type="button" className="beacon-tree-folder" aria-expanded={expanded.sensors !== false} onClick={() => setExpanded((current) => ({ ...current, sensors: current.sensors === false }))}><span>{expanded.sensors === false ? "▸" : "▾"}</span><b>센서</b></button>
                {expanded.sensors !== false && <div className="beacon-tree-file-list">{detail.sensors.map((entry) => <button type="button" key={entry.device.sensor_id} className={`beacon-tree-file${selectedFile?.kind === "sensor" && selectedFile.id === entry.device.sensor_id ? " selected" : ""}`} onClick={() => setSelectedFile({ kind: "sensor", id: entry.device.sensor_id })}><span>▤</span><span><b>{entry.device.display_name}.csv</b><small>{entry.device.sensor_type} · {entry.readings.length}개 측정</small></span></button>)}{!detail.sensors.length && <small className="beacon-tree-empty">아직 수신한 센서 파일이 없습니다.</small>}</div>}
                </>}
                {fileFilter !== "sensor" && fileFilter !== "events" && <><button type="button" className="beacon-tree-folder" aria-expanded={expanded.images !== false} onClick={() => setExpanded((current) => ({ ...current, images: current.images === false }))}><span>{expanded.images === false ? "▸" : "▾"}</span><b>이미지</b></button>
                {expanded.images !== false && <div className="beacon-tree-file-list">{detail.images.map((entry) => <button type="button" key={entry.asset_id} className={`beacon-tree-file${selectedFile?.kind === "image" && selectedFile.id === entry.asset_id ? " selected" : ""}`} onClick={() => setSelectedFile({ kind: "image", id: entry.asset_id })}><span>▧</span><span><b>{entry.asset_id}.jpg</b><small>{timeLabel(entry.captured_at)} · {prettyBytes(entry.byte_size)}</small></span></button>)}{!detail.images.length && <small className="beacon-tree-empty">저장된 이미지가 없습니다.</small>}</div>}
                </>}
                {(fileFilter === "all" || fileFilter === "events") && <><button type="button" className={`beacon-tree-file standalone${selectedFile?.kind === "checkins" ? " selected" : ""}`} onClick={() => setSelectedFile({ kind: "checkins" })}><span>{"{}"}</span><b>checkins.json</b></button>
                <button type="button" className={`beacon-tree-file standalone${selectedFile?.kind === "commands" ? " selected" : ""}`} onClick={() => setSelectedFile({ kind: "commands" })}><span>{"{}"}</span><b>commands.json</b></button></>}
              </div>}
            </div>;
          })}
          {!filteredNodes.length && <div className="beacon-tree-empty">등록된 Beacon이 없습니다.</div>}
        </div>}
        <div className="beacon-tree-footer"><span>저장 방식</span><b>센서 · SQLite</b><b>이미지 · SSD</b></div>
      </aside>

      <main className="beacon-file-preview">
        {!selectedNode ? <div className="beacon-file-empty"><span>▤</span><strong>표시할 Beacon 데이터가 없습니다</strong><p>장치 연결에서 Beacon을 등록하면 수신 파일이 여기에 정리됩니다.</p></div>
        : loading && !detail ? <div className="beacon-file-empty"><span className="beacon-spinner" /><strong>저장 기록을 불러오는 중</strong></div>
        : error ? <div className="beacon-file-empty"><span>!</span><strong>기록을 열지 못했습니다</strong><p>{error}</p><button type="button" onClick={() => setReloadKey((value) => value + 1)}>다시 시도</button></div>
        : !selectedFile ? <div className="beacon-file-empty"><span>▤</span><strong>왼쪽에서 폴더 또는 파일을 선택하세요</strong><p>{selectedNode.label} · {selectedNode.node_id}</p></div>
        : selectedFile.kind === "sensor" && sensor ? <section className="beacon-file-document">
          <header><div><span className="beacon-file-type">CSV · 센서 측정</span><h4>{sensor.device.display_name}.csv</h4><p>{sensor.device.sensor_type} · {sensor.device.sensor_id}</p></div><span className="beacon-file-count">{sensor.readings.length}개 측정</span></header>
          <div className="beacon-file-current"><small>가장 최근 측정</small><strong>{sensor.latest_reading ? `${sensor.latest_reading.value} ${sensor.latest_reading.unit}` : "측정값 없음"}</strong><span>{timeLabel(sensor.latest_reading?.recorded_at)}</span></div>
          <div className="beacon-file-table-wrap"><table className="beacon-file-table"><thead><tr><th>수신 시각</th><th>값</th><th>단위</th><th>품질</th></tr></thead><tbody>{[...sensor.readings].reverse().map((row, index) => <tr key={`${row.recorded_at}-${index}`}><td>{timeLabel(row.recorded_at)}</td><td>{row.value}</td><td>{row.unit || sensor.device.unit}</td><td>{row.quality || "정상"}</td></tr>)}{!sensor.readings.length && <tr><td colSpan={4} className="beacon-table-empty">센서 측정 데이터가 아직 없습니다.</td></tr>}</tbody></table></div>
        </section>
        : selectedFile.kind === "image" && image ? <section className="beacon-file-document">
          <header><div><span className="beacon-file-type">JPEG · 카메라 수신</span><h4>{image.asset_id}.jpg</h4><p>{timeLabel(image.captured_at)} · {image.width ?? "?"} × {image.height ?? "?"} · {prettyBytes(image.byte_size)}</p></div><span className="beacon-file-count">원본 미리보기</span></header>
          <div className="beacon-image-preview"><img src={`/api/backend/dashboard/assets/${encodeURIComponent(image.asset_id)}/preview`} alt={`${selectedNode.label} ${timeLabel(image.captured_at)}`} /></div>
          <div className="beacon-image-meta"><span>Beacon <b>{selectedNode.node_id}</b></span><span>촬영 시각 <b>{timeLabel(image.captured_at)}</b></span><span>해상도 <b>{image.width ?? "?"} × {image.height ?? "?"}</b></span></div>
        </section>
        : selectedFile.kind === "checkins" ? <section className="beacon-file-document">
          <header><div><span className="beacon-file-type">JSON · 연결 기록</span><h4>checkins.json</h4><p>{detail?.checkins.length ?? 0}건 · 최근 체크인부터 표시</p></div></header>
          <div className="beacon-checkin-list">{(detail?.checkins ?? []).map((item, index) => <article key={String(item.received_at ?? index)}><span className="beacon-timeline-dot" /><div><strong>{timeLabel(typeof item.received_at === "number" ? item.received_at : String(item.received_at ?? ""))}</strong><small>IP {String(item.source_ip ?? "—")} · RSSI {String(item.rssi ?? "—")} dBm · 채널 {String(item.channel ?? "—")}</small><code>{JSON.stringify(item)}</code></div></article>)}{!detail?.checkins.length && <div className="beacon-table-empty">저장된 체크인 기록이 없습니다.</div>}</div>
        </section>
        : <section className="beacon-file-document">
          <header><div><span className="beacon-file-type">JSON · 수집 작업</span><h4>commands.json</h4><p>{detail?.commands.length ?? 0}건 · 센서 읽기와 이미지 요청 상태</p></div></header>
          <div className="beacon-checkin-list">{(detail?.commands ?? []).map((item) => <article key={item.command_id}><span className={`beacon-timeline-dot ${item.state === "done" ? "done" : item.state === "failed" ? "failed" : ""}`} /><div><strong>#{item.command_id} · {item.command_type === "sensor" ? "센서 측정" : "이미지 촬영"}</strong><small>{item.state} · {timeLabel(item.done_at ?? item.created_at)}</small><code>{JSON.stringify({ params: item.params, result: item.result, reason: item.reason })}</code></div></article>)}{!detail?.commands.length && <div className="beacon-table-empty">저장된 수집 작업이 없습니다.</div>}</div>
        </section>}
      </main>
    </div>
  </section>;
}
