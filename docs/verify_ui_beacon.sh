#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p docs/_logs
log="docs/_logs/verify_$(date +%Y%m%d-%H%M).log"
exec > >(tee "$log") 2>&1
pass=0; fail=0
run() { name="$1"; shift; if "$@"; then printf 'PASS %s\n' "$name"; pass=$((pass+1)); else code=$?; printf 'FAIL %s (exit %s)\n' "$name" "$code"; fail=$((fail+1)); fi; }
if ! timeout 30 docker ps >/dev/null 2>&1; then
  printf 'FAIL Docker 접근: sudo usermod -aG docker nano 실행 후 다시 로그인하세요.\n'
  exit 1
fi
printf 'PASS Docker 접근\n'; pass=$((pass+1))
run '브랜치' bash -c 'test "$(git branch --show-current)" = ui/beacon-v1.1'
run '작업 트리' bash -c 'test -z "$(git status --short)"'
run 'API 이미지 빌드' timeout 900 docker compose --env-file .env -f infra/compose.yaml build api
run 'API 단위 테스트' timeout 600 docker compose --env-file .env -f infra/compose.yaml run --rm --no-deps -v "$PWD/services/api/tests:/app/tests:ro" api python -m unittest discover -s tests -v
run '웹 이미지 빌드' timeout 1200 docker compose --env-file .env -f infra/compose.yaml build web
run '배포 전 DB 행 수' timeout 60 docker compose --env-file .env -f infra/compose.yaml exec -T api python -c 'import sqlite3; db=sqlite3.connect("file:/workspace/storage/state/mirgam.db?mode=ro",uri=True); tables=("sensor_readings","camera_assets","beacon_node_checkins","beacon_commands"); print({t:db.execute("SELECT count(*) FROM "+t).fetchone()[0] for t in tables})'
run '서비스 시작' timeout 120 docker compose --env-file .env -f infra/compose.yaml up -d api web
run 'API 준비' timeout 65 bash -c 'for i in $(seq 1 60); do if curl -fsS --max-time 2 http://127.0.0.1:8100/health >/dev/null; then exit 0; fi; sleep 1; done; exit 1'
run '웹 HTTP 200' timeout 15 bash -c 'test "$(curl -sS -o /dev/null -w "%{http_code}" -I http://127.0.0.1:3100/)" = 200'
run '감사 테이블' timeout 60 docker compose --env-file .env -f infra/compose.yaml exec -T api python -c 'import sqlite3;db=sqlite3.connect("file:/workspace/storage/state/mirgam.db?mode=ro",uri=True);assert db.execute("SELECT 1 FROM sqlite_master WHERE type=? AND name=?",("table","beacon_data_deletions")).fetchone();print("beacon_data_deletions 존재")'
printf '\n결과: PASS %s / FAIL %s\n' "$pass" "$fail"
printf '이제 브라우저에서 docs/verify_ui_beacon.md를 진행하세요: http://<Jetson IP>:3100\n'
test "$fail" -eq 0
