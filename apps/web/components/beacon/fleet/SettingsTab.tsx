"use client";
import type { BeaconDetail, BeaconNode } from "../types";
import { intervalLabel, dateTime } from "../format";
import { Button } from "../ui/Button";
export function SettingsTab({ node, detail, onEdit, onDanger }: { node: BeaconNode; detail: BeaconDetail | null; onEdit(): void; onDanger(kind: "hibernate" | "detach"): void }) {
  const loc = node.metadata.location;
  const location = [loc?.site, loc?.zone, loc?.row, loc?.position].filter(Boolean).join(" · ") || "설치 위치 미지정";
  const coords = typeof loc?.latitude === "number" && typeof loc.longitude === "number" ? loc.latitude.toFixed(6) + ", " + loc.longitude.toFixed(6) : "좌표 미지정";
  return <div className="bx-settings-tab">
    <dl className="bx-kv"><dt>표시 이름</dt><dd>{node.label}</dd><dt>설치 위치</dt><dd>{location} · {coords}</dd><dt>수집 주기</dt><dd>{intervalLabel(node.interval_s)}</dd><dt>수집 데이터</dt><dd>{node.requested_data.map((x) => x === "sensor" ? "센서" : "이미지").join(" · ") || "설정 없음"}</dd><dt>펌웨어</dt><dd>{node.fw ?? "정보 없음"}</dd><dt>최근 센서 보고</dt><dd>{detail?.sensors.map((s) => {
    const address = s.device.metadata.address;
    const suffix = address === undefined ? "" : " · 0x" + Number(address).toString(16).padStart(2, "0");
    return s.device.display_name + suffix + (s.latest_reading ? " · " + dateTime(s.latest_reading.recorded_at) : "");
  }).join(" / ") || "보고된 센서 없음"}</dd></dl>
    <Button variant="secondary" icon="gear" onClick={onEdit}>설정 편집</Button>
    <section className="bx-danger-zone"><strong>위험 구역</strong><div className="bx-dz-row"><div><strong>절전</strong><small>타이머 없이 장치 전원을 끕니다.</small></div><Button variant="danger-ghost" onClick={() => onDanger("hibernate")}>절전</Button></div><div className="bx-dz-row"><div><strong>연결 해제</strong><small>등록을 해제하고 체크인 주기를 늘립니다.</small></div><Button variant="danger-ghost" onClick={() => onDanger("detach")}>연결 해제</Button></div></section>
  </div>;
}
