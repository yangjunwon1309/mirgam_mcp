"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { createBeaconApi } from "../api";
import type { DeleteKind, DeleteRequest } from "../types";
type Api = ReturnType<typeof createBeaconApi>;
type Toasts = { push(input: { title: string; body?: string; tone?: "ok" | "wait" | "error"; action?: { label: string; onClick: () => void }; durationMs?: number | null }): string };
type Item = { id: string; t: number; sensorId?: string };
type Pending = { key: string; nodeId: string; kind: DeleteKind; request: DeleteRequest; label: string; count: number; hides: (item: Item) => boolean; timer: number; started: boolean };
const kindLabel: Record<DeleteKind, string> = { sensor: "센서", image: "이미지", checkin: "체크인", command: "작업" };
const kindUnit: Record<DeleteKind, string> = { sensor: "건", image: "장", checkin: "건", command: "건" };
export function usePendingDeletes(api: Api, toasts: Toasts, onCommitted: (nodeId: string) => void): {
  schedule(p: Omit<Pending, "key" | "timer" | "started">): void; undo(key: string): void;
  isHidden(nodeId: string, kind: DeleteKind, item: Item): boolean; hasPending(nodeId: string): boolean;
} {
  const [pending, setPending] = useState<Pending[]>([]);
  const latest = useRef(pending); latest.current = pending;
  const commit = useCallback(async (entry: Pending) => {
    try {
      const result = await api.deleteData(entry.nodeId, entry.request);
      if (result.deleted < entry.count) {
        const reason = result.skipped_current ? " 최신 체크인은 보존했습니다." : result.skipped_busy ? " 진행 중 작업은 건너뛰었습니다." : "";
        toasts.push({ title: "요청 " + entry.count + "건 중 " + result.deleted + "건만 삭제되었습니다.", body: reason, tone: "wait" });
      } else toasts.push({ title: entry.label + " " + result.deleted + kindUnit[entry.kind] + " 삭제했습니다.", tone: "ok" });
      setPending((all) => all.filter((p) => p.key !== entry.key));
      onCommitted(entry.nodeId);
    } catch (error) {
      setPending((all) => all.filter((p) => p.key !== entry.key));
      const message = error instanceof Error ? error.message : "삭제하지 못했습니다.";
      const retry = async () => {
        try {
          const result = await api.deleteData(entry.nodeId, entry.request);
          toasts.push({ title: entry.label + " " + result.deleted + kindUnit[entry.kind] + " 삭제했습니다.", tone: "ok" });
          onCommitted(entry.nodeId);
        } catch (cause) {
          toasts.push({ title: "다시 삭제하지 못했습니다.", body: cause instanceof Error ? cause.message : "요청을 완료하지 못했습니다.", tone: "error", durationMs: null });
        }
      };
      toasts.push({ title: "삭제하지 못했습니다.", body: message, tone: "error", durationMs: null, action: { label: "다시 시도", onClick: () => { void retry(); } } });
    }
  }, [api, onCommitted, toasts]);
  const schedule = useCallback((input: Omit<Pending, "key" | "timer" | "started">) => {
    const key = "delete-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    const entry = { ...input, key, timer: 0, started: false } as Pending;
    entry.timer = window.setTimeout(() => { entry.started = true; void commit(entry); }, 6000);
    setPending((all) => [...all, entry]);
    toasts.push({ title: kindLabel[input.kind] + " " + input.count + kindUnit[input.kind] + " 삭제 대기", body: input.label + " · 6초 후 서버에서 확정됩니다", tone: "wait", durationMs: 6000, action: { label: "실행 취소", onClick: () => { if (entry.started) { toasts.push({ title: "이미 삭제 요청을 보내 취소할 수 없습니다.", tone: "wait" }); return; } window.clearTimeout(entry.timer); setPending((all) => all.filter((p) => p.key !== key)); } } });
  }, [commit, toasts]);
  const undo = useCallback((key: string) => {
    const entry = latest.current.find((p) => p.key === key);
    if (entry?.started) return;
    if (entry) window.clearTimeout(entry.timer);
    setPending((all) => all.filter((p) => p.key !== key));
  }, []);
  const isHidden = useCallback((nodeId: string, kind: DeleteKind, item: Item) => pending.some((p) => p.nodeId === nodeId && p.kind === kind && p.hides(item)), [pending]);
  const hasPending = useCallback((nodeId: string) => pending.some((p) => p.nodeId === nodeId), [pending]);
  useEffect(() => {
    const stop = () => { latest.current.forEach((p) => window.clearTimeout(p.timer)); setPending([]); };
    window.addEventListener("pagehide", stop);
    return () => { window.removeEventListener("pagehide", stop); latest.current.forEach((p) => window.clearTimeout(p.timer)); };
  }, []);
  return useMemo(() => ({ schedule, undo, isHidden, hasPending }), [schedule, undo, isHidden, hasPending]);
}
