"use client";
import { useEffect, useRef, type RefObject } from "react";
import { Icon } from "./Icon";
import type { IconName } from "./Icon";
type Item = { label: string; hint?: string; icon?: IconName; danger?: boolean; onSelect: () => void; kbd?: string };
type Entry = Item | "sep" | { heading: string };
type PopoverDiv = HTMLDivElement & { showPopover?: () => void; hidePopover?: () => void };
export function Menu({ anchor, open, onClose, items }: { anchor: RefObject<HTMLElement | null>; open: boolean; onClose: () => void; items: Entry[] }) {
  const ref = useRef<PopoverDiv>(null);
  useEffect(() => {
    const menu = ref.current;
    const element = anchor.current;
    if (!menu || !element) return;
    if (open) {
      menu.showPopover?.();
      const rect = element.getBoundingClientRect();
      menu.style.left = Math.max(8, Math.min(window.innerWidth - menu.offsetWidth - 8, rect.left)) + "px";
      menu.style.top = Math.max(8, Math.min(window.innerHeight - menu.offsetHeight - 8, rect.bottom + 6)) + "px";
      menu.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    } else menu.hidePopover?.();
  }, [open, anchor]);
  const move = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
    const current = buttons.indexOf(document.activeElement as HTMLElement);
    let index = current;
    if (event.key === "ArrowDown") index = (current + 1) % buttons.length;
    else if (event.key === "ArrowUp") index = (current - 1 + buttons.length) % buttons.length;
    else if (event.key === "Home") index = 0;
    else if (event.key === "End") index = buttons.length - 1;
    else if (event.key === "Escape") { onClose(); return; }
    else return;
    event.preventDefault(); buttons[index]?.focus();
  };
  return <div ref={ref} className="bx-pop" popover="auto" role="menu" onKeyDown={move} onToggle={(event) => { if (event.newState === "closed") onClose(); }}>
    {items.map((item, index) => item === "sep" ? <div className="bx-menu-sep" key={"sep-" + index} /> : "heading" in item ? <div className="bx-menu-label" key={"head-" + index}>{item.heading}</div> : <button type="button" role="menuitem" className={"bx-menu-item" + (item.danger ? " bx-danger" : "")} key={item.label} onClick={() => { ref.current?.hidePopover?.(); item.onSelect(); }}><span>{item.icon ? <Icon name={item.icon} size={16} /> : null}{item.label}{item.hint ? <small>{item.hint}</small> : null}</span>{item.kbd ? <kbd>{item.kbd}</kbd> : null}</button>)}
  </div>;
}
