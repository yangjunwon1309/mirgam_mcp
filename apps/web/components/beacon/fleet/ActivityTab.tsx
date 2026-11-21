"use client";
import type { CommandEntry } from "../types";
import { commandLabel, commandStateLabel, dateTime, failReason } from "../format";
export function ActivityTab({ commands }: { commands: CommandEntry[] }) {
  const ordered = [...commands].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
  if (!ordered.length) return <div className="bx-empty"><strong>아직 요청한 작업이 없습니다</strong><p>센서 읽기나 촬영을 요청하면 여기에 진행 상황이 표시됩니다.</p></div>;
  return <div className="bx-timeline">{ordered.map((command) => {
    const failed = command.state === "failed" || command.state === "expired";
    const done = command.state === "done";
    const elapsed = command.done_at !== null && command.created_at !== null ? Math.max(0, command.done_at - command.created_at) : null;
    return <article className="bx-tl-item" key={command.command_id}><span className={"bx-tl-dot " + (done ? "ok" : failed ? "fail" : "wait")}>{done ? "✓" : failed ? "!" : "·"}</span>
      <div><strong>{commandLabel(command.command_type)} #{command.command_id}</strong><small>{commandStateLabel(command.state)}{command.reason ? " · " + failReason(command.reason) : ""}</small>
        {command.state === "queued" || command.state === "dispatched" ? <div className="bx-steps"><span className="on" /><span className={command.state === "dispatched" ? "on" : ""} /><span /></div> : null}
        {command.result ? <details><summary>결과 JSON</summary><pre>{JSON.stringify(command.result, null, 2)}</pre></details> : null}
      </div><div className="r">{command.created_at === null ? "시각 미상" : dateTime(command.created_at)}<small>{elapsed === null ? "" : elapsed < 60 ? elapsed.toFixed(1) + "초" : Math.floor(elapsed / 60) + "분"}</small></div>
    </article>;
  })}</div>;
}
