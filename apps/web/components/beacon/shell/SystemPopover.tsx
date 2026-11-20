"use client";
import { useEffect, useRef, useState, type RefObject } from "react";
import { useBeaconFleet } from "../BeaconFleetProvider";
import { useToasts } from "../ui/Toasts";
type Pop = HTMLDivElement & { showPopover?: () => void; hidePopover?: () => void };
export function SystemPopover({ anchor, open, onClose }: { anchor: RefObject<HTMLButtonElement | null>; open: boolean; onClose(): void }) {
  const fleet = useBeaconFleet();
  const toasts = useToasts();
  const ref = useRef<Pop>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const [ports, setPorts] = useState<{ port: string; kind: string; label?: string }[]>([]);
  const [usbReachable, setUsbReachable] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [resetting, setResetting] = useState<string | null>(null);
  useEffect(() => {
    const pop = ref.current;
    const button = anchor.current;
    if (!pop || !button) return;
    if (open) {
      pop.showPopover?.();
      const rect = button.getBoundingClientRect();
      pop.style.left = Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, rect.left)) + "px";
      pop.style.top = Math.max(8, Math.min(window.innerHeight - pop.offsetHeight - 8, rect.bottom + 8)) + "px";
      void loadPorts();
    } else pop.hidePopover?.();
  }, [open, anchor]);
  async function loadPorts() {
    setLoading(true);
    try { const result = await fleet.api.listUsb(); setUsbReachable(result.reachable); setPorts(result.ports ?? []); }
    catch (cause) { setUsbReachable(false); setPorts([]); toasts.push({ title: "USB 포트 목록을 불러오지 못했습니다.", body: cause instanceof Error ? cause.message : undefined, tone: "error" }); }
    finally { setLoading(false); }
  }
  async function resetPort(port: string) {
    const before = new Map(fleet.allNodes.map((node) => [node.node_id, node.last_seen ?? 0]));
    setResetting(port);
    try {
      await fleet.api.resetUsb(port);
      const deadline = Date.now() + 45000;
      let confirmed = false;
      while (Date.now() < deadline) {
        await new Promise((resolve) => window.setTimeout(resolve, 1800));
        const result = await fleet.api.listNodes();
        fleet.refreshNodes();
        confirmed = result.nodes.some((node) => Boolean(node.last_seen && node.last_seen > (before.get(node.node_id) ?? 0) + 0.5));
        if (confirmed) break;
      }
      toasts.push({ title: confirmed ? "리셋 후 새 체크인을 확인했습니다." : "리셋 신호를 보냈지만 새 체크인은 아직 없습니다.", body: confirmed ? "USB 포트와 장치의 연결 관계는 확인되지 않았습니다." : "Wi-Fi 설정과 서버 주소를 확인하세요.", tone: confirmed ? "ok" : "wait" });
    } catch (cause) { toasts.push({ title: "USB 리셋에 실패했습니다.", body: cause instanceof Error ? cause.message : undefined, tone: "error" }); }
    finally { setResetting(null); }
  }
  return <div ref={ref} className="bx-pop bx-sys-pop" popover="auto" onToggle={(event) => { if (event.newState === "closed") closeRef.current(); }}>
    <div className="sec"><strong>Beacon 수신 서버</strong><small>Wi-Fi 체크인 :8080 · 관리 API는 내부 네트워크 전용</small></div>
    <div className="sec"><strong>USB 직렬 포트</strong><small>연결된 보드의 리셋 신호와 체크인을 확인합니다.</small>
      {loading ? <p>포트를 확인하고 있습니다…</p> : usbReachable === false ? <p>Beacon 컨테이너에 연결할 수 없습니다.</p> : ports.length ? ports.map((port) => <div className="port" key={port.port}><span className="ic">USB</span><div><strong>{port.label ?? "/dev/" + port.port}</strong><small>{port.kind}</small></div><button type="button" disabled={resetting !== null} onClick={() => void resetPort(port.port)}>{resetting === port.port ? "확인 중…" : "리셋 후 확인"}</button></div>) : <p>USB 직렬 포트가 없습니다.</p>}
      <button type="button" className="bx-btn bx-btn--ghost" onClick={() => void loadPorts()}>포트 새로고침</button>
    </div>
  </div>;
}
