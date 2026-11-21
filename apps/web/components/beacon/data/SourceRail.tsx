"use client";
import { useState } from "react";
import type { BeaconNode } from "../types";
import { health, relTime } from "../format";
export function SourceRail({ nodes, selected, onSelect }: { nodes: BeaconNode[]; selected: string | null; onSelect(id: string): void }) {
  const [query, setQuery] = useState("");
  return <aside className="bx-rail"><label className="bx-search"><span className="sr-only">장치 검색</span><input type="search" placeholder="이름 또는 ID 검색" value={query} onChange={(e) => setQuery(e.target.value)} /></label><h3>BEACONS · {nodes.length}</h3><div className="bx-rail-list">{nodes.filter((n) => `${n.label} ${n.node_id}`.toLowerCase().includes(query.toLowerCase())).map((node) => <button type="button" key={node.node_id} className="bx-source" aria-current={selected === node.node_id} onClick={() => onSelect(node.node_id)}><span className={"bx-dot bx-" + health(node).key} /><span><strong>{node.label}</strong><small>{node.last_seen ? relTime(Date.now()/1000-node.last_seen) : "기록 없음"}</small></span></button>)}</div><footer>센서 · SQLite<br />이미지 · SSD</footer></aside>;
}
