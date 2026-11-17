#!/usr/bin/env python3
"""Independent database-based AC2–AC4 verifier for the simulator run."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def verify(db_path: Path, input_path: Path, output_path: Path) -> dict:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    command_ids = raw.get("scenario", {}).get("command_ids", [])
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    if command_ids:
        marks = ",".join("?" for _ in command_ids)
        commands = db.execute(
            f"SELECT id,node_id,state,reason,done_at,expires_at FROM commands WHERE id IN ({marks})",
            command_ids,
        ).fetchall()
    else:
        commands = []
    processed = [
        row for row in commands
        if row["state"] in ("done", "failed")
        and row["reason"] != "no_result"
        and row["done_at"] is not None
        and row["done_at"] <= row["expires_at"]
    ]
    dispatched_outside = int(db.execute(
        "SELECT COUNT(*) FROM commands c JOIN nodes n ON n.id=c.node_id "
        "WHERE n.state IN ('DISCOVERED','DETACHED') AND c.state IN ('dispatched','done')"
    ).fetchone()[0])
    duplicate_readings = int(db.execute(
        "SELECT COUNT(*) FROM (SELECT cmd_id FROM readings GROUP BY cmd_id HAVING COUNT(*)>1)"
    ).fetchone()[0])
    duplicate_images = int(db.execute(
        "SELECT COUNT(*) FROM (SELECT cmd_id FROM images GROUP BY cmd_id HAVING COUNT(*)>1)"
    ).fetchone()[0])
    db.close()

    ratio = len(processed) / len(command_ids) if command_ids else None
    rejected = int(raw.get("protocol", {}).get("nonattached_command_rejections_http_409", 0))
    next_records = raw.get("protocol", {}).get("next_records", [])
    all_next_valid = bool(next_records) and all(
        bool(item.get("within_policy_jitter")) for item in next_records
    )
    raw["database"] = {
        "commands_created": len(command_ids),
        "commands_found": len(commands),
        "commands_processed_before_expiry": len(processed),
        "command_processing_ratio": round(ratio, 4) if ratio is not None else None,
        "nonattached_dispatched_commands": dispatched_outside,
        "duplicate_result_rows": duplicate_readings + duplicate_images,
    }
    raw["acceptance"] = {
        "AC2_command_completion_ge_99_percent": (
            ratio is not None and ratio >= 0.99 and duplicate_readings + duplicate_images == 0
        ),
        "AC3_no_discovered_or_detached_dispatch": dispatched_outside == 0 and rejected == 2,
        "AC4_all_next_within_policy_jitter": all_next_valid,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return raw


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", default="results/sim_report.json", type=Path)
    args = parser.parse_args(argv)
    report = verify(args.db, args.input, args.output)
    print(json.dumps({"acceptance": report["acceptance"], "database": report["database"]}, indent=2))
    return 0 if all(report["acceptance"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
