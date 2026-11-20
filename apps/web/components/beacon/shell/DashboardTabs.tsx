"use client";
import type { KeyboardEvent } from "react";
import { useBeaconFleet, type DashboardTab } from "../BeaconFleetProvider";
const tabs: { value: DashboardTab; label: string }[] = [
  { value: "farm", label: "농장 현황" }, { value: "jeju-weather", label: "제주 날씨" }, { value: "beacon", label: "Beacon" }, { value: "data-server", label: "데이터 서버" },
];
export function DashboardTabs({ value, onChange }: { value: DashboardTab; onChange(tab: DashboardTab): void }) {
  const { nodes } = useBeaconFleet();
  const keyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = tabs.findIndex((tab) => tab.value === value);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else return;
    event.preventDefault(); onChange(tabs[next].value);
    document.getElementById("dashboard-tab-" + tabs[next].value)?.focus();
  };
  return <nav className="bx-tabs" role="tablist" aria-label="대시보드 화면 선택">{tabs.map((tab) => <button id={"dashboard-tab-" + tab.value} key={tab.value} className={"bx-tab" + (value === tab.value ? " active" : "")} type="button" role="tab" aria-selected={value === tab.value} tabIndex={value === tab.value ? 0 : -1} onClick={() => onChange(tab.value)} onKeyDown={keyDown}><span aria-hidden="true">▰</span>{tab.label}{tab.value === "beacon" ? <span className="bx-tab-count">{nodes.length}</span> : null}</button>)}</nav>;
}
