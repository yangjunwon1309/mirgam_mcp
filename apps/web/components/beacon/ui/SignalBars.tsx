"use client";
import { signalLevel } from "../format";
export function SignalBars({ rssi }: { rssi: number | null }) {
  const level = signalLevel(rssi);
  const label = rssi === null ? "신호 정보 없음" : "신호 " + String(rssi).replace("-", "−") + " dBm";
  return <span className={"bx-sig bx-l" + level} aria-label={label}>{[1, 2, 3, 4].map((n) => <i key={n} />)}</span>;
}
