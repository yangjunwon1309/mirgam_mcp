"use client";
import type { BeaconNode } from "../types";
import { health, metricLabel, relTime, unitShort, value1 } from "../format";
import { Battery } from "../ui/Battery";
import { Icon } from "../ui/Icon";
import { Badge } from "../ui/Badge";
export function DeviceCard({ node, onOpen, highlighted }: { node: BeaconNode; onOpen(id: string): void; highlighted: boolean }) {
  const status = health(node);
  const location = node.metadata.location;
  const place = [location?.site, location?.zone, location?.row, location?.position].filter(Boolean).join(" · ") || "설치 위치 미지정";
  return <button type="button" className={"bx-card" + (node.online ? "" : " offline") + (highlighted ? " highlighted" : "")} aria-label={node.label + ", " + status.label + ", 상세 열기"} onClick={() => onOpen(node.node_id)}>
    <span className="bx-card-head"><span className="bx-dev-icon"><Icon name="beacon" size={22} /></span><span className="bx-card-title"><strong>{node.label}</strong><small>{place}</small></span><Badge tone={status.tone} dot>{status.label}</Badge></span>
    <span className="bx-card-values">{node.latest_readings.slice(0, 2).map((reading) => <span className="bx-card-reading" key={reading.sensor_id}><strong>{reading.value === null ? "—" : value1(reading.value)}<small>{unitShort(reading.unit)}</small></strong><small>{metricLabel(reading.sensor_type, reading.display_name)}</small></span>)}
      {!node.latest_readings.length ? <span className="bx-card-reading bx-card-wait"><strong>—</strong><small>수집 대기</small></span> : null}</span>
    <span className="bx-card-foot"><Battery mv={node.last_vbat_mv} showValue /><small>{node.last_seen === null ? "체크인 기록 없음" : relTime(Math.max(0, Date.now() / 1000 - node.last_seen))}</small>{node.pending_commands ? <b className="bx-pending">⏱ 대기 {node.pending_commands}</b> : null}</span>
  </button>;
}
