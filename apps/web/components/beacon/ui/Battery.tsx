"use client";
import { vbatFill, vbatLevel } from "../format";
export function Battery({ mv, showValue = false }: { mv: number | null; showValue?: boolean }) {
  const level = vbatLevel(mv);
  const volts = mv === null ? "—" : (mv / 1000).toFixed(2) + " V";
  const status = level === "danger" ? "위험" : level === "warn" ? "낮음" : level === "idle" ? "정보 없음" : "정상";
  return <span className={"bx-batt " + (level === "idle" ? "" : "bx-" + level)} aria-label={"배터리 " + volts + ", " + status}><span className="bx-batt-bar"><i style={{ width: (vbatFill(mv) * 100) + "%" }} /></span>{showValue ? <span>{volts}</span> : null}</span>;
}
