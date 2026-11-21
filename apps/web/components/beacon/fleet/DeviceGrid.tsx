"use client";
import { useEffect, useRef } from "react";
import type { BeaconNode } from "../types";
import { EmptyState } from "../ui/EmptyState";
import { DeviceCard } from "./DeviceCard";
export function DeviceGrid({ nodes, emptyTitle, emptyBody, onOpen, onAdd, highlightId }: { nodes: BeaconNode[]; emptyTitle: string; emptyBody?: string; onOpen(id: string): void; onAdd(): void; highlightId: string | null }) {
  const highlightRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (highlightId) highlightRef.current?.scrollIntoView({ block: "nearest" }); }, [highlightId]);
  if (!nodes.length) return <EmptyState icon="beacon" title={emptyTitle} body={emptyBody} action={<button type="button" className="bx-btn bx-btn--primary" onClick={onAdd}>장치 추가</button>} />;
  return <div className="bx-cards">{nodes.map((node) => <div key={node.node_id} ref={node.node_id === highlightId ? (element) => { if (element) highlightRef.current = element.querySelector("button"); } : undefined}><DeviceCard node={node} onOpen={onOpen} highlighted={node.node_id === highlightId} /></div>)}<button type="button" className="bx-card-add" onClick={onAdd}><span>＋</span><strong>새 Beacon 연결</strong><small>주변에서 체크인한 장치를 등록합니다</small></button></div>;
}
