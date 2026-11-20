"use client";
import type { HTMLAttributes, ReactNode } from "react";
export function Badge({ tone, dot = false, children, className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone: "ok" | "warn" | "danger" | "green" | "idle" | "orange"; dot?: boolean; children: ReactNode }) {
  return <span {...props} className={["bx-badge", "bx-badge--" + tone, dot ? "bx-badge--dot" : "", className ?? ""].filter(Boolean).join(" ")}>{children}</span>;
}
