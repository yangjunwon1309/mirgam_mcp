"use client";
import { useRef, useState } from "react";
import { useBeaconFleet } from "../BeaconFleetProvider";
import { relTime } from "../format";
import { useNow } from "../hooks/useNow";
import { SystemPopover } from "./SystemPopover";
export function ContextBar({ onNavigate }: { onNavigate(tab: "farm" | "jeju-weather" | "data-server" | "beacon"): void }) {
  const fleet = useBeaconFleet();
  const anchor = useRef<HTMLButtonElement>(null);
  const [systemOpen, setSystemOpen] = useState(false);
  const now = useNow(true, 5000);
  const age = fleet.lastSyncAt === null ? null : Math.max(0, now - fleet.lastSyncAt);
  return <div className="bx-context">
    <label className="bx-farm-switch"><span className="sr-only">농장 선택</span><select value={fleet.farmId ?? ""} onChange={(event) => fleet.setFarmId(event.target.value || null)} aria-label="농장 선택">{fleet.farms.length ? fleet.farms.map((farm) => <option value={farm.id} key={farm.id}>{farm.name}</option>) : <option value="">농장을 먼저 등록하세요</option>}</select></label>
    {!fleet.farms.length ? <button type="button" className="bx-btn bx-btn--ghost" onClick={() => onNavigate("farm")}>농장 현황</button> : null}
    <button ref={anchor} type="button" className={"bx-sys-pill" + (fleet.reachable === false ? " danger" : "")} aria-expanded={systemOpen} onClick={() => setSystemOpen((value) => !value)}><i className={fleet.reachable ? "bx-pulse" : ""} />{fleet.reachable === true ? "수신 서버 정상" : fleet.reachable === false ? "수신 서버 연결 불가" : "확인 중"}<span>▾</span></button>
    <SystemPopover anchor={anchor} open={systemOpen} onClose={() => setSystemOpen(false)} />
    <button type="button" className="bx-sync" onClick={fleet.refreshNodes} aria-label="지금 동기화">↻ {age === null ? "동기화 대기" : relTime(age) + " 동기화"}</button>
    {fleet.reachable === false ? <p className="bx-context-warning" role="status">Beacon 서버에 연결할 수 없습니다. 저장된 정보만 표시합니다.</p> : null}
  </div>;
}
