"use client";
import { useNow } from "../hooks/useNow";
import type { BeaconNode } from "../types";
import { countdown, dateTime, deliveryInfo, intervalLabel } from "../format";
export function DeliveryBar({ node }: { node: BeaconNode }) {
  const now = useNow(true);
  const info = deliveryInfo(node, now);
  const offline = node.state === "ATTACHED" && !node.online;
  const title = offline ? "다시 연결되면 대기 작업이 전달됩니다" : info.late ? Math.ceil(Math.abs(info.left ?? 0) / 60) + "분 지연" : info.left === null ? "다음 체크인 시각을 기다리는 중입니다" : "요청은 다음 체크인에 전달됩니다";
  return <section className={"bx-delivery" + (offline ? " offline" : "")} aria-label="다음 체크인 전달 상태">
    <div className="bx-delivery-head"><strong>⏱ {title}</strong><b>{offline ? "체크인 대기 중" : info.left === null ? "—" : "약 " + countdown(info.left) + " 후"}</b></div>
    <div className="bx-cycle"><span style={{ width: (offline ? 100 : info.pct ?? 0) + "%" }} /></div>
    <div className="bx-delivery-foot"><span>마지막 체크인 {node.last_seen === null ? "기록 없음" : dateTime(node.last_seen)}</span><span>주기 {intervalLabel(node.interval_s)}{info.note ? " · " + info.note : ""}</span></div>
  </section>;
}
