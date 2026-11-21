"use client";
import { useEffect, useRef, type MouseEvent, type ReactNode } from "react";
export function Dialog({ open, onClose, size = "md", labelledBy, className = "", children }: { open: boolean; onClose: () => void; size?: "md" | "lg"; labelledBy: string; className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const restore = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) { restore.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; dialog.showModal(); (dialog.querySelector<HTMLElement>("[autofocus]") ?? dialog.querySelector<HTMLElement>("[data-dialog-close]") ?? dialog.querySelector<HTMLElement>("button"))?.focus(); }
    if (!open && dialog.open) { dialog.close(); restore.current?.focus(); }
  }, [open]);
  useEffect(() => () => { if (ref.current?.open) restore.current?.focus(); }, []);
  const backdrop = (event: MouseEvent<HTMLDialogElement>) => { if (event.target === ref.current) onClose(); };
  return <dialog ref={ref} className={["bx-dialog", size === "lg" && "bx-dialog--lg", className].filter(Boolean).join(" ")} aria-labelledby={labelledBy} onClick={backdrop} onCancel={(event) => { event.preventDefault(); onClose(); }}>{children}</dialog>;
}
