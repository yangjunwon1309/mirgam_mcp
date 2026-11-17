#!/usr/bin/env bash
set -u
ROOT=/home/nano/beacon
cd "$ROOT" || exit 1
timeout 5 mkdir -p "$ROOT/results" || exit 1
LOG="$ROOT/results/n1.log"
timeout 180 python3 -m unittest discover -s server/tests -v >"$LOG" 2>&1
rc=$?
timeout 5 tail -n 30 "$LOG"
printf 'N1 exit=%s\n' "$rc"
exit "$rc"

