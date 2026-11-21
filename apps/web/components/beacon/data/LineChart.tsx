"use client";
import { useEffect, useRef, useState } from "react";
import { clock, dateTime } from "../format";
export function LineChart({ points, unit, height = 200 }: { points: {t:number;v:number;flag?:boolean}[]; unit:string; height?:number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [active, setActive] = useState<number | null>(null);
  useEffect(() => { if (!ref.current) return; const observer = new ResizeObserver(([entry]) => setWidth(Math.max(180, entry.contentRect.width))); observer.observe(ref.current); return () => observer.disconnect(); }, []);
  if (!points.length) return <div className="bx-empty">측정 기록이 없습니다.</div>;
  const left = 36, right = 8, top = 10, bottom = 24;
  const min = Math.min(...points.map(p => p.v)), max = Math.max(...points.map(p => p.v));
  const raw = Math.max((max-min)/4, Math.abs(max)*0.01, 0.01), magnitude = 10**Math.floor(Math.log10(raw));
  const step = ([1,2,5,10].find(n => n*magnitude >= raw) ?? 10)*magnitude;
  const lower = Math.floor(min/step)*step, upper = Math.max(lower+step, Math.ceil(max/step)*step);
  const x = (i:number) => left+i*(width-left-right)/Math.max(points.length-1,1);
  const y = (v:number) => top+(upper-v)*(height-top-bottom)/(upper-lower);
  const path = points.map((p,i) => `${x(i)},${y(p.v)}`).join(" ");
  const ticks = Array.from({length:Math.min(8,Math.round((upper-lower)/step)+1)},(_,i)=>lower+i*step);
  return <div ref={ref} className="bx-chart" tabIndex={0} aria-label="센서 추이. 좌우 화살표로 측정값 이동" onKeyDown={e=>{if(["ArrowRight","ArrowLeft","Home","End"].includes(e.key)){e.preventDefault();setActive(i=>e.key==="Home"?0:e.key==="End"?points.length-1:Math.max(0,Math.min(points.length-1,(i??0)+(e.key==="ArrowRight"?1:-1))));}}}>
    <svg viewBox={`0 0 ${width} ${height}`} onMouseLeave={()=>setActive(null)} onMouseMove={e=>{const r=e.currentTarget.getBoundingClientRect();setActive(Math.max(0,Math.min(points.length-1,Math.round(((e.clientX-r.left)-left)/(width-left-right)*Math.max(points.length-1,1)))));}}>
      <defs><linearGradient id="bx-chart-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#d9782f" stopOpacity=".22"/><stop offset="100%" stopColor="#d9782f" stopOpacity="0"/></linearGradient></defs>
      {ticks.map(v=><g key={v}><line x1={left} x2={width-right} y1={y(v)} y2={y(v)} stroke="#e0e9dd"/><text x="0" y={y(v)+4}>{Number(v.toPrecision(4))}</text></g>)}
      <polygon fill="url(#bx-chart-fill)" points={`${x(0)},${height-bottom} ${path} ${x(points.length-1)},${height-bottom}`}/><polyline fill="none" stroke="#d9782f" strokeWidth="2" points={path}/>
      {points.map((p,i)=>p.flag?<circle key={i} cx={x(i)} cy={y(p.v)} r="3" fill="#c16622"/>:null)}
      {points.map((p,i)=>i % (width<480?32:16)===0?<text key={i} x={x(i)} y={height-4}>{clock(p.t/1000)}</text>:null)}
      {active!==null&&<><line x1={x(active)} x2={x(active)} y1={top} y2={height-bottom} stroke="#65826b" strokeDasharray="4 4"/><circle cx={x(active)} cy={y(points[active].v)} r="4" fill="#fff" stroke="#295b3b" strokeWidth="2"/></>}
    </svg>{active!==null&&<div className="bx-chart-tooltip" style={{left:`${Math.max(5,Math.min(72,(x(active)/width)*100))}%`,top:`${Math.max(3,Math.min(70,(y(points[active].v)/height)*100))}%`}}>{points[active].v} {unit} · {dateTime(points[active].t/1000)}</div>}<div className="sr-only" aria-live="polite">{active!==null?`${points[active].v} ${unit} · ${dateTime(points[active].t/1000)}`:""}</div>
  </div>;
}
