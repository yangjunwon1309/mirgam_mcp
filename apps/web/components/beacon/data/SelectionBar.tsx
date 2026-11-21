"use client";
import { Button } from "../ui/Button";
export function SelectionBar({count,onClear,onDone,onDelete}:{count:number;onClear():void;onDone():void;onDelete():void}) {return <div className="bx-bulkbar" role="region" aria-label="선택 작업"><strong aria-live="polite">{count}개 선택됨</strong><Button variant="ghost" disabled={!count} onClick={onClear}>선택 해제</Button><Button variant="secondary" onClick={onDone}>완료</Button><Button variant="danger" disabled={!count} onClick={onDelete}>삭제</Button></div>}
