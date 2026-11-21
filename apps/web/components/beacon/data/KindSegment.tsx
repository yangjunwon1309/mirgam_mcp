"use client";
import type { DeleteKind } from "../types";
import { Segmented } from "../ui/Segmented";
export function KindSegment({ kind, counts, onChange }: { kind: DeleteKind; counts: Record<DeleteKind, number>; onChange(value: DeleteKind): void }) {
  return <Segmented label="자료 종류" value={kind} onChange={onChange} options={([{value:"sensor",label:"센서"},{value:"image",label:"이미지"},{value:"checkin",label:"체크인"},{value:"command",label:"작업"}] as const).map((o) => ({...o,count:counts[o.value]}))} />;
}
