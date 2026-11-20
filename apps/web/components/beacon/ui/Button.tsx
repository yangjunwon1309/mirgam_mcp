"use client";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "./Icon";
import type { IconName } from "./Icon";
type Common = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & { variant: "primary" | "secondary" | "ghost" | "danger" | "danger-ghost" | "green"; size?: "sm"; icon?: IconName };
type Props = Common & ({ iconOnly: true; "aria-label": string; children?: never } | { iconOnly?: false; "aria-label"?: string; children?: ReactNode });
export function Button({ variant, size, icon, iconOnly, className, children, ...props }: Props) {
  const classes = ["bx-btn", "bx-btn--" + variant, size === "sm" ? "bx-btn--sm" : "", iconOnly ? "bx-btn--icon" : "", className ?? ""].filter(Boolean).join(" ");
  return <button {...props} className={classes}>{icon ? <Icon name={icon} size={16} /> : null}{children}</button>;
}
