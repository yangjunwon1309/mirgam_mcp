"use client";
import type { ReactNode } from "react";
import { Icon } from "./Icon";
import type { IconName } from "./Icon";
export function EmptyState({ icon, title, body, action }: { icon: IconName; title: string; body?: string; action?: ReactNode }) {
  return <div className="bx-empty"><span className="ic"><Icon name={icon} size={22} /></span><strong>{title}</strong>{body ? <p>{body}</p> : null}{action}</div>;
}
