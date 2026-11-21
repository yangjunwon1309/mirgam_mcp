"use client";
import { useEffect, useMemo, useState } from "react";
import type { FleetFilter } from "../types";
import { health } from "../format";
import { readUi, writeUi } from "../session";
import { useBeaconFleet } from "../BeaconFleetProvider";
import { FleetHero } from "./FleetHero";
import { DeviceGrid } from "./DeviceGrid";
import { DeviceDialog } from "./DeviceDialog";
import { AddBeaconDialog } from "./AddBeaconDialog";
import { EmptyState } from "../ui/EmptyState";
export function BeaconWorkspace() {
  const fleet = useBeaconFleet();
  const [filter, setFilter] = useState<FleetFilter>("all");
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const stored = readUi().filter; if (stored === "all" || stored === "ok" || stored === "warn" || stored === "offline") setFilter(stored);
  }, []);
  useEffect(() => { writeUi({ filter }); }, [filter]);
  useEffect(() => { const timer = window.setTimeout(() => setDebounced(query.trim().toLocaleLowerCase("ko-KR")), 120); return () => window.clearTimeout(timer); }, [query]);
  const shown = useMemo(() => fleet.nodes.filter((node) => {
    if (filter !== "all" && health(node).key !== filter) return false;
    const loc = node.metadata.location;
    const haystack = [node.label, node.node_id, loc?.site, loc?.zone, loc?.row, loc?.position].filter(Boolean).join(" ").toLocaleLowerCase("ko-KR");
    return !debounced || haystack.includes(debounced);
  }).sort((a, b) => {
    const rank = (node: typeof a) => { const key = health(node).key; return key === "offline" ? 0 : key === "warn" ? 1 : key === "ok" ? 2 : 3; };
    return rank(a) - rank(b) || a.label.localeCompare(b.label, "ko");
  }), [fleet.nodes, filter, debounced]);
  if (!fleet.farms.length) return <div className="bx-root"><EmptyState icon="pin" title="농장을 먼저 등록하세요" body="Beacon을 농장에 연결하려면 농장 정보가 필요합니다." action={<button type="button" className="bx-btn bx-btn--primary" onClick={() => fleet.navigate("farm")}>농장 현황으로 이동</button>} /></div>;
  return <div className="bx-root"><div className="bx-workspace">
    <FleetHero nodes={fleet.nodes} filter={filter} onFilter={setFilter} onAdd={fleet.openAdd} />
    <div className="bx-sec-head"><div><h2>장치{filter !== "all" ? " · " + (filter === "ok" ? "정상" : filter === "warn" ? "주의" : "오프라인") : ""}</h2><span>{shown.length}대</span></div><label className="bx-search"><span className="sr-only">이름·위치·ID 검색</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="이름·위치·ID 검색" /></label></div>
    {fleet.lastSyncAt === null && fleet.reachable === null ? <div className="bx-cards" aria-label="장치 불러오는 중">{[1, 2, 3].map((n) => <div className="bx-card bx-skeleton" key={n} />)}</div> : <DeviceGrid nodes={shown} emptyTitle={query || filter !== "all" ? "조건에 맞는 장치가 없습니다" : "이 농장에 연결된 Beacon이 없습니다"} emptyBody={query || filter !== "all" ? undefined : "새 장치를 등록하면 여기에서 상태와 센서값을 확인할 수 있습니다."} onOpen={fleet.openDevice} onAdd={fleet.openAdd} highlightId={fleet.highlightId} allowAdd={!query && filter === "all"} />}
    <DeviceDialog />
    <AddBeaconDialog />
  </div></div>;
}
