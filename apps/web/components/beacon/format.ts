import type { BeaconNode, CommandState, HealthKey } from "./types";

export const VBAT_WARN = 3450;
export const VBAT_CRIT = 3300;
export type Health = { key: HealthKey; label: string; tone: "ok" | "warn" | "danger" | "green" | "idle" };
export function health(node: Pick<BeaconNode, "state" | "online" | "last_vbat_mv" | "next_given" | "interval_s">): Health {
  if (node.state !== "ATTACHED") {
    const labels: Record<string, string> = { DISCOVERED: "발견됨", DETACHED: "연결 해제", HIBERNATING: "절전", UNKNOWN: "정보 없음" };
    return { key: "idle", label: labels[node.state] ?? "정보 없음", tone: "idle" };
  }
  if (!node.online) return { key: "offline", label: "오프라인", tone: "danger" };
  if (node.last_vbat_mv !== null && node.last_vbat_mv < VBAT_CRIT) return { key: "warn", label: "배터리 위험", tone: "danger" };
  if (node.last_vbat_mv !== null && node.last_vbat_mv < VBAT_WARN) return { key: "warn", label: "배터리 낮음", tone: "warn" };
  if (node.next_given !== null && node.next_given <= 60 && node.interval_s > 60) return { key: "ok", label: "자주 확인 중", tone: "green" };
  return { key: "ok", label: "정상", tone: "ok" };
}
export function vbatLevel(mv: number | null): "danger" | "warn" | "ok" | "idle" {
  if (mv === null) return "idle";
  if (mv < VBAT_CRIT) return "danger";
  if (mv < VBAT_WARN) return "warn";
  return "ok";
}
export function vbatFill(mv: number | null): number {
  if (mv === null) return 0.06;
  return Math.max(0.06, Math.min(1, (mv - 3300) / (4200 - 3300)));
}
export function signalLevel(rssi: number | null): number {
  if (rssi === null) return 0;
  if (rssi >= -55) return 4;
  if (rssi >= -67) return 3;
  if (rssi >= -75) return 2;
  return 1;
}
export function relTime(sec: number | null): string {
  if (sec === null || !Number.isFinite(sec) || sec < 45) return "방금";
  if (sec < 3600) return Math.floor(sec / 60) + "분 전";
  if (sec < 86400) return Math.floor(sec / 3600) + "시간 전";
  return Math.floor(sec / 86400) + "일 전";
}
export function countdown(sec: number): string {
  if (sec <= 0) return "곧";
  if (sec < 60) return Math.floor(sec) + "초";
  return Math.floor(sec / 60) + "분 " + String(Math.floor(sec % 60)).padStart(2, "0") + "초";
}
export function intervalLabel(sec: number): string {
  if (sec % 3600 === 0) return sec / 3600 + "시간";
  if (sec % 60 === 0) return sec / 60 + "분";
  return sec + "초";
}
type TimeValue = number | string | null;
function date(value: TimeValue): Date | null {
  if (value === null) return null;
  const d = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(d.getTime()) ? null : d;
}
export function clock(t: TimeValue): string {
  const d = date(t);
  return d ? new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false }).format(d) : "—";
}
export function dateTime(t: TimeValue): string {
  const d = date(t);
  return d ? new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(d) : "—";
}
export function dayLabel(t: TimeValue): string {
  const d = date(t);
  return d ? new Intl.DateTimeFormat("ko-KR", { month: "long", day: "numeric", weekday: "short" }).format(d) : "날짜 미상";
}
export function bytes(n: number | null): string {
  if (n === null) return "크기 미상";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / (1024 * 1024)).toFixed(2) + " MB";
}
export function metricLabel(sensorType: string, fallback: string): string {
  const labels: Record<string, string> = { temperature: "온도", humidity: "습도", soil_moisture: "토양 수분", illuminance: "조도", co2: "CO₂" };
  return labels[sensorType] ?? fallback;
}
export function unitShort(unit: string): string { return unit === "%RH" ? "%" : unit; }
export function value1(v: number): string { return v.toFixed(1); }
export function commandLabel(type: string): string {
  const labels: Record<string, string> = { sensor: "센서 읽기", image: "촬영", config: "설정 변경", hibernate: "절전" };
  return labels[type] ?? "작업";
}
export function commandStateLabel(state: CommandState): string {
  const labels: Record<CommandState, string> = { queued: "대기 중", dispatched: "전달됨", done: "완료", failed: "실패", expired: "만료" };
  return labels[state];
}
export function failReason(reason: string | null): string {
  if (!reason) return "실패 이유 없음";
  const labels: Record<string, string> = { no_result: "결과 없음(3회 전달)", low_battery: "배터리 부족으로 거부", expired: "만료", sensor_absent: "센서 없음" };
  return labels[reason] ?? reason;
}
export type DeliveryInfo = { pct: number | null; left: number | null; late: boolean; note: string | null };
export function deliveryInfo(node: Pick<BeaconNode, "last_seen" | "next_given" | "next_expected_at" | "interval_s">, now: number): DeliveryInfo {
  const pct = node.last_seen === null || !node.next_given ? null : Math.max(0, Math.min(100, ((now - node.last_seen) / node.next_given) * 100));
  const left = node.next_expected_at === null ? null : node.next_expected_at - now;
  const note = node.next_given !== null && node.next_given <= 60 && node.interval_s > 60 ? "자주 확인 모드" : node.next_given !== null && node.next_given > node.interval_s ? "저전압으로 연장됨" : null;
  return { pct, left, late: left !== null && left < -30, note };
}
