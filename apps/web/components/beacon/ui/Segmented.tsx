"use client";
import type { ReactNode } from "react";
type Option<T extends string> = { value: T; label: string; icon?: ReactNode; count?: number };
export function Segmented<T extends string>({ options, value, onChange, label }: { options: Option<T>[]; value: T; onChange: (value: T) => void; label?: string }) {
  return <div className="bx-segmented" role="group" aria-label={label}>{options.map((option) => <button key={option.value} type="button" aria-pressed={option.value === value} onClick={() => onChange(option.value)}>{option.icon}{option.label}{option.count !== undefined ? <span>{option.count}</span> : null}</button>)}</div>;
}
