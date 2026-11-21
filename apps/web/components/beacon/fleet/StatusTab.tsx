"use client";
import type { BeaconDetail, Energy } from "../types";
import { Battery } from "../ui/Battery";
import { SignalBars } from "../ui/SignalBars";
import { Sparkline } from "../ui/Sparkline";
import { dateTime, metricLabel, value1 } from "../format";
function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}
function text(value: unknown): string { return value === null || value === undefined || value === "" ? "—" : String(value); }
export function StatusTab({ detail, energy, onOpenData }: { detail: BeaconDetail; energy: Energy | null; onOpenData(nodeId: string, sensorId?: string): void }) {
  const node = detail.node;
  const checkins = detail.checkins;
  const bat = checkins.map((x) => x.vbat_mv).filter((x): x is number => typeof x === "number");
  const rssi = checkins.map((x) => x.rssi).filter((x): x is number => typeof x === "number");
  const wifi = checkins.map((x) => x.wifi_ms).filter((x): x is number => typeof x === "number");
  const awake = checkins.map((x) => x.prev_awake_ms).filter((x): x is number => typeof x === "number");
  const fast = checkins.filter((x) => x.fast === 1).length;
  return <div className="bx-status-tab">
    <div className="bx-stat-grid">
      <section className="bx-stat"><span className="lab">배터리</span><strong className="v">{node.last_vbat_mv === null ? "—" : (node.last_vbat_mv / 1000).toFixed(2)}<small> V</small></strong><Battery mv={node.last_vbat_mv} /><Sparkline values={bat} color="var(--ok)" />{!checkins.length ? <small>체크인 기록 없음</small> : null}</section>
      <section className="bx-stat"><span className="lab">Wi-Fi 신호</span><strong className="v">{node.last_rssi === null ? "—" : String(node.last_rssi).replace("-", "−")}<small> dBm</small><SignalBars rssi={node.last_rssi} /></strong><small>채널 {text(node.last_ch)} · IP {text(node.last_ip)}</small><Sparkline values={rssi} color="var(--green)" /></section>
      <section className="bx-stat"><span className="lab">Wi-Fi 접속</span><strong className="v">{median(wifi) === null ? "—" : Math.round(median(wifi) as number)}<small> ms 중앙값</small></strong><small>빠른 접속 {checkins.length ? Math.round((fast / checkins.length) * 100) : 0}% · {checkins.length}회</small></section>
      <section className="bx-stat"><span className="lab">깨어 있는 시간</span><strong className="v">{median(awake) === null ? "—" : Math.round(median(awake) as number)}<small> ms 중앙값</small></strong><small>일반 상한 25초 · 세션 상한 180초</small></section>
    </div>
    <div className="bx-sec-title"><strong>연결된 센서</strong><span>{detail.sensors.length}종</span></div>
    {detail.sensors.length ? detail.sensors.map((sensor) => {
      const meta = sensor.device.metadata;
      const model = text(meta.model ?? meta.sensor_type);
      const addr = meta.address === undefined ? "" : " · 0x" + Number(meta.address).toString(16).padStart(2, "0");
      const reading = sensor.latest_reading;
      return <button type="button" className="bx-sensor-row" key={sensor.device.sensor_id} onClick={() => onOpenData(node.node_id, sensor.device.sensor_id)}>
        <span className="bx-s-ico"><span aria-hidden="true">◉</span></span><span><strong>{metricLabel(sensor.device.sensor_type, sensor.device.display_name)}</strong><small>{model}{addr} · {reading ? dateTime(reading.recorded_at) : "측정 대기"}</small></span><span className="val">{reading ? value1(reading.value) : "—"} <small>{reading?.unit ?? sensor.device.unit}</small></span><span className="bx-sensor-link">데이터 서버 ›</span>
      </button>;
    }) : <p className="bx-muted">센서 정보가 아직 보고되지 않았습니다.</p>}
    <section className="bx-energy"><span className="lab">전력 사용 추정</span><strong className="big">{energy ? energy.estimated_mAh_day.toFixed(2) + " mAh/일" : "자료 없음"}</strong><span className="lab">만충 기준 수명</span><strong className="big">{energy?.estimated_days_remaining === null || !energy ? "자료 없음" : energy.estimated_days_remaining > 365 ? "1년 이상" : "약 " + Math.round(energy.estimated_days_remaining) + "일"}</strong><small className="note">계산 가정에 따른 추정값입니다. 배터리·활성 전류 실측값은 반영되지 않았습니다.</small></section>
  </div>;
}
