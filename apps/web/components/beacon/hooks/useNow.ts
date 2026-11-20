"use client";
import { useEffect, useState } from "react";
export function useNow(enabled: boolean, stepMs = 1000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!enabled) return;
    const update = () => setNow(Date.now() / 1000);
    update();
    const timer = window.setInterval(update, stepMs);
    return () => window.clearInterval(timer);
  }, [enabled, stepMs]);
  return now;
}
