"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BeaconNode, CommandEntry, Energy } from "../types";
import { useBeaconFleet } from "../BeaconFleetProvider";
import { useBeaconDetail } from "../hooks/useBeaconDetail";
import { usePolling } from "../hooks/usePolling";
import { useToasts } from "../ui/Toasts";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";
import { Icon } from "../ui/Icon";
import { Menu } from "../ui/Menu";
import { health, deliveryInfo, countdown, intervalLabel } from "../format";
import { DeliveryBar } from "./DeliveryBar";
import { StatusTab } from "./StatusTab";
import { ActivityTab } from "./ActivityTab";
import { SettingsTab } from "./SettingsTab";
import { ConfirmDialog } from "./ConfirmDialog";

type Tab = "status" | "activity" | "settings";
function queuedCommand(id: number, nodeId: string, type: "sensor" | "image", params: Record<string, unknown>): CommandEntry {
  return { command_id: id, node_id: nodeId, command_type: type, params, state: "queued", reason: null, attempts: 0, created_at: Date.now() / 1000, dispatched_at: null, done_at: null, result: null, image_asset_id: null };
}
export function DeviceDialog() {
  const fleet = useBeaconFleet();
  const toasts = useToasts();
  const id = fleet.openDeviceId;
  const open = Boolean(id);
  const node = fleet.allNodes.find((item) => item.node_id === id) ?? null;
  const detailState = useBeaconDetail(open ? id : null, { intervalMs: 7000, paused: !open });
  const [energy, setEnergy] = useState<Energy | null>(null);
  const energyTask = useCallback(async (signal: AbortSignal) => {
    if (id) setEnergy(await fleet.api.getEnergy(id, signal));
  }, [fleet.api, id]);
  usePolling(energyTask, { intervalMs: 60000, enabled: open && Boolean(id), deps: [id] });
  const [tab, setTab] = useState<Tab>("status");
  const [optimistic, setOptimistic] = useState<CommandEntry[]>([]);
  const [confirmKind, setConfirmKind] = useState<"hibernate" | "detach" | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [resolution, setResolution] = useState("VGA");
  useEffect(() => { setEnergy(null); setTab("status"); setOptimistic([]); setMenuOpen(false); }, [id]);
  const menuAnchor = useRef<HTMLButtonElement>(null);
  const detail = detailState.detail;
  const activeNode = detail?.node ?? node;
  const actualIds = useMemo(() => new Set(detail?.commands.map((item) => item.command_id) ?? []), [detail?.commands]);
  const pendingOptimistic = optimistic.filter((item) => !actualIds.has(item.command_id));
  const canCommand = Boolean(activeNode?.registered && activeNode.state === "ATTACHED");
  const status = activeNode ? health(activeNode) : null;
  useEffect(() => {
    const next = activeNode?.next_expected_at;
    if (!open || !next) return;
    const ms = (next - Date.now() / 1000 - 3) * 1000;
    if (ms < -3000) return;
    const timer = window.setTimeout(detailState.reload, Math.max(0, ms) + 2000);
    return () => window.clearTimeout(timer);
  }, [open, activeNode?.next_expected_at, detailState.reload]);
  if (!activeNode) return <Dialog open={false} onClose={fleet.closeDevice} size="lg" labelledBy="bx-device-title"><span /></Dialog>;

  async function requestCommand(type: "sensor" | "image", fs?: string) {
    if (!id || !canCommand || !activeNode) return;
    const body = type === "image" ? { type, fs: fs ?? resolution, q: 12, warm: 500 } : { type };
    try {
      const result = await fleet.api.command(id, body);
      const entry = queuedCommand(result.command_id, id, type, body);
      setOptimistic((items) => [entry, ...items.filter((item) => item.command_id !== result.command_id)]);
      setTab("activity"); detailState.reload(); fleet.refreshNodes();
      const eta = activeNode.next_expected_at === null ? "다음 체크인" : "약 " + countdown(Math.max(0, activeNode.next_expected_at - Date.now() / 1000)) + " 후 체크인";
      toasts.push({ title: (type === "sensor" ? "센서 읽기" : "촬영") + " #" + result.command_id + " 요청됨", body: activeNode.online ? activeNode.label + "이 " + eta + " 때 실행합니다." : "장치가 다시 연결되면 전달됩니다.", tone: "wait" });
    } catch (cause) { toasts.push({ title: "명령을 요청하지 못했습니다", body: cause instanceof Error ? cause.message : undefined, tone: "error", durationMs: null }); }
  }
  async function doAction(kind: "hibernate" | "detach") {
    if (!id) return;
    await fleet.api.action(id, kind, {});
    toasts.push({ title: kind === "hibernate" ? "절전을 요청했습니다" : "연결을 해제했습니다", body: "다음 체크인 때 장치에 전달됩니다.", tone: "ok" });
    setConfirmKind(null); fleet.closeDevice(); fleet.refreshNodes();
  }
  const menuItems = [
    { label: "1분간 즉시 응답", disabled: !canCommand, icon: "zap" as const, onSelect: () => void fleet.api.action(id!, "session", { hold_s: 60 }).then(() => toasts.push({ title: "즉시 응답을 요청했습니다", body: "다음 체크인부터 적용됩니다.", tone: "ok" })).catch((e: unknown) => toasts.push({ title: "요청 실패", body: e instanceof Error ? e.message : undefined, tone: "error", durationMs: null })) },
    { label: "10분간 자주 확인", disabled: !canCommand, icon: "clock" as const, onSelect: () => void fleet.api.action(id!, "watch", { minutes: 10 }).then(() => { toasts.push({ title: "자주 확인을 요청했습니다", body: "다음 체크인부터 적용됩니다.", tone: "ok" }); fleet.refreshNodes(); }).catch((e: unknown) => toasts.push({ title: "요청 실패", body: e instanceof Error ? e.message : undefined, tone: "error", durationMs: null })) },
    "sep" as const,
    { label: "설정 편집", icon: "gear" as const, onSelect: () => { fleet.closeDevice(); fleet.openEdit(id!); } },
    { label: "절전", disabled: !activeNode.registered, icon: "moon" as const, danger: true, onSelect: () => setConfirmKind("hibernate") },
    { label: "연결 해제", disabled: !activeNode.registered, icon: "unlink" as const, danger: true, onSelect: () => setConfirmKind("detach") },
  ];
  return <>
    <Dialog open={open} onClose={fleet.closeDevice} size="lg" className="bx-device-dialog" labelledBy="bx-device-title">
      <div className="bx-dialog-head bx-device-head">
        <span className="bx-device-mark"><Icon name="beacon" size={22} /></span><div className="bx-device-heading"><h2 id="bx-device-title">{activeNode.label}</h2><div><code>{activeNode.node_id}</code><button type="button" className="bx-copy-id" onClick={() => { void navigator.clipboard.writeText(activeNode.node_id).then(() => toasts.push({ title: "ID를 복사했습니다", tone: "ok" })).catch(() => toasts.push({ title: "클립보드에 복사하지 못했습니다", tone: "error" })); }}>ID 복사</button></div><small>{[activeNode.metadata.location?.site, activeNode.metadata.location?.zone, activeNode.metadata.location?.row].filter(Boolean).join(" · ") || "설치 위치 미지정"}</small></div>
        {status ? <Badge tone={status.tone} dot>{status.label}</Badge> : null}<button type="button" className="bx-btn bx-btn--icon" data-dialog-close aria-label="닫기" onClick={fleet.closeDevice}>×</button>
      </div>
      <div className="bx-action-row">
        <Button variant="primary" icon="activity" disabled={!canCommand} title={!canCommand ? "연결된 장치에서 사용할 수 있습니다" : "오프라인이면 다시 연결될 때 전달됩니다"} onClick={() => void requestCommand("sensor")}>센서 읽기</Button>
        <label className="bx-image-action"><Button variant="secondary" icon="camera" disabled={!canCommand} onClick={() => void requestCommand("image")}>촬영</Button><select aria-label="촬영 해상도" value={resolution} onChange={(event) => setResolution(event.target.value)} disabled={!canCommand}><option>QVGA</option><option>VGA</option><option>SVGA</option><option>XGA</option></select></label>
        <Button variant="ghost" icon="db" onClick={() => id && fleet.openData(id)}>데이터</Button>
        <button ref={menuAnchor} type="button" className="bx-btn bx-btn--ghost bx-btn--icon" aria-label="추가 작업" aria-expanded={menuOpen} onClick={() => setMenuOpen((value) => !value)}><Icon name="more" size={16} /></button>
        <Menu anchor={menuAnchor} open={menuOpen} onClose={() => setMenuOpen(false)} items={menuItems} />
      </div>
      <div className="bx-dialog-body bx-device-body">
        {detailState.error ? <p className="bx-form-error" role="alert">{detailState.error}</p> : null}
        <DeliveryBar node={activeNode} />
        <div className="bx-subtabs" role="tablist" aria-label="장치 상세">
          {([{ key: "status", label: "상태" }, { key: "activity", label: "작업", count: (detail?.commands.length ?? 0) + pendingOptimistic.length }, { key: "settings", label: "설정" }] as const).map((item) => <button key={item.key} type="button" role="tab" aria-selected={tab === item.key} onClick={() => setTab(item.key)}>{item.label}{"count" in item ? <span>{item.count}</span> : null}</button>)}
        </div>
        {!detail ? <div className="bx-empty"><strong>{detailState.loading ? "장치 정보를 불러오는 중입니다" : "상세 정보를 표시할 수 없습니다"}</strong></div> : tab === "status" ? <StatusTab detail={detail} energy={energy} onOpenData={fleet.openData} /> : tab === "activity" ? <><ActivityTab commands={pendingOptimistic.length ? [...pendingOptimistic, ...detail.commands] : detail.commands} /></> : <SettingsTab node={activeNode} detail={detail} onEdit={() => { fleet.closeDevice(); fleet.openEdit(activeNode.node_id); }} onDanger={setConfirmKind} />}
      </div>
    </Dialog>
    <ConfirmDialog open={Boolean(confirmKind)} title={confirmKind === "hibernate" ? "장치를 절전 상태로 보낼까요?" : "장치 연결을 해제할까요?"}
      body={confirmKind === "hibernate" ? "다음 수동 깨우기 전까지 이 장치의 데이터 수집이 멈춥니다." : "장치 등록을 해제합니다. 대기 중인 작업은 만료됩니다."}
      confirmLabel={confirmKind === "hibernate" ? "절전" : "연결 해제"} requireText={confirmKind === "hibernate" ? activeNode.label : undefined}
      onClose={() => setConfirmKind(null)} onConfirm={() => doAction(confirmKind ?? "detach")} />
  </>;
}
