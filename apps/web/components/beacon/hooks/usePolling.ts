"use client";
import { useCallback, useEffect, useRef, useState } from "react";
export function usePolling(task: (signal: AbortSignal) => Promise<void>, opts: { intervalMs: number; enabled: boolean; deps?: unknown[] }): { refresh: () => void; failures: number } {
  const taskRef = useRef(task);
  taskRef.current = task;
  const [failures, setFailures] = useState(0);
  const [revision, setRevision] = useState(0);
  const depsKey = JSON.stringify(opts.deps ?? []);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    if (!opts.enabled) return;
    let active = true, running = false, rerun = false, localFailures = 0;
    let timer: number | undefined;
    let controller: AbortController | null = null;
    const clear = () => { if (timer !== undefined) window.clearTimeout(timer); timer = undefined; };
    const schedule = () => {
      if (!active || document.hidden) return;
      clear();
      const delay = localFailures >= 3 ? Math.max(opts.intervalMs, 30000) : opts.intervalMs;
      timer = window.setTimeout(() => { void run(); }, delay);
    };
    const run = async () => {
      if (!active || document.hidden) return;
      if (running) { rerun = true; return; }
      clear(); running = true; controller = new AbortController();
      try {
        await taskRef.current(controller.signal);
        if (active) { localFailures = 0; setFailures(0); }
      } catch (error) {
        if (active && !(error instanceof DOMException && error.name === "AbortError")) {
          localFailures += 1; setFailures(localFailures);
        }
      } finally {
        running = false;
        if (active && !document.hidden && rerun) { rerun = false; void run(); }
        else schedule();
      }
    };
    const onVisibility = () => {
      if (document.hidden) { clear(); controller?.abort(); }
      else { clear(); if (running) rerun = true; else void run(); }
    };
    void run();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      active = false; clear(); controller?.abort();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [opts.enabled, opts.intervalMs, depsKey, revision]);
  return { refresh, failures };
}
