"use client";
import { useEffect, useRef } from "react";
export function Checkbox({ checked, indeterminate = false, disabled = false, title, onChange, ariaLabel }: { checked: boolean; indeterminate?: boolean; disabled?: boolean; title?: string; onChange: (checked: boolean) => void; ariaLabel: string }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate; }, [indeterminate]);
  return <input ref={ref} className="bx-checkbox" type="checkbox" checked={checked} disabled={disabled} title={title} aria-label={ariaLabel} onChange={(event) => onChange(event.target.checked)} />;
}
