"use client";
import { useMemo } from "react";
import type { BeaconNode, FleetFilter } from "../types";
import { health, relTime } from "../format";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
export function FleetHero({ nodes, filter, onFilter, onAdd }: { nodes: BeaconNode[]; filter: FleetFilter; onFilter(value: FleetFilter): void; onAdd(): void }) {
  const counts = useMemo(() => nodes.reduce((acc, node) => { acc[health(node).key] += 1; return acc; }, { ok: 0, warn: 0, offline: 0, idle: 0 }), [nodes]);
  const newest = nodes.reduce<number | null>((max, node) => node.last_seen === null ? max : max === null ? node.last_seen : Math.max(max, node.last_seen), null);
  const pending = nodes.reduce((sum, node) => sum + node.pending_commands, 0);
  const filters: { key: FleetFilter; label: string; value: number; dot?: string }[] = [
    { key: "all", label: "전체", value: nodes.length }, { key: "ok", label: "정상", value: counts.ok, dot: "ok" },
    { key: "warn", label: "주의", value: counts.warn, dot: "warn" }, { key: "offline", label: "오프라인", value: counts.offline, dot: "danger" },
  ];
  return <section className="bx-hero" aria-label="Beacon 상태 요약">
    <span className="eyebrow">FARM NETWORK</span>
    <div className="bx-hero-main"><div><h2>Beacon <b>{nodes.length}</b>대 연결</h2><p>마지막 수신 {newest === null ? "기록 없음" : relTime(Math.max(0, Date.now() / 1000 - newest))} · 전달 대기 {pending}건</p></div>
      <div className="bx-hero-filters" role="group" aria-label="장치 상태 필터">{filters.map((item) => <button key={item.key} type="button" aria-pressed={filter === item.key} onClick={() => onFilter(item.key)}><i className={item.dot ? "bx-hero-dot " + item.dot : ""} />{item.label} <b>{item.value}</b></button>)}</div>
      <Button variant="primary" icon="plus" onClick={onAdd}>장치 추가</Button>
    </div>
  </section>;
}
