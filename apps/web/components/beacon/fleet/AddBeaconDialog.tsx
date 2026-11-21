"use client";
import { useEffect, useMemo, useState } from "react";
import { useBeaconFleet } from "../BeaconFleetProvider";
import { useToasts } from "../ui/Toasts";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { Checkbox } from "../ui/Checkbox";
import { intervalLabel, relTime } from "../format";
import { daysLabel, estimateDays } from "../energy";

const presets = [60, 300, 900, 3600];
export function AddBeaconDialog() {
  const fleet = useBeaconFleet();
  const toasts = useToasts();
  const draft = fleet.addDraft;
  const [custom, setCustom] = useState(false);
  const [customText, setCustomText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const available = useMemo(() => draft?.mode === "edit" ? [] : fleet.discoverable, [draft?.mode, fleet.discoverable]);
  useEffect(() => {
    if (draft) {
      const isPreset = presets.includes(draft.intervalS);
      setCustom(!isPreset); setCustomText(isPreset ? "" : String(draft.intervalS)); setError("");
    }
  }, [draft?.mode, draft?.nodeId]);
  if (!draft) return <Dialog open={false} onClose={fleet.closeAdd} labelledBy="bx-add-title"><span /></Dialog>;
  const chosen = draft.nodeId ? fleet.allNodes.find((node) => node.node_id === draft.nodeId) : null;
  const interval = custom ? Number(customText) : draft.intervalS;
  const intervalValid = Number.isInteger(interval) && interval >= 60 && interval <= 14400;
  const nameValid = draft.label.trim().length > 0 && draft.label.trim().length <= 64;
  const dataValid = draft.sensor || draft.image;
  const locationValid = typeof draft.location.latitude === "number" && Number.isFinite(draft.location.latitude) && typeof draft.location.longitude === "number" && Number.isFinite(draft.location.longitude);
  async function save() {
    if (!draft) return;
    if (!draft.nodeId || !fleet.farm || !nameValid || !intervalValid || !dataValid || !locationValid) return;
    setSaving(true); setError("");
    const location = { ...draft.location, site: draft.location.site ?? fleet.farm.name };
    try {
      await fleet.api.configure(draft.nodeId, { farm_id: fleet.farmId, metadata: { ...draft.metadata, label: draft.label.trim(), location }, interval_s: interval, requested_data: [draft.sensor ? "sensor" : null, draft.image ? "image" : null].filter((x): x is "sensor" | "image" => x !== null), attach: true });
      const id = draft.nodeId; fleet.closeAdd(); fleet.refreshNodes(); fleet.markHighlight(id);
      toasts.push({ title: draft.mode === "add" ? "장치를 연결했습니다" : "설정을 저장했습니다", body: "다음 체크인 때 장치에 전달됩니다.", tone: "ok" });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "설정을 저장하지 못했습니다."); }
    finally { setSaving(false); }
  }
  const isEdit = draft.mode === "edit";
  const title = isEdit ? "장치 설정 편집" : "Beacon 연결";
  return <Dialog open onClose={fleet.closeAdd} size="md" labelledBy="bx-add-title">
    <div className="bx-dialog-head"><div><h2 id="bx-add-title">{title}</h2><p>{draft.step === 1 ? "최근 체크인한 장치를 선택합니다." : draft.step === 2 ? "표시 이름과 수집 설정을 정합니다." : "농장 지도에서 설치 위치를 지정합니다."}</p></div><button type="button" className="bx-btn bx-btn--icon" data-dialog-close aria-label="닫기" onClick={fleet.closeAdd}>×</button></div>
    {!isEdit ? <div className="bx-stepper" aria-label="진행 단계">{[["장치 선택", 1], ["이름·수집", 2], ["설치 위치", 3]].map(([label, step]) => <span key={step} className={"bx-step" + (draft.step === step ? " bx-on" : Number(step) < draft.step ? " bx-done" : "")}><i>{Number(step) < draft.step ? "✓" : step}</i>{label}</span>)}</div> : null}
    <div className="bx-dialog-body bx-add-body">
      {draft.step === 1 ? <>
        <div className="bx-choice-list" role="radiogroup" aria-label="연결할 Beacon">{available.map((item) => <button type="button" role="radio" aria-checked={draft.nodeId === item.node_id} className="bx-choice" key={item.node_id} onClick={() => fleet.updateDraft({ nodeId: item.node_id, label: item.label && item.label !== item.node_id ? item.label : "" })}><span className="bx-r" /><span><b className="bx-mono">{item.node_id}</b><small>{item.last_ip ?? "IP 정보 없음"} · {item.last_seen === null ? "체크인 기록 없음" : relTime(Math.max(0, Date.now() / 1000 - item.last_seen))}</small></span><span className="bx-badge bx-badge--idle">{item.first_seen !== null && Date.now() / 1000 - item.first_seen < 600 ? "새로 발견" : "발견됨"}</span></button>)}</div>
        {!available.length ? <div className="bx-empty"><strong>선택할 Beacon이 없습니다</strong><p>장치 전원을 켜고 체크인이 들어온 뒤 다시 확인하세요.</p><Button variant="secondary" icon="refresh" onClick={fleet.refreshNodes}>다시 찾기</Button></div> : null}
        <p className="bx-callout bx-info">발견된 장치는 15분마다 체크인합니다.</p>
      </> : null}
      {draft.step === 2 ? <>
        {isEdit ? <p className="bx-selected-node"><code>{draft.nodeId}</code></p> : <p className="bx-selected-node"><code>{chosen?.node_id ?? draft.nodeId}</code> 선택됨</p>}
        <label className="bx-field"><span className="bx-lab">표시 이름</span><input autoFocus type="text" maxLength={64} value={draft.label} onChange={(event) => fleet.updateDraft({ label: event.target.value })} placeholder="예: 북쪽 하우스 1" /></label>
        <div className="bx-field"><span className="bx-lab">체크인 주기</span><div className="bx-presets">{presets.map((sec) => <button type="button" className="bx-preset" aria-pressed={!custom && draft.intervalS === sec} key={sec} onClick={() => { setCustom(false); fleet.updateDraft({ intervalS: sec }); }}><b>{intervalLabel(sec)}</b><small>{daysLabel(estimateDays(sec, draft.image))}</small></button>)}</div>
          <button type="button" className="bx-btn bx-btn--ghost bx-custom-toggle" aria-pressed={custom} onClick={() => { setCustom(true); if (!customText) setCustomText(String(draft.intervalS)); }}>직접 입력</button>
          {custom ? <label className="bx-field"><span className="bx-lab">주기(초, 60~14,400)</span><input type="number" min={60} max={14400} step={1} value={customText} onChange={(event) => { setCustomText(event.target.value); if (Number.isInteger(Number(event.target.value))) fleet.updateDraft({ intervalS: Number(event.target.value) }); }} /></label> : null}
        </div>
        <fieldset className="bx-data-toggles"><legend>수집 데이터</legend><label><Checkbox checked={draft.sensor} onChange={(sensor) => fleet.updateDraft({ sensor })} ariaLabel="센서 데이터 수집" /> 센서</label><label><Checkbox checked={draft.image} onChange={(image) => fleet.updateDraft({ image })} ariaLabel="이미지 수집" /> 이미지</label></fieldset>
        <p className="bx-callout bx-info">이 설정의 예상 배터리 수명 {intervalValid ? daysLabel(estimateDays(interval, draft.image)) : "—"} · 목표 30일 {intervalValid && estimateDays(interval, draft.image) >= 30 ? "충족" : "미달"}</p>
      </> : null}
      {draft.step === 3 ? <>
        <p>{locationValid ? `선택된 위치: ${draft.location.latitude?.toFixed(6)}, ${draft.location.longitude?.toFixed(6)}` : "지도에서 설치 위치를 선택하세요."}</p>
        <Button variant="secondary" icon="pin" disabled={!fleet.hasBoundary || !draft.nodeId} onClick={fleet.beginPlacement}>지도에서 위치 {locationValid ? "변경" : "선택"}</Button>
        {!fleet.hasBoundary ? <><p className="bx-hint">먼저 농장 경계를 등록하세요. 지도 위치 선택은 경계가 있어야 사용할 수 있습니다.</p><Button variant="ghost" onClick={() => fleet.navigate("farm")}>농장 지도로 이동</Button></> : null}
      </> : null}
      {error ? <p role="alert" className="bx-form-error">{error}</p> : null}
    </div>
    <div className="bx-dialog-foot">
      <Button variant="secondary" onClick={() => draft.step > (isEdit ? 2 : 1) ? fleet.updateDraft({ step: (draft.step - 1) as 1 | 2 | 3 }) : fleet.closeAdd()} disabled={saving}>{draft.step === 1 || isEdit && draft.step === 2 ? "취소" : "이전"}</Button>
      {draft.step === 1 ? <Button variant="primary" disabled={!draft.nodeId} onClick={() => fleet.updateDraft({ step: 2 })}>다음</Button> : draft.step === 2 ? <Button variant="primary" disabled={!nameValid || !intervalValid || !dataValid} onClick={() => fleet.updateDraft({ step: 3 })}>다음</Button> : <Button variant="primary" disabled={!nameValid || !intervalValid || !dataValid || !locationValid || saving} onClick={() => void save()}>{saving ? "저장 중…" : isEdit ? "저장" : "연결하고 저장"}</Button>}
    </div>
  </Dialog>;
}
