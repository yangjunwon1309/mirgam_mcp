# Codex 작업 지시: Beacon UI 개편 D1~D8 (Docker 없는 실행 경로)

너는 `~/mirgam_mcp`에서 `docs/SPEC_DEV_BEACON_UI.md`(이하 "개발 명세")를 끝까지 구현한다. 이 지시문은 개발 명세의 **실행 환경과 역할 분담만** 바꾼다. 구현 내용·파일 구조·API 계약·수락 기준은 개발 명세가 그대로 기준이다. 디자인 판단은 `docs/SPEC_UI_BEACON.md`, 시각 기준은 `docs/design/beacon-dashboard-sample.html`을 따른다.

목표: 사람에게 질문하지 않고 D1~D8을 모두 끝내고, 사람이 마지막에 돌릴 검수 스크립트와 체크리스트를 남긴다. 사람이 하는 일은 **검수 CLI 실행과 브라우저 확인뿐**이다.

---

## 1. 현재 상태 (확인된 사실)

- 브랜치 `ui/beacon-v1.1`, 커밋 `559c1ef beacon-ui: D0 add specs and design sample`. D0의 문서 게이트는 통과했다.
- 작업 전 미추적 빌드 캐시는 `/tmp`로 옮겨 두었다. 되돌리지 않는다.
- `nano` 계정은 Docker 소켓(`/var/run/docker.sock`)에 접근할 수 없다. **`docker` 명령은 이번 작업에서 한 번도 실행하지 않는다.**
- 호스트 Python은 3.10이고, API 코드는 3.12 기준이다.

## 2. 실행 환경 준비 (sudo 없이, 홈 디렉터리에만 설치)

아래 명령은 이미 설치되어 있으면 건너뛰도록 확인부터 한다. 결과(버전, 종료 코드)는 `docs/_logs/env.log`에 남긴다.

```bash
mkdir -p ~/mirgam_mcp/docs/_logs
# Python 3.12 + API 의존성
command -v ~/.local/bin/uv >/dev/null || (curl -LsSf https://astral.sh/uv/install.sh | sh)
~/.local/bin/uv python install 3.12
test -x ~/.venvs/mirgam-api/bin/python || ~/.local/bin/uv venv ~/.venvs/mirgam-api --python 3.12
cd ~/mirgam_mcp/services/api && timeout 1200 ~/.local/bin/uv pip install --python ~/.venvs/mirgam-api/bin/python -r pyproject.toml
~/.venvs/mirgam-api/bin/python -c "import sys,sqlite3,pydantic,fastapi;print(sys.version, sqlite3.sqlite_version, pydantic.VERSION)"

# Node 22 (arm64)
test -x ~/.local/node/bin/node || ( cd /tmp && curl -fsSLO https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-arm64.tar.xz \
  && mkdir -p ~/.local/node && tar -xJf node-v22.11.0-linux-arm64.tar.xz -C ~/.local/node --strip-components=1 )
export PATH="$HOME/.local/node/bin:$PATH"; node --version; npm --version
```

- `-r pyproject.toml` 설치가 일부 패키지(예: `pyproj`, `shapely`, `sqlitecloud`) 때문에 실패하면, 테스트에 필요한 최소 집합만 설치하고 계속한다: `pydantic>=2`, `pydantic-settings`, `fastapi`, `httpx`. 무엇을 뺐는지 `env.log`와 보고서에 적는다.
- 다운로드 자체가 막히면(네트워크 오류) 그때만 멈추고 보고한다.
- 이후 모든 셸에서 `export PATH="$HOME/.local/node/bin:$PATH"`와 `export NEXT_TELEMETRY_DISABLED=1`을 먼저 실행한다.

## 3. 개발 명세 명령의 대체표

| 개발 명세의 명령 | 이번 작업에서 쓰는 명령 |
|---|---|
| `docker compose ... run --rm ... api python -m unittest discover -s tests -v` | `cd services/api && timeout 600 ~/.venvs/mirgam-api/bin/python -m unittest discover -s tests -v 2>&1 \| tee ../../docs/_logs/api_tests.log` |
| `docker compose ... build api` | 실행하지 않음. 대신 `cd services/api && ~/.venvs/mirgam-api/bin/python -c "import app.schemas, app.services.beacon_store, app.services.sqlite_store"`로 import 검사. `app.main` import는 설정·외부 클라이언트 초기화가 걸려 있으므로 시도하되 실패하면 사유만 기록 |
| `docker run ... node:22-alpine ... npm run lint` | `cd apps/web && npm install --no-package-lock --no-audit --no-fund && timeout 600 npm run lint` |
| `npm run build` / `docker compose build web` | `cd apps/web && timeout 1200 npm run build` (호스트) |
| `docker compose exec -T api python -c "...mirgam.db..."` | `~/.venvs/mirgam-api/bin/python`으로 `~/mirgam_mcp/storage/state/mirgam.db`를 `?mode=ro` URI로 직접 연다. **쓰기 연결 금지** |
| `docker compose ps` 등 상태 확인 | 실행하지 않음 |

## 4. 역할 분담

**Codex가 끝내는 것 (전부)**
- 개발 명세 D1~D8의 모든 코드 작성, 수정, 삭제(4~9절, 12절, D7 정리).
- API 단위 테스트(4.6, 14개 이상) 작성과 통과.
- `npm run lint`, `npm run build` 통과.
- 자동으로 판정할 수 있는 수락 기준: AC1, AC2, AC3, AC4(grep 부분), AC8, AC10, AC13, AC15(테스트 부분). 판정 명령과 출력은 보고서에 남긴다.
- 검수 스크립트 `docs/verify_ui_beacon.sh`와 체크리스트 `docs/verify_ui_beacon.md` 작성(6절).
- 보고서 `docs/report_ui_beacon.md` 작성(개발 명세 16절 형식). 사람이 확인할 항목은 "사람 확인 대기"로 표시한다.
- 단계마다 커밋.

**Codex가 하지 않는 것 (사람이 검수 때 함)**
- 모든 `docker`·`docker compose` 명령.
- 브라우저 확인(R·B·D·X 시나리오, AC4 네트워크 탭, AC5~AC7, AC9, AC11, AC12, AC14, AC16, AC17).
- 운영 DB에 대한 실제 삭제. Codex는 운영 DB를 읽기 전용으로만 연다. 삭제 API의 `dry_run` 호출도 하지 않는다(API 서버를 띄울 수 없으므로).
- `git push`.

## 5. 진행 규칙

1. **끝까지 진행한다.** 아래 "멈춤 조건"이 아니면 사람에게 묻지 않는다. 모호한 점은 `SPEC_UI_BEACON.md`와 샘플 HTML에 더 가까운 쪽을 택하고, 보고서 7절 "구현 중 결정"에 `결정 / 근거 / 대안` 한 줄씩 남긴다.
2. **멈춤 조건(이때만 멈추고 개발 명세 15절 형식으로 보고):**
   - 2절 설치가 네트워크 문제로 불가능할 때.
   - 개발 명세의 계약(API 경로, 요청·응답 필드, 파일 경로·이름)을 바꾸지 않으면 구현이 불가능할 때.
   - 같은 실패가 소스 수정 3회 후에도 계속될 때.
   - 기존 기능(농장 지도, 채팅, 제주 날씨)을 깨뜨리지 않고는 진행할 수 없을 때.
3. **단계와 커밋:** D1 → D2 → D3 → D4 → D5 → D6 → D7 → D8 순서. 단계 게이트(lint, 테스트)를 통과한 뒤 `git add -A && git commit -m "beacon-ui: D<n> <요약>"`. 사람 확인이 필요한 게이트(R1~R4, B·D·X 시나리오)는 기다리지 않고 체크리스트로 넘긴 뒤 다음 단계로 간다.
4. **커밋하면 안 되는 것:** `node_modules/`, `.next/`, `package-lock.json`, `.venv`·`~/.venvs`, `__pycache__`, `docs/_logs/` 안의 대용량 빌드 로그(1 MB 넘으면 마지막 300줄만 남긴다). 커밋 전에 `git status --short`로 확인하고, 예상 밖 파일이 있으면 커밋에서 빼고 보고서에 적는다. `package.json`·`pyproject.toml`은 diff가 0이어야 한다.
5. **금지:** `sudo`, `apt`, `docker`, 시스템 설정 변경, `services/beacon/`·펌웨어·`infra/compose.yaml` 수정, `.env`·`storage/` 실데이터 출력·수정, `git reset --hard`, `git clean`, `git push`, 새 의존성 추가. 설치는 `~/.local`, `~/.venvs`, `/tmp`에만 한다.
6. 모든 외부 명령에 `timeout`을 건다. 개발 서버(`next dev`, `uvicorn`)를 백그라운드로 남겨 두지 않는다.
7. 성공을 추측으로 쓰지 않는다. 판정마다 명령, 종료 코드, 출력 근거를 남긴다. 추론은 "추정"이라고 표시한다.

## 6. 사람용 검수 산출물

### 6.1 `docs/verify_ui_beacon.sh` (사람이 실행)

`bash docs/verify_ui_beacon.sh`로 처음부터 끝까지 돌아가고, 각 단계의 결과를 `docs/_logs/verify_<YYYYmmdd-HHMM>.log`에 남기는 스크립트. `set -u`, 단계마다 `PASS/FAIL` 한 줄 출력, 실패해도 다음 단계로 진행하고 마지막에 요약표를 출력한다. 포함할 단계:

1. Docker 접근 확인: `docker ps` 성공 여부. 실패하면 `sudo usermod -aG docker nano` 후 재로그인 안내를 출력하고 종료.
2. 브랜치·커밋 확인: `git rev-parse --abbrev-ref HEAD`가 `ui/beacon-v1.1`, `git status --short`가 비었는지.
3. API 이미지 빌드: `timeout 900 docker compose -f infra/compose.yaml build api`.
4. 컨테이너 안 API 테스트(개발 명세 4.6의 원래 명령, tests 폴더 읽기 전용 마운트).
5. 웹 이미지 빌드: `timeout 1200 docker compose -f infra/compose.yaml build web`.
6. 배포 전 DB 행 수 기록(읽기 전용): `sensor_readings`, `camera_assets`, `beacon_node_checkins`, `beacon_commands`.
7. 재기동: `docker compose -f infra/compose.yaml up -d api web` 후 최대 60 s 동안 `curl -fsS http://127.0.0.1:8100/health` 성공 대기, `curl -fsSI http://127.0.0.1:3100/`가 200인지.
8. 감사 테이블 생성 확인(읽기 전용): `beacon_data_deletions` 존재.
9. 마지막에 "이제 브라우저에서 `docs/verify_ui_beacon.md`를 진행하세요"와 접속 주소(`http://<Jetson IP>:3100`) 출력.

스크립트는 `sudo`를 쓰지 않으며, 삭제·초기화 명령(`down -v`, `rm -rf storage` 등)을 포함하지 않는다. Codex는 이 스크립트를 **작성만 하고 실행하지 않는다**. 단, `bash -n docs/verify_ui_beacon.sh`(문법 검사)와 `shellcheck`가 있으면 그것까지는 실행한다.

### 6.2 `docs/verify_ui_beacon.md` (사람이 체크)

- 개발 명세 13절의 R1~R4, B1~B10, D1~D6, X1~X9와 14절에서 사람이 확인할 AC를 체크박스 목록으로. 항목마다 **무엇을 누르고, 무엇이 보여야 통과인지** 한두 줄로 쓴다.
- 삭제 시나리오(X1, X2, X4, X6) 앞뒤에 실행할 읽기 전용 행 수 확인 명령을 그대로 붙여 넣을 수 있게 적는다.
- 스크린샷이 필요한 항목(AC11, AC17)은 파일 이름 규칙을 정한다: `docs/_shots/<ID>_<폭>.png`.
- 맨 아래 "결과 기록" 표(ID · 통과/실패 · 메모).

## 7. 완료 조건 (Codex 기준)

다음을 모두 만족하면 작업을 끝내고 최종 보고한다.
- D1~D8 커밋이 브랜치에 있고 작업 트리가 깨끗하다.
- API 테스트 전부 통과, `npm run lint`·`npm run build` 종료 코드 0.
- Codex 판정 AC(4절 목록)가 모두 PASS이거나, FAIL이면 사유와 해결 시도가 보고서에 있다.
- `docs/verify_ui_beacon.sh`(문법 검사 통과), `docs/verify_ui_beacon.md`, `docs/report_ui_beacon.md`가 있다.

최종 응답은 다음만 짧게: 커밋 목록(해시 + 메시지), Codex 판정 AC 결과표, 구현 중 결정 목록, 사람이 실행할 명령 두 줄(`cd ~/mirgam_mcp && bash docs/verify_ui_beacon.sh`, 그다음 `docs/verify_ui_beacon.md` 진행).
