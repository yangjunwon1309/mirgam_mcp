"use client";
import { useCallback, useMemo, useState } from "react";
export function useSelection(): { ids: Set<string>; has(id: string): boolean; toggle(id: string): void; setMany(ids: string[], on: boolean): void; clear(): void; size: number } {
  const [ids, setIds] = useState<Set<string>>(() => new Set());
  const toggle = useCallback((id: string) => setIds((current) => {
    const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next;
  }), []);
  const setMany = useCallback((values: string[], on: boolean) => setIds((current) => {
    const next = new Set(current); values.forEach((id) => on ? next.add(id) : next.delete(id)); return next;
  }), []);
  const clear = useCallback(() => setIds(new Set()), []);
  const has = useCallback((id: string) => ids.has(id), [ids]);
  return useMemo(() => ({ ids, has, toggle, setMany, clear, size: ids.size }), [ids, has, toggle, setMany, clear]);
}
