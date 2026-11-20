"use client";
import { useCallback, useRef, useState } from "react";
import type { BeaconDetail } from "../types";
import { useBeaconApi } from "../api-context";
import { usePolling } from "./usePolling";
type LoadState = { id: string | null; loading: boolean; error: string | null };
export function useBeaconDetail(nodeId: string | null, opts: { intervalMs: number; paused?: boolean }): { detail: BeaconDetail | null; error: string | null; loading: boolean; reload: () => void } {
  const api = useBeaconApi();
  const nodeRef = useRef(nodeId);
  nodeRef.current = nodeId;
  const [loaded, setLoaded] = useState<{ id: string; detail: BeaconDetail } | null>(null);
  const [state, setState] = useState<LoadState>({ id: nodeId, loading: Boolean(nodeId), error: null });
  const task = useCallback(async (signal: AbortSignal) => {
    if (!nodeId) { setState({ id: null, loading: false, error: null }); return; }
    setState((current) => current.id === nodeId ? { ...current, loading: true } : { id: nodeId, loading: true, error: null });
    try {
      const result = await api.getNode(nodeId, signal);
      if (!signal.aborted && nodeRef.current === nodeId) { setLoaded({ id: nodeId, detail: result }); setState({ id: nodeId, loading: false, error: null }); }
    } catch (cause) {
      if (signal.aborted) throw cause;
      if (nodeRef.current === nodeId) setState({ id: nodeId, loading: false, error: cause instanceof Error ? cause.message : "장치 정보를 불러오지 못했습니다." });
    }
  }, [api, nodeId]);
  const polling = usePolling(task, { intervalMs: opts.intervalMs, enabled: Boolean(nodeId) && !opts.paused, deps: [nodeId] });
  return { detail: nodeId && loaded?.id === nodeId ? loaded.detail : null, error: state.id === nodeId ? state.error : null, loading: state.id === nodeId ? state.loading : Boolean(nodeId), reload: polling.refresh };
}
