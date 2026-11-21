"use client";
import { useState } from "react";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";

export function ConfirmDialog({ open, title, body, confirmLabel, requireText, onClose, onConfirm }: {
  open: boolean; title: string; body: string; confirmLabel: string; requireText?: string;
  onClose(): void; onConfirm(): Promise<void>;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const valid = !requireText || typed === requireText;
  async function confirm() {
    if (!valid || busy) return;
    setBusy(true); setError("");
    try { await onConfirm(); onClose(); setTyped(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "요청을 완료하지 못했습니다."); }
    finally { setBusy(false); }
  }
  return <Dialog open={open} onClose={onClose} labelledBy="bx-confirm-title">
    <div className="bx-dialog-head"><div><h2 id="bx-confirm-title">{title}</h2><p>{body}</p></div><button type="button" className="bx-btn bx-btn--icon" data-dialog-close aria-label="닫기" onClick={onClose}>×</button></div>
    <div className="bx-dialog-body">
      {requireText ? <label className="bx-field"><span className="bx-lab">계속하려면 장치 이름을 입력하세요: <b>{requireText}</b></span><input autoFocus type="text" value={typed} onChange={(event) => setTyped(event.target.value)} /></label> : null}
      {error ? <p role="alert" className="bx-form-error">{error}</p> : null}
    </div>
    <div className="bx-dialog-foot"><Button variant="secondary" onClick={onClose} disabled={busy}>취소</Button><Button variant="danger" onClick={() => void confirm()} disabled={!valid || busy}>{busy ? "처리 중…" : confirmLabel}</Button></div>
  </Dialog>;
}
