"use client";
import type { SensorEntry } from "../types";
import { dateTime, metricLabel } from "../format";
import { Checkbox } from "../ui/Checkbox";
import { LineChart } from "./LineChart";
type Selection={has(id:string):boolean;toggle(id:string):void;setMany(ids:string[],on:boolean):void};
export function SensorView({sensors,metricId,onMetric,selectMode,selection}:{sensors:SensorEntry[];metricId:string|null;onMetric(id:string):void;selectMode:boolean;selection:Selection}) {
 const sensor=sensors.find(s=>s.device.sensor_id===metricId)??sensors[0]; if(!sensor)return <div className="bx-empty">저장된 센서가 없습니다.</div>;
 const ids=sensor.readings.map(r=>String(r.reading_id)); const count=ids.filter(selection.has).length;
 return <><div className="bx-metrics">{sensors.map(s=><button type="button" className="bx-metric" aria-pressed={s.device.sensor_id===sensor.device.sensor_id} key={s.device.sensor_id} onClick={()=>onMetric(s.device.sensor_id)}><span>{metricLabel(s.device.sensor_type,s.device.display_name)}</span><strong>{s.latest_reading?.value??"—"} {s.device.unit}</strong><small>{s.reading_count}건 저장</small></button>)}</div><LineChart points={sensor.readings.map(r=>({t:Date.parse(r.recorded_at),v:r.value}))} unit={sensor.device.unit}/><div className="bx-table-scroll"><table className="bx-table"><thead><tr>{selectMode&&<th scope="col"><Checkbox ariaLabel="보이는 측정 전체 선택" checked={ids.length>0&&count===ids.length} indeterminate={count>0&&count<ids.length} onChange={v=>selection.setMany(ids,v)}/></th>}<th scope="col">수신 시각</th><th scope="col">값</th><th scope="col">단위</th><th scope="col">품질</th></tr></thead><tbody>{[...sensor.readings].reverse().map(r=><tr key={r.reading_id}>{selectMode&&<td><Checkbox ariaLabel={`${dateTime(r.recorded_at)} 측정 선택`} checked={selection.has(String(r.reading_id))} onChange={()=>selection.toggle(String(r.reading_id))}/></td>}<td>{dateTime(r.recorded_at)}</td><td>{r.value}</td><td>{r.unit}</td><td>{!r.quality||["ok","reported"].includes(r.quality)?"정상":"확인 필요"}</td></tr>)}</tbody></table></div><p className="bx-hint">최근 {sensor.readings.length}건 표시 · 전체 {sensor.reading_count}건 — 오래된 기록은 기간으로 삭제할 수 있습니다.</p></>;
}
