"use client";
import { useEffect, useState } from "react";
import type { DeleteKind } from "../types";
import { useBeaconFleet } from "../BeaconFleetProvider";
import { useBeaconDetail } from "../hooks/useBeaconDetail";
import { useSelection } from "../hooks/useSelection";
import { downloadCsv, toCsv } from "../csv";
import { SourceRail } from "./SourceRail";
import { KindSegment } from "./KindSegment";
import { SensorView } from "./SensorView";
import { ImageGallery } from "./ImageGallery";
import { Lightbox } from "./Lightbox";
import { CheckinTable } from "./CheckinTable";
import { CommandTable } from "./CommandTable";
export function DataWorkspace() {
 const fleet=useBeaconFleet(),[nodeId,setNodeId]=useState<string|null>(fleet.dataSelection?.nodeId??null),[kind,setKind]=useState<DeleteKind>("sensor"),[metric,setMetric]=useState<string|null>(fleet.dataSelection?.sensorId??null),[selectMode,setSelectMode]=useState(false),[lightbox,setLightbox]=useState<number|null>(null),selection=useSelection();
 useEffect(()=>{if(nodeId&&fleet.nodes.some(n=>n.node_id===nodeId))return;setNodeId(fleet.dataSelection?.nodeId&&fleet.nodes.some(n=>n.node_id===fleet.dataSelection?.nodeId)?fleet.dataSelection.nodeId:fleet.nodes[0]?.node_id??null);},[fleet.nodes,nodeId,fleet.dataSelection]);
 const state=useBeaconDetail(nodeId,{intervalMs:15000,paused:selectMode||Boolean(nodeId&&fleet.pendingDeletes.hasPending(nodeId))}),detail=state.detail,node=fleet.nodes.find(n=>n.node_id===nodeId);
 useEffect(()=>{if(!detail)return;if(!metric||!detail.sensors.some(s=>s.device.sensor_id===metric))setMetric(detail.sensors[0]?.device.sensor_id??null);},[detail,metric]);
 const sensors=detail?.sensors??[],images=detail?.images??[],checkins=detail?.checkins??[],commands=detail?.commands??[],current=sensors.find(s=>s.device.sensor_id===metric)??sensors[0];
 const csv=()=>{if(kind==="sensor"&&current)downloadCsv(`${nodeId}-sensor.csv`,toCsv([{key:"recorded_at",label:"수신 시각"},{key:"value",label:"값"},{key:"unit",label:"단위"},{key:"quality",label:"품질"}],current.readings));if(kind==="checkin")downloadCsv(`${nodeId}-checkins.csv`,toCsv([{key:"checkin_id",label:"ID"},{key:"received_at",label:"수신 시각"},{key:"boot",label:"부팅"},{key:"vbat_mv",label:"전압"},{key:"rssi",label:"RSSI"},{key:"wifi_ms",label:"접속 ms"},{key:"fast",label:"빠른 연결"},{key:"prev_awake_ms",label:"활성 ms"},{key:"prev_result",label:"직전 결과"},{key:"next_given",label:"다음 주기"}],checkins));if(kind==="command")downloadCsv(`${nodeId}-commands.csv`,toCsv([{key:"command_id",label:"ID"},{key:"command_type",label:"종류"},{key:"state",label:"상태"},{key:"created_at",label:"요청"},{key:"done_at",label:"완료"},{key:"reason",label:"사유"}],commands));};
 return <div className="bx-root"><div className="bx-explorer"><SourceRail nodes={fleet.nodes} selected={nodeId} onSelect={id=>{setNodeId(id);setMetric(null);selection.clear();}}/><main className="bx-ex-main"><div className="bx-ex-head"><div className="bx-breadcrumb">{fleet.farm?.name??"농장"} › beacons › {node?.label??"장치 선택"}</div><KindSegment kind={kind} counts={{sensor:sensors.reduce((a,s)=>a+s.reading_count,0),image:detail?.image_count??0,checkin:detail?.checkin_count??0,command:commands.length}} onChange={v=>{setKind(v);selection.clear();}}/><div className="bx-ex-actions"><span>{kind==="image"?"SSD · raw/beacons/":"SQLite · "+({sensor:"sensor_readings",checkin:"beacon_node_checkins",command:"beacon_commands"} as Record<string,string>)[kind]}</span>{kind!=="image"&&<button type="button" className="bx-btn bx-btn--secondary" onClick={csv}>CSV</button>}</div></div><div className="bx-ex-body">{!nodeId?<div className="bx-empty">장치를 선택하세요.</div>:state.error?<div className="bx-empty">{state.error}</div>:!detail?<div className="bx-empty">기록을 불러오는 중입니다.</div>:kind==="sensor"?<SensorView sensors={sensors} metricId={metric} onMetric={id=>{setMetric(id);selection.clear();}} selectMode={selectMode} selection={selection}/>:kind==="image"?<ImageGallery images={images} total={detail.image_count} selectMode={selectMode} selection={selection} onOpen={setLightbox}/>:kind==="checkin"?<CheckinTable items={checkins} selectMode={selectMode} selection={selection}/>:<CommandTable items={commands} selectMode={selectMode} selection={selection}/>}</div></main></div>{lightbox!==null&&<Lightbox images={images} index={lightbox} onIndex={setLightbox} onClose={()=>setLightbox(null)} onDelete={()=>{setLightbox(null);setSelectMode(true);}}/>}</div>;
}
