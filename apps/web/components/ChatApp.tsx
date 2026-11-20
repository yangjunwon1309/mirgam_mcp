"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent, KeyboardEvent, MouseEvent, PointerEvent } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import JejuWeatherDashboard from "./JejuWeatherDashboard";
import FarmGeographyPanel from "./FarmGeographyPanel";
import DataServerDashboard from "./DataServerDashboard";

type ProgressEvent =
  | { type: "status"; phase: string; message: string }
  | { type: "tool_call"; tool: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; tool: string; result: unknown };
type Message = { role: "user" | "assistant"; content: string; trace?: ProgressEvent[]; pending?: boolean; traceOpen?: boolean };
type WorkspaceStyle = CSSProperties & { "--chat-split": string; "--dashboard-split": string };
type StoredMessage = { role: "system" | Message["role"]; content: string; trace?: ProgressEvent[] | null };
type Thread = { thread_id: string; title: string; updated_at: string };
type ThreadDocument = Thread & { messages: StoredMessage[] };
type AuthUser = { account_id: number; farm_name: string; username: string | null };
type Health = { llama?: { reachable?: boolean; model_available?: boolean } };
type SensorDevice = { sensor_id: string; display_name: string; sensor_type: string; unit: string; status: string; zone_id: string | null; latest_value: number | null; latest_recorded_at: string | null };
type SensorReading = { value: number; unit: string; recorded_at: string; quality: string };
type SensorRollup = { local_date: string; unit: string; sample_count: number; min_value: number; max_value: number; avg_value: number; p50_value: number };
type SensorDetail = { device: SensorDevice; latest_reading: SensorReading | null; readings: SensorReading[]; daily_rollups: SensorRollup[] };
type Camera = { camera_id: string; display_name: string; camera_type: string; status: string; zone_id: string | null; latest_asset_id: string | null; latest_captured_at: string | null; avg_coverage_ratio: number | null; avg_confidence: number | null; alert_count: number | null };
type CameraAsset = { asset_id: string; captured_at: string; content_type: string; width: number; height: number };
type VisionRollup = { local_date: string; label: string; image_count: number; total_instances: number; avg_coverage_ratio: number | null; avg_confidence: number | null; alert_count: number };
type CameraDetail = { camera: Camera; latest_asset: CameraAsset | null; daily_rollups: VisionRollup[] };

function cameraMarkerLabel(name: string) {
  return name.replace(/\s*카메라.*$/u, "").trim() || "카메라";
}

function displayFarmText(value: string | null | undefined, farmName: string) {
  if (!value) return value ?? "";
  return value.replace(/온실\s*A|greenhouse[-_ ]?A/giu, () => farmName);
}

async function* readSseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<Record<string, unknown>> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const data = block.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
        if (data) yield JSON.parse(data) as Record<string, unknown>;
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
}

function timestamp(value: string | null) {
  if (!value) return "기록 없음";
  return new Intl.DateTimeFormat("ko-KR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function sensorIcon(type: string) {
  if (type.includes("temperature")) return "☀";
  if (type.includes("humidity") || type.includes("moisture")) return "💧";
  return "◉";
}

function trendPoints(readings: SensorReading[]) {
  if (!readings.length) return "";
  const values = readings.map((reading) => reading.value);
  const min = Math.min(...values);
  const range = Math.max(Math.max(...values) - min, 0.01);
  return readings.map((reading, index) => `${(index / Math.max(readings.length - 1, 1)) * 320},${82 - ((reading.value - min) / range) * 58}`).join(" ");
}

export default function ChatApp() {
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [authNotice, setAuthNotice] = useState<string | null>(null);
  const [loginIdentifier, setLoginIdentifier] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginSubmitting, setLoginSubmitting] = useState(false);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelOnline, setModelOnline] = useState<boolean | null>(null);
  const [sensors, setSensors] = useState<SensorDevice[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selectedSensorId, setSelectedSensorId] = useState<string | null>(null);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
  const [sensorDetail, setSensorDetail] = useState<SensorDetail | null>(null);
  const [cameraDetail, setCameraDetail] = useState<CameraDetail | null>(null);
  const [dashboardMode, setDashboardMode] = useState<"sensor" | "camera">("sensor");
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [chatPercent, setChatPercent] = useState(50);
  const [dashboardCollapsed, setDashboardCollapsed] = useState(false);
  const [dataSelection, setDataSelection] = useState<{ nodeId: string; sensorId?: string } | null>(null);
  const [dashboardTab, setDashboardTab] = useState<"farm" | "jeju-weather" | "data-server" | "beacon">("farm");
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const workspaceRef = useRef<HTMLElement | null>(null);
  const resizingRef = useRef(false);

  const fetchProtected = useCallback(async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await fetch(input, init);
    if (response.status === 401) {
      setAuthNotice("로그인 세션이 만료되었습니다. 다시 로그인해 주세요.");
      setAuthUser(null);
    }
    return response;
  }, []);

  useEffect(() => {
    let active = true;
    void fetch("/api/backend/auth/me", { cache: "no-store" })
      .then(async (response) => {
        if (response.ok) {
          const user: AuthUser = await response.json();
          if (active) setAuthUser(user);
        } else if (response.status !== 401 && active) {
          setAuthNotice("로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
        }
      })
      .catch(() => {
        if (active) setAuthNotice("로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
      })
      .finally(() => {
        if (active) setAuthChecking(false);
      });
    return () => { active = false; };
  }, []);

  const loadThreads = useCallback(async () => {
    const response = await fetchProtected("/api/backend/threads");
    if (response.ok) setThreads(await response.json());
  }, [fetchProtected]);

  const loadModelStatus = useCallback(async () => {
    try {
      const response = await fetchProtected("/api/backend/health");
      const health: Health = await response.json();
      setModelOnline(Boolean(health.llama?.reachable && health.llama?.model_available));
    } catch {
      setModelOnline(false);
    }
  }, [fetchProtected]);

  const loadDashboard = useCallback(async () => {
    try {
      const [sensorResponse, cameraResponse] = await Promise.all([
        fetchProtected("/api/backend/dashboard/sensors"),
        fetchProtected("/api/backend/dashboard/cameras"),
      ]);
      if (!sensorResponse.ok || !cameraResponse.ok) throw new Error("SQLite dashboard data is unavailable.");
      const sensorData: SensorDevice[] = await sensorResponse.json();
      const cameraData: Camera[] = await cameraResponse.json();
      setSensors(sensorData);
      setCameras(cameraData);
      setSelectedSensorId((current) => current ?? sensorData[0]?.sensor_id ?? null);
      setSelectedCameraId((current) => current ?? cameraData[0]?.camera_id ?? null);
      setDashboardError(null);
    } catch {
      setDashboardError("SQLite 데이터가 아직 없습니다. demo seed를 실행한 뒤 새로고침하세요.");
    }
  }, [fetchProtected]);

  const loadSensorDetail = useCallback(async (sensorId: string) => {
    const response = await fetchProtected(`/api/backend/dashboard/sensors/${encodeURIComponent(sensorId)}?hours=24`);
    if (response.ok) setSensorDetail(await response.json());
  }, [fetchProtected]);

  const loadCameraDetail = useCallback(async (cameraId: string) => {
    const response = await fetchProtected(`/api/backend/dashboard/cameras/${encodeURIComponent(cameraId)}`);
    if (response.ok) setCameraDetail(await response.json());
  }, [fetchProtected]);

  useEffect(() => {
    if (!authUser) return;
    void loadThreads();
    void loadModelStatus();
    void loadDashboard();
  }, [authUser, loadDashboard, loadModelStatus, loadThreads]);

  useEffect(() => {
    if (authUser && selectedSensorId) void loadSensorDetail(selectedSensorId);
  }, [authUser, loadSensorDetail, selectedSensorId]);

  useEffect(() => {
    if (authUser && selectedCameraId) void loadCameraDetail(selectedCameraId);
  }, [authUser, loadCameraDetail, selectedCameraId]);

  useEffect(() => {
    if (!authUser || dashboardTab !== "farm") return;
    const refresh = () => {
      void loadDashboard();
      if (selectedSensorId) void loadSensorDetail(selectedSensorId);
      if (selectedCameraId) void loadCameraDetail(selectedCameraId);
    };
    const timer = window.setInterval(refresh, 15_000);
    return () => window.clearInterval(timer);
  }, [authUser, dashboardTab, loadCameraDetail, loadDashboard, loadSensorDetail, selectedCameraId, selectedSensorId]);

  useEffect(() => {
    if (sending) messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  const currentSensorDetail = sensorDetail?.device.sensor_id === selectedSensorId ? sensorDetail : null;
  const currentCameraDetail = cameraDetail?.camera.camera_id === selectedCameraId ? cameraDetail : null;
  const latestReading = currentSensorDetail?.readings[currentSensorDetail.readings.length - 1] ?? currentSensorDetail?.latest_reading ?? null;
  const latestRollup = currentSensorDetail?.daily_rollups[0] ?? null;
  const chart = useMemo(() => trendPoints(currentSensorDetail?.readings ?? []), [currentSensorDetail]);
  const previewUrl = currentCameraDetail?.latest_asset ? `/api/backend/dashboard/assets/${encodeURIComponent(currentCameraDetail.latest_asset.asset_id)}/preview` : null;
  const latestVision = currentCameraDetail?.daily_rollups[0] ?? null;

  function beginResize(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    resizingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveResize(event: PointerEvent<HTMLDivElement>) {
    if (!resizingRef.current || !workspaceRef.current) return;
    const bounds = workspaceRef.current.getBoundingClientRect();
    const availableWidth = bounds.width - 10;
    const requestedPercent = ((event.clientX - bounds.left - 5) / availableWidth) * 100;
    setChatPercent(Math.round(Math.max(38, Math.min(65, requestedPercent))));
  }

  function endResize() {
    resizingRef.current = false;
  }

  function resizeWithKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.key === "ArrowLeft" ? -2 : 2;
    setChatPercent((current) => Math.max(38, Math.min(65, current + step)));
  }

  async function selectThread(threadId: string) {
    const response = await fetchProtected(`/api/backend/threads/${encodeURIComponent(threadId)}`);
    if (!response.ok) return;
    const thread: ThreadDocument = await response.json();
    setActiveId(thread.thread_id);
    setMessages(thread.messages
      .filter((message): message is StoredMessage & { role: Message["role"] } => message.role !== "system")
      .map((message) => ({ role: message.role, content: message.content, trace: message.trace ?? undefined, traceOpen: false })));
    setError(null);
  }

  function startNew() {
    setActiveId(null);
    setMessages([]);
    setDraft("");
    setError(null);
  }

  async function removeThread(threadId: string, event: MouseEvent) {
    event.stopPropagation();
    await fetchProtected(`/api/backend/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
    if (activeId === threadId) startNew();
    await loadThreads();
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || sending) return;
    setSending(true);
    setError(null);
    setDraft("");
    setMessages((current) => [
      ...current,
      { role: "user", content: message },
      { role: "assistant", content: "", trace: [], pending: true, traceOpen: true },
    ]);
    try {
      const response = await fetchProtected("/api/backend/chat/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message, thread_id: activeId }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `요청 실패 (${response.status})`);
      }
      if (!response.body) throw new Error("진행 상태 스트림을 열 수 없습니다.");
      let completed = false;
      for await (const event of readSseEvents(response.body)) {
        if (event.type === "status" || event.type === "tool_call" || event.type === "tool_result") {
          const progress = event as unknown as ProgressEvent;
          setMessages((current) => {
            const lastIndex = current.length - 1;
            const last = current[lastIndex];
            if (!last?.pending) return current;
            const updated = [...current];
            updated[lastIndex] = { ...last, trace: [...(last.trace ?? []), progress] };
            return updated;
          });
        } else if (event.type === "done") {
          const threadId = String(event.thread_id ?? "");
          const reply = String(event.reply ?? "");
          if (!threadId || !reply) throw new Error("완료된 답변이 스트림에 포함되지 않았습니다.");
          completed = true;
          setActiveId(threadId);
          setMessages((current) => {
            const lastIndex = current.length - 1;
            const last = current[lastIndex];
            if (!last?.pending) return [...current, { role: "assistant", content: reply }];
            const updated = [...current];
            updated[lastIndex] = { ...last, content: reply, pending: false, traceOpen: false };
            return updated;
          });
        } else if (event.type === "error") {
          throw new Error(String(event.detail ?? `요청 실패 (${event.status ?? "server"})`));
        }
      }
      if (!completed) throw new Error("서버가 답변을 완료하기 전에 연결이 끊겼습니다.");
      await loadThreads();
      await loadModelStatus();
    } catch (caught) {
      setMessages((current) => {
        const lastIndex = current.length - 1;
        const last = current[lastIndex];
        if (!last?.pending) return current;
        if (!last.trace?.length) return current.slice(0, -1);
        const updated = [...current];
        updated[lastIndex] = { ...last, pending: false, traceOpen: false };
        return updated;
      });
      setDraft(message);
      setError(caught instanceof Error ? caught.message : "응답을 받을 수 없습니다.");
      void loadModelStatus();
    } finally {
      setSending(false);
    }
  }

  async function submitLogin(event: FormEvent) {
    event.preventDefault();
    if (loginSubmitting) return;
    setLoginSubmitting(true);
    setAuthNotice(null);
    try {
      const response = await fetch("/api/backend/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ identifier: loginIdentifier, password: loginPassword }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "로그인에 실패했습니다. 입력 정보를 확인해 주세요.");
      setAuthUser(body as AuthUser);
      setLoginPassword("");
    } catch (caught) {
      setAuthNotice(caught instanceof Error ? caught.message : "로그인에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setLoginSubmitting(false);
    }
  }

  async function logout() {
    try {
      await fetch("/api/backend/auth/logout", { method: "POST" });
    } finally {
      setAuthUser(null);
      setThreads([]);
      setMessages([]);
      setActiveId(null);
      setAuthNotice(null);
      setError(null);
    }
  }

  if (authChecking) {
    return <main className="auth-screen"><div className="auth-card auth-loading"><span className="brand-mark">◒</span><p>로그인 상태를 확인하고 있습니다…</p></div></main>;
  }

  if (!authUser) {
    return <main className="auth-screen">
      <section className="auth-card" aria-labelledby="login-title">
        <div className="auth-brand"><span className="brand-mark">◒</span><div><strong>mirgam mcp</strong><small>smart farm agent</small></div></div>
        <p className="eyebrow">FARM MANAGEMENT</p>
        <h1 id="login-title">농장 계정으로 로그인</h1>
        <p className="auth-description">등록된 농장명 또는 사용자 ID와 비밀번호를 입력해 주세요.</p>
        <form className="auth-form" onSubmit={submitLogin}>
          <label htmlFor="login-identifier">농장명 또는 사용자 ID</label>
          <input
            id="login-identifier"
            name="username"
            autoComplete="username"
            value={loginIdentifier}
            onChange={(event) => setLoginIdentifier(event.target.value)}
            required
            disabled={loginSubmitting}
          />
          <label htmlFor="login-password">비밀번호</label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={loginPassword}
            onChange={(event) => setLoginPassword(event.target.value)}
            required
            disabled={loginSubmitting}
          />
          {authNotice && <p className="auth-error" role="alert">{authNotice}</p>}
          <button type="submit" disabled={loginSubmitting || !loginIdentifier || !loginPassword}>
            {loginSubmitting ? "계정 확인 중…" : "로그인"}
          </button>
        </form>
        <p className="auth-footnote">로그인 정보는 Mirgam 계정 서버에서 확인됩니다.</p>
      </section>
    </main>;
  }

  return (
    <main
      ref={workspaceRef}
      className={`workspace ${dashboardCollapsed ? "dashboard-collapsed" : ""}`}
      style={{ "--chat-split": `${chatPercent}fr`, "--dashboard-split": `${100 - chatPercent}fr` } as WorkspaceStyle}
    >
      <section className="chat-panel" aria-label="MIRGAM AI agent chat">
        <aside className="conversation-rail">
          <div className="brand"><span className="brand-mark">◒</span><div><strong>mirgam mcp</strong><small>smart farm agent</small></div></div>
          <button className="new" onClick={startNew}>+ 새 대화</button><div className="rail-label">대화 기록</div>
          <nav aria-label="대화 목록">
            {threads.map((thread) => <button key={thread.thread_id} className={`thread ${thread.thread_id === activeId ? "selected" : ""}`} onClick={() => void selectThread(thread.thread_id)}>
              <span>{thread.title}</span><i onClick={(event) => void removeThread(thread.thread_id, event)} aria-label="대화 삭제">×</i>
            </button>)}
          </nav>
          <p className="storage">대화와 농장 demo 데이터는 로컬 SQLite에 저장됩니다.</p>
        </aside>
        <section className="chat">
          <header className="chat-header"><div><p className="eyebrow">AI FARM COPILOT</p><strong>{activeId ? "농장 운영 대화" : "새 운영 대화"}</strong></div><div className="chat-header-actions"><span className="account-name" title={authUser.farm_name}>{authUser.farm_name}</span><button className="logout-button" onClick={() => void logout()}>로그아웃</button><span className={`status ${modelOnline ? "online" : ""}`}>● {modelOnline === null ? "확인 중" : modelOnline ? "로컬 준비됨" : "모델 오프라인"}</span>{dashboardCollapsed && <button className="dashboard-open-button" onClick={() => setDashboardCollapsed(false)}>대시보드 열기 ↗</button>}</div></header>
          <div className="messages">
            {messages.length === 0 && <div className="empty"><span className="sprout">✦</span><h1>오늘 농장은 어떤가요?</h1><p>SQLite 센서 기록, 이미지 상태, 작업 계획을 MIRGAM에게 물어보세요.</p></div>}
            {messages.map((message, index) => <article key={index} className={`message ${message.role}`}><div className="avatar">{message.role === "user" ? "나" : "✦"}</div><div className="content">
              {message.trace && message.trace.length > 0 && <details className="trace-panel" open={message.traceOpen} onToggle={(event) => {
                const isOpen = event.currentTarget.open;
                setMessages((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, traceOpen: isOpen } : item));
              }}>
                <summary><span>진행 과정과 도구 조회</span><small>{[...message.trace].reverse().find((item): item is Extract<ProgressEvent, { type: "status" }> => item.type === "status")?.message ?? "단계별 기록"}</small></summary>
                <div className="trace-events">{message.trace.map((item, traceIndex) => {
                  if (item.type === "status") return <div className="trace-status" key={traceIndex}><i />{item.message}</div>;
                  if (item.type === "tool_call") return <div className="trace-tool" key={traceIndex}><strong>도구 호출 · {item.tool}</strong><span>전달한 인자</span><pre>{JSON.stringify(item.arguments, null, 2)}</pre></div>;
                  return <div className="trace-result" key={traceIndex}><strong>{item.tool} 반환 결과</strong><pre>{JSON.stringify(item.result, null, 2)}</pre></div>;
                })}</div>
              </details>}
              {message.content && <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>}
              {message.pending && !message.trace?.length && <p className="waiting">요청을 전달하고 있습니다…</p>}
              {message.pending && <span className="trace-spinner" aria-label="처리 중" />}
            </div></article>)}
            <div ref={messagesEndRef} />
          </div>
          <form onSubmit={send}>
            {error && <p className="error">{error}</p>}
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={`예: 오늘 ${authUser.farm_name}의 온도와 습도 추이를 알려줘`} rows={3} disabled={sending} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
            <div className="composer-footer"><small>Enter 전송 · Shift+Enter 줄바꿈</small><button type="submit" disabled={!draft.trim() || sending}>전송 ↑</button></div>
          </form>
        </section>
      </section>

      {!dashboardCollapsed && <div
        className="resize-handle"
        role="separator"
        aria-label="채팅과 대시보드 너비 조절"
        aria-orientation="vertical"
        aria-valuemin={38}
        aria-valuemax={65}
        aria-valuenow={chatPercent}
        tabIndex={0}
        onPointerDown={beginResize}
        onPointerMove={moveResize}
        onPointerUp={endResize}
        onPointerCancel={endResize}
        onLostPointerCapture={endResize}
        onKeyDown={resizeWithKeyboard}
      />}

      {!dashboardCollapsed && <section className="farm-dashboard" aria-label="Smart farm dashboard">
        <header className="dashboard-header"><div><p className="eyebrow">{dashboardTab === "farm" ? "FIELD OVERVIEW" : dashboardTab === "jeju-weather" ? "JEJU WEATHER" : dashboardTab === "beacon" ? "BEACON DEVICES" : "DATA SERVER"}</p><h1>{dashboardTab === "farm" ? `${authUser.farm_name} · 재배 현황` : dashboardTab === "jeju-weather" ? "제주 기상 정보" : dashboardTab === "beacon" ? "Beacon 관리" : "농장 데이터 서버"}</h1></div><button className="dashboard-collapse-button" onClick={() => setDashboardCollapsed(true)} aria-label="대시보드 접기">접기 ⟶</button></header>
        <nav className="dashboard-folder-tabs" role="tablist" aria-label="대시보드 화면 선택">{([["farm", "농장 현황"], ["jeju-weather", "제주 날씨"], ["data-server", "데이터 서버"], ["beacon", "Beacon 관리"]] as const).map(([key, label]) => <button type="button" role="tab" aria-selected={dashboardTab === key} key={key} className={dashboardTab === key ? "active" : ""} onClick={() => { if (key === "data-server") setDataSelection(null); setDashboardTab(key); }}><span aria-hidden="true">▰</span>{label}</button>)}</nav>
        {dashboardTab === "jeju-weather" ? <JejuWeatherDashboard fetchProtected={fetchProtected} /> : dashboardTab === "data-server" ? <DataServerDashboard farmName={authUser.farm_name} selectedNodeId={dataSelection?.nodeId ?? null} selectedSensorId={dataSelection?.sensorId ?? null} fetchProtected={fetchProtected} /> : <>
        <FarmGeographyPanel
          view={dashboardTab === "beacon" ? "beacon" : "farm"}
          onViewChange={setDashboardTab}
          onOpenData={(nodeId, sensorId) => { setDataSelection({ nodeId, sensorId }); setDashboardTab("data-server"); }}
          farmName={authUser.farm_name}
          fetchProtected={fetchProtected}
          sensors={sensors.map((sensor) => ({ sensor_id: sensor.sensor_id, display_name: displayFarmText(sensor.display_name, authUser.farm_name), sensor_type: sensor.sensor_type }))}
          cameras={cameras.map((camera) => ({ camera_id: camera.camera_id, display_name: displayFarmText(cameraMarkerLabel(camera.display_name), authUser.farm_name) }))}
          selectedSensorId={selectedSensorId}
          selectedCameraId={selectedCameraId}
          dashboardMode={dashboardMode}
          onSelectSensor={(sensorId) => { setSelectedSensorId(sensorId); setDashboardMode("sensor"); }}
          onSelectCamera={(cameraId) => { setSelectedCameraId(cameraId); setDashboardMode("camera"); }}
        />
        {dashboardTab === "farm" && <section className="sensor-panel"><div className="section-heading"><div><h2>{dashboardMode === "sensor" ? displayFarmText(currentSensorDetail?.device.display_name ?? "센서 데이터", authUser.farm_name) : displayFarmText(currentCameraDetail?.camera.display_name ?? "카메라 이미지", authUser.farm_name)}</h2><p>선택한 위치의 최신 센서값 또는 카메라 기록</p></div><button className="refresh-data" onClick={() => { if (dashboardMode === "sensor" && selectedSensorId) void loadSensorDetail(selectedSensorId); if (dashboardMode === "camera" && selectedCameraId) void loadCameraDetail(selectedCameraId); }}>새로고침</button></div>
          {dashboardMode === "sensor" && currentSensorDetail && <div className="sensor-detail">
            <div className="sensor-reading"><span>{sensorIcon(currentSensorDetail.device.sensor_type)}</span><div><small>{latestReading?.unit ?? currentSensorDetail.device.unit} · {displayFarmText(currentSensorDetail.device.zone_id, authUser.farm_name) || "미지정"}</small><strong>{latestReading ? latestReading.value.toFixed(1) : "—"}</strong><p>{latestRollup ? `${latestRollup.local_date} 평균 ${latestRollup.avg_value.toFixed(1)} · ${latestRollup.sample_count}개 측정값` : "기록된 raw 값이 없습니다."}</p></div></div>
            <div className="sensor-graph" aria-label="최근 SQLite raw 추이"><div className="graph-labels"><span>{currentSensorDetail.readings.length ? "최근 raw 추이" : "마지막 저장값"}</span><span>{latestReading ? timestamp(latestReading.recorded_at) : "수집 대기"}</span></div><svg viewBox="0 0 320 95" preserveAspectRatio="none">{chart && <polyline points={chart} fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />}</svg></div>
          </div>}
          {dashboardMode === "camera" && currentCameraDetail && <div className="camera-detail">
            <div className="camera-detail-preview">{previewUrl ? <img src={previewUrl} alt={`${currentCameraDetail.camera.display_name} 최신 이미지`} /> : <div className="camera-empty">저장된 이미지가 없습니다.</div>}{currentCameraDetail.latest_asset && <small>{timestamp(currentCameraDetail.latest_asset.captured_at)} · {currentCameraDetail.latest_asset.width}×{currentCameraDetail.latest_asset.height}</small>}</div>
            <div className="camera-detail-info"><div className="sensor-reading"><span>◉</span><div><small>{displayFarmText(currentCameraDetail.camera.zone_id, authUser.farm_name) || "미지정"} · {currentCameraDetail.camera.camera_type}</small><strong>{latestVision ? `${latestVision.total_instances} 포기` : "—"}</strong><p>{latestVision ? `피복률 ${((latestVision.avg_coverage_ratio ?? 0) * 100).toFixed(1)}% · 신뢰도 ${((latestVision.avg_confidence ?? 0) * 100).toFixed(0)}% · 경고 ${latestVision.alert_count}건` : "비전 집계가 없습니다."}</p></div></div>
              <div className="vision-days">{currentCameraDetail.daily_rollups.map((rollup) => <div key={rollup.local_date}><small>{rollup.local_date.slice(5)}</small><strong>{((rollup.avg_coverage_ratio ?? 0) * 100).toFixed(0)}%</strong><span>{rollup.total_instances} 포기</span></div>)}</div>
            </div>
          </div>}
          {dashboardMode === "sensor" && !currentSensorDetail && <p className="dashboard-empty">센서 데이터를 불러오는 중입니다…</p>}
          {dashboardMode === "camera" && !currentCameraDetail && <p className="dashboard-empty">카메라 기록을 불러오는 중입니다…</p>}
          {!dashboardError && !sensors.length && !cameras.length && <p className="dashboard-empty">등록된 장치가 없습니다. demo seed를 실행하면 이 영역에 센서와 카메라가 표시됩니다.</p>}
          {dashboardError && <p className="dashboard-empty">{dashboardError}</p>}
        </section>}
        </>}
      </section>}
    </main>
  );
}
