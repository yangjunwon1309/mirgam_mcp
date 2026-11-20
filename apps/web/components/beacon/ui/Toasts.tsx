"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { RefObject } from "react";
type ToastInput = { title: string; body?: string; tone?: "ok" | "wait" | "error"; action?: { label: string; onClick: () => void }; durationMs?: number | null };
type Toast = ToastInput & { id: string };
type ToastContextType = { push(input: ToastInput): string };
const ToastContext = createContext<ToastContextType | null>(null);
type PopoverDiv = HTMLDivElement & { showPopover?: () => void; hidePopover?: () => void };
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const timers = useRef(new Map<string, number>());
  const push = useCallback((input: ToastInput) => {
    const id = "toast-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    setItems((current) => [...current.slice(-2), { ...input, id }]);
    return id;
  }, []);
  useEffect(() => () => { timers.current.forEach(window.clearTimeout); timers.current.clear(); }, []);
  const value = useMemo(() => ({ push }), [push]);
  return <ToastContext.Provider value={value}>{children}<ToastStack items={items} setItems={setItems} timers={timers} /></ToastContext.Provider>;
}
export function useToasts(): ToastContextType {
  const value = useContext(ToastContext);
  if (!value) throw new Error("ToastProvider가 필요합니다.");
  return value;
}
function ToastStack({ items, setItems, timers }: { items: Toast[]; setItems: React.Dispatch<React.SetStateAction<Toast[]>>; timers: RefObject<Map<string, number>> }) {
  const ref = useRef<PopoverDiv>(null);
  useEffect(() => {
    const pop = ref.current;
    if (!pop) return;
    if (items.length) { pop.hidePopover?.(); pop.showPopover?.(); } else pop.hidePopover?.();
  }, [items.length]);
  const close = (id: string) => { const timer = timers.current?.get(id); if (timer) window.clearTimeout(timer); timers.current?.delete(id); setItems((all) => all.filter((item) => item.id !== id)); };
  const arm = (item: Toast) => {
    const duration = item.durationMs === undefined ? 5000 : item.durationMs;
    if (duration === null) return;
    const timer = window.setTimeout(() => close(item.id), duration);
    timers.current?.set(item.id, timer);
  };
  useEffect(() => {
    const visible = new Set(items.map((item) => item.id));
    timers.current?.forEach((timer, id) => { if (!visible.has(id)) { window.clearTimeout(timer); timers.current?.delete(id); } });
    items.forEach((item) => { if (!timers.current?.has(item.id)) arm(item); });
  }, [items]);
  return <div ref={ref} className="bx-toasts" popover="manual" aria-live="polite">
    {items.map((item) => <article className="bx-toast" key={item.id} onMouseEnter={() => { const timer = timers.current?.get(item.id); if (timer) window.clearTimeout(timer); timers.current?.delete(item.id); }} onMouseLeave={() => arm(item)}>
      <i className="ic" aria-hidden="true">{item.tone === "error" ? "!" : "✓"}</i><div><strong>{item.title}</strong>{item.body ? <small>{item.body}</small> : null}</div>
      {item.action ? <button type="button" className="bx-toast-action" onClick={() => { item.action?.onClick(); close(item.id); }}>{item.action.label}</button> : <button type="button" aria-label="알림 닫기" onClick={() => close(item.id)}>×</button>}
    </article>)}
  </div>;
}
