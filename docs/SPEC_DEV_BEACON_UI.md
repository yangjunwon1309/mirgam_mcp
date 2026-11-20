# Beacon 관리 · 데이터 서버 개발 명세서 (SPEC_DEV_BEACON_UI v1)

작업자: Codex(Jetson 셸, `~/mirgam_mcp`) + 사람(파일 배치·브라우저 확인·push). 대상: `yangjunwon1309/mirgam_mcp` `main`(기준 커밋 `9931d45`).

입력 문서와 우선순위:
1. **이 문서** — 무엇을, 어느 파일에, 어떤 계약으로 만드는가.
2. `docs/SPEC_UI_BEACON.md` v1.1 — 디자인 규칙(색·문구·상태 매핑·화면 구성). 이 문서가 절 번호로 참조한다(예: UI-4.4).
3. `docs/design/beacon-dashboard-sample.html` — 시각 기준. 클래스 이름, 간격, 색 값, 아이콘 path의 출처.

세 문서가 충돌하면 위의 순서를 따른다. 명세와 현실이 어긋나면 추측해서 진행하지 말고 15절대로 멈추고 보고한다.

---

## 0. 목적과 완료 정의

우측 대시보드의 **Beacon** 탭과 **데이터 서버** 탭을 v1.1 디자인으로 다시 만든다.

완료 정의:
- Beacon 탭: 요약 배너 + 장치 카드 + 카드 클릭 시 상세 팝업 + 장치 추가/설정 편집 3단계 다이얼로그.
- 데이터 서버 탭: 소스 레일 + 종류 세그먼트(센서·이미지·체크인·작업) + 차트·갤러리·표 + 선택 삭제·기간 삭제·실행 취소.
- 농장 선택은 대시보드 전체에서 하나(Beacon·데이터 서버·농장 지도가 공유).
- 백엔드: 삭제 API 1개, 목록 응답에 센서 최신값, 상세 응답에 행 ID와 건수.
- 기존 `BeaconDashboard.tsx`, `DataServerDashboard.tsx`, `BeaconDataExplorer.tsx`와 그 CSS 규칙 삭제.
- 14절 수락 기준 전부 통과, `docs/report_ui_beacon.md` 작성.

범위 밖: 채팅 패널, 농장 현황 탭의 센서·카메라 카드 디자인, 제주 날씨, 농장 지도 자체의 그리기 기능, 로그인, 펌웨어, Beacon 서버(`services/beacon`) 코드, 다크 모드.

---

## 1. 전제 (확인 상태 표시)

| 항목 | 값 | 상태 |
|---|---|---|
| 작업 폴더 | `~/mirgam_mcp` (Jetson, 사용자 `nano`) | 사용자 진술, D0에서 확인 |
| 웹 | Next.js 15 App Router, React 19, TypeScript `strict`, 일반 전역 CSS(`globals.css`, `dashboard.css`), 의존성 `next`·`react`·`react-dom`·`react-markdown`·`remark-gfm`뿐 | 확인(`apps/web/package.json`) |
| 웹 검사 | `npm run lint` = `tsc --noEmit`, `npm run build`. 프론트 테스트 러너 없음 | 확인 |
| API | FastAPI, Python ≥ 3.12, 컨테이너 `python:3.12-slim`, 이미지에는 `app/`만 복사됨. `services/api/tests/` 없음 | 확인 |
| Jetson 호스트 Python | 3.10 (API 코드는 3.12 기준) → API 테스트는 **컨테이너에서** 실행 | SPEC_NET 1절 기준, D0에서 확인 |
| DB | SQLite `storage/state/mirgam.db`(컨테이너 `/workspace/storage/state/mirgam.db`), `PRAGMA foreign_keys=ON` | 확인 |
| 이미지 | API는 Beacon 원본 `/beacon-data`를 **읽기 전용** 마운트, 사본을 `storage/raw/beacons/<node>/<cmd>.jpg`에 저장하고 `camera_assets.file_path`에 상대 경로 기록. `asset_id = beacon-command-<cmd>`, `camera_id = beacon:<node>` | 확인(`beacon.py`, `beacon_store.py`, `infra/compose.yaml`) |
| 센서 행 | 측정 항목마다 `sensor_devices` 1행: `sensor_id = beacon:<node>:<type>:<addr>:<field>`, `sensor_type`은 `temperature`·`humidity` 등, `metadata_json.beacon_node_id = <node>` | 확인 |
| 웹 프록시 | `app/api/backend/[...path]/route.ts`가 GET·DELETE의 본문을 버림 → 본문 있는 삭제는 POST | 확인 |
| 목록 API | `GET /dashboard/beacons`는 `farm_id` 쿼리를 **무시**하고 계정의 모든 노드를 돌려준다 → 농장 필터는 프론트에서 | 확인 |
| 체크인 스냅샷 | 목록 조회마다 `record_checkin_snapshot`이 노드의 현재 `last_seen`을 `INSERT OR IGNORE` → 가장 최근 체크인은 지워도 다시 생김 | 확인 |
| 집계 | `sensor_daily_rollups`는 데모 시드 경로에서만 생성됨. Beacon 측정은 집계 없음 | 확인(`sqlite_store._refresh_demo_rollup`만 INSERT) |
| 브라우저 | Chromium 계열(Popover API·`<dialog>`·컨테이너 쿼리 지원 필요: Chrome ≥ 114, Safari ≥ 17, Firefox ≥ 125) | 가정 |
| 이미지 미리보기 권한 | `GET /dashboard/assets/{id}/preview`는 세션만 확인하고 **소유 계정은 확인하지 않음** | 확인. 기존 문제, 이번 범위에서 고치지 않고 보고서에 기록 |

---

## 2. 금지와 안전 규칙

- 새 npm·pip 의존성을 추가하지 않는다(`package.json`, `pyproject.toml` diff 금지).
- `.env`, `secrets.h`, `storage/` 아래 실데이터를 읽어 출력하거나 수정하지 않는다. 테스트는 임시 DB(`tempfile`)만 쓴다.
- 운영 DB에 대한 삭제 API 호출은 사람이 한다. Codex는 `dry_run=true`만 호출할 수 있다.
- `services/beacon/`, 펌웨어, `infra/compose.yaml`을 수정하지 않는다.
- `sudo`, `apt`, 시스템 설정 변경, 컨테이너 재시작 정책 변경 금지. `docker compose ... build/run/up`은 허용.
- `main`에 직접 커밋하지 않는다. 브랜치 `ui/beacon-v1.1`에서 단계(11절)마다 커밋하고 push는 사람이 한다. 커밋 메시지 접두사 `beacon-ui:`.
- 모든 외부 명령에 `timeout`을 건다. 서버를 백그라운드로 남겨 두지 않는다(`up -d`로 띄운 경우 단계 끝에 상태만 보고하고 사람이 판단).
- 성공을 추측으로 쓰지 않는다. 모든 단계는 명령, 종료 코드, 로그 근거와 함께 보고한다.

---

## 3. 산출물 트리

```
docs/
  SPEC_DEV_BEACON_UI.md            NEW  이 문서 (사람이 배치)
  SPEC_UI_BEACON.md                NEW  디자인 명세 v1.1 (사람이 배치)
  design/beacon-dashboard-sample.html NEW 시각 기준 (사람이 배치)
  beacon-dashboard-ui-spec.md      DELETE (대체됨)
  report_ui_beacon.md              NEW  16절 보고서

services/api/
  app/schemas.py                   EDIT  BeaconDataDeleteRequest
  app/main.py                      EDIT  POST /dashboard/beacons/{node_id}/data/delete
  app/services/beacon_store.py     EDIT  감사 테이블, latest_readings, detail 보강, delete_data()
  tests/__init__.py                NEW  (빈 파일)
  tests/test_beacon_store_ui.py    NEW  4.6절

apps/web/
  app/layout.tsx                   EDIT  tokens.css, beacon.css import
  app/tokens.css                   NEW   5.1
  app/beacon.css                   NEW   5.2
  app/dashboard.css                EDIT  12절(D7)에서 Beacon·데이터 서버·폴더 탭 규칙 삭제
  components/ChatApp.tsx           EDIT  7.1
  components/FarmGeographyPanel.tsx EDIT 7.2
  components/BeaconDashboard.tsx   DELETE (D7)
  components/DataServerDashboard.tsx DELETE (D7)
  components/BeaconDataExplorer.tsx DELETE (D7)
  components/beacon/
    types.ts  api.ts  format.ts  energy.ts  csv.ts
    BeaconFleetProvider.tsx
    hooks/  usePolling.ts  useNow.ts  useBeaconDetail.ts  useSelection.ts  usePendingDeletes.ts
    ui/     Icon.tsx  Button.tsx  Badge.tsx  Dialog.tsx  Menu.tsx  Toasts.tsx  Segmented.tsx
            Checkbox.tsx  Battery.tsx  SignalBars.tsx  Sparkline.tsx  EmptyState.tsx
    shell/  DashboardTabs.tsx  ContextBar.tsx  SystemPopover.tsx
    fleet/  BeaconWorkspace.tsx  FleetHero.tsx  DeviceGrid.tsx  DeviceCard.tsx
            DeviceDialog.tsx  DeliveryBar.tsx  StatusTab.tsx  ActivityTab.tsx  SettingsTab.tsx
            AddBeaconDialog.tsx  ConfirmDialog.tsx
    data/   DataWorkspace.tsx  SourceRail.tsx  KindSegment.tsx  SensorView.tsx  LineChart.tsx
            ImageGallery.tsx  Lightbox.tsx  CheckinTable.tsx  CommandTable.tsx
            SelectionBar.tsx  DeleteDialog.tsx
```

파일 하나는 300줄을 넘기지 않는다(넘으면 하위 컴포넌트로 나눈다). 모든 클라이언트 컴포넌트 첫 줄은 `"use client";`.

---

## 4. 백엔드

### 4.1 감사 테이블

`BeaconStore.initialize()`의 `executescript`에 추가:

```sql
CREATE TABLE IF NOT EXISTS beacon_data_deletions (
  deletion_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id    INTEGER NOT NULL,
  node_id       TEXT NOT NULL,
  kind          TEXT NOT NULL,          -- sensor|image|checkin|command
  mode          TEXT NOT NULL,          -- ids|before|all
  matched       INTEGER NOT NULL,
  deleted       INTEGER NOT NULL,
  skipped       INTEGER NOT NULL DEFAULT 0,
  freed_bytes   INTEGER NOT NULL DEFAULT 0,
  criteria_json TEXT NOT NULL,          -- {"ids_count":n,"sensor_ids":[...],"before":"...","all":false}
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS beacon_data_deletions_node_idx
  ON beacon_data_deletions(node_id, created_at DESC);
```
측정값·이미지 내용은 기록하지 않는다. `dry_run`은 기록하지 않는다.

### 4.2 목록 응답에 `latest_readings`

새 메서드 `BeaconStore._latest_readings(db, node_id, limit=4) -> list[dict]`:

```sql
SELECT d.sensor_id, d.display_name, d.sensor_type, d.unit,
       r.value, r.unit AS reading_unit, r.recorded_at
FROM sensor_devices d
LEFT JOIN sensor_readings r ON r.reading_id = (
  SELECT reading_id FROM sensor_readings
  WHERE sensor_id = d.sensor_id
  ORDER BY recorded_at DESC, reading_id DESC LIMIT 1)
WHERE json_extract(d.metadata_json, '$.beacon_node_id') = ?
  AND d.status = 'active'
ORDER BY CASE d.sensor_type WHEN 'temperature' THEN 0 WHEN 'humidity' THEN 1 ELSE 2 END,
         d.display_name
LIMIT ?;
```
반환 항목: `{"sensor_id","display_name","sensor_type","value"(float|None),"unit"(reading_unit 우선, 없으면 d.unit),"recorded_at"(str|None)}`.

`update_node_snapshot()`의 각 출력 dict와 `cached_nodes()`의 각 dict에 `"latest_readings": self._latest_readings(db, node_id)`를 추가한다(기존 `with self._connect() as db` 블록 안에서, 노드당 쿼리 1회). 다른 키는 바꾸지 않는다.

### 4.3 상세 응답 보강 (`BeaconStore.detail`)

| 위치 | 변경 |
|---|---|
| 센서 `history` SELECT | `SELECT reading_id, value, unit, recorded_at, quality ...` (`reading_id` 추가) |
| 센서 `latest` SELECT | 같은 열 구성 |
| 센서 항목 | `"reading_count": SELECT COUNT(*) FROM sensor_readings WHERE sensor_id=?` 추가 |
| 이미지 | LIMIT 30 유지, 최상위에 `"image_count"`(같은 JOIN 조건의 COUNT) 추가 |
| 체크인 | `SELECT *`라 `checkin_id`는 이미 포함. 최상위에 `"checkin_count"` 추가 |
| 작업 | 변경 없음(`list_history` 100건) |

### 4.4 요청 모델 (`app/schemas.py`)

```python
class BeaconDataDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["sensor", "image", "checkin", "command"]
    ids: list[str] | None = Field(None, min_length=1, max_length=1000)
    sensor_ids: list[str] | None = Field(None, min_length=1, max_length=32)
    before: datetime | None = None
    all: bool = False
    confirm_label: str | None = Field(None, max_length=64)
    dry_run: bool = False

    @model_validator(mode="after")
    def one_mode(self) -> "BeaconDataDeleteRequest":
        modes = [self.ids is not None, self.before is not None, self.all]
        if sum(modes) != 1:
            raise ValueError("ids, before, all 중 정확히 하나를 지정하세요.")
        if self.sensor_ids is not None and (self.kind != "sensor" or self.ids is not None):
            raise ValueError("sensor_ids는 kind=sensor의 기간·전체 삭제에서만 쓸 수 있습니다.")
        if self.before is not None and self.before.tzinfo is None:
            raise ValueError("before에는 시간대가 있어야 합니다.")
        return self

    @property
    def mode(self) -> str:
        return "ids" if self.ids is not None else "all" if self.all else "before"
```
`ids` 형식 검사는 store에서 한다: `sensor`·`checkin`·`command`는 정수 문자열(`^\d{1,18}$`), `image`는 `^beacon-command-\d{1,18}$`. 하나라도 어긋나면 `ValueError` → 422.

### 4.5 라우트와 store 메서드

`app/main.py`(기존 Beacon 라우트들 옆):

```python
@app.post("/dashboard/beacons/{node_id}/data/delete", dependencies=[Depends(require_session)])
async def delete_dashboard_beacon_data(
    node_id: str, payload: BeaconDataDeleteRequest, request: Request,
    user: AuthenticatedUser = Depends(require_session),
) -> dict[str, object]:
    if not re.fullmatch(r"tc-[0-9a-f]{6}", node_id):
        raise HTTPException(status_code=422, detail="Beacon ID 형식이 올바르지 않습니다.")
    store: BeaconStore = request.app.state.beacon_store
    try:
        return await asyncio.to_thread(store.delete_data, user.account_id, node_id, payload.model_dump(mode="python") | {"mode": payload.mode})
    except (KeyError, PermissionError):
        raise HTTPException(status_code=404, detail="등록된 beacon을 찾지 못했습니다.") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```
`asyncio.to_thread`로 이벤트 루프를 막지 않는다. 존재하지 않는 장치와 다른 계정 장치는 **같은 404**로 응답한다.

`BeaconStore.delete_data(account_id, node_id, req) -> dict` 규칙:

1. **소유권**: `SELECT label FROM beacon_node_profiles WHERE node_id=? AND account_id=?`. 없으면 `KeyError`(기존 `_assert_owner`는 프로필이 없으면 통과시키므로 여기서는 쓰지 않는다).
2. **all 확인**: `mode=="all"`이면 `confirm_label.strip() == label`이 아니면 `ValueError("장치 이름이 일치하지 않습니다.")`.
3. **대상 조건**(kind별 WHERE). `before`는 UTC로 바꿔 비교한다: 문자열 시각 열은 `before.astimezone(timezone.utc).isoformat()`, REAL 열은 `before.timestamp()`.

| kind | 대상 집합 | ids 모드 | before 모드 | 제외(건너뜀) |
|---|---|---|---|---|
| sensor | `sensor_readings` 중 `sensor_id ∈ S`, S = 이 노드 소유 센서(`json_extract(metadata_json,'$.beacon_node_id')=?`) ∩ `sensor_ids`(있으면) | `reading_id IN (...)` | `recorded_at < ?`(ISO) | — |
| image | `camera_assets` 중 `camera_id = 'beacon:'||node_id` | `asset_id IN (...)` | `captured_at < ?`(ISO) | — |
| checkin | `beacon_node_checkins` 중 `node_id=?` | `checkin_id IN (...)` | `received_at < ?`(epoch) | 이 노드의 `MAX(received_at)` 행 → `skipped_current` |
| command | `beacon_commands` 중 `node_id=? AND account_id=?` | `command_id IN (...)` | `created_at < ?`(epoch) | `state NOT IN ('done','failed','expired')` → `skipped_busy` |

4. **dry_run**: 같은 조건으로 `COUNT(*)`, 시각 `MIN/MAX`, (image) `SUM(byte_size)`, 제외 건수만 계산해 반환. 아무것도 쓰지 않는다.
5. **삭제**:
   - ids 모드: 한 트랜잭션(`BEGIN IMMEDIATE`).
   - before/all 모드: 5,000행씩 `DELETE ... WHERE <pk> IN (SELECT <pk> FROM ... WHERE <조건> LIMIT 5000)`를 `rowcount==0`까지 반복, 배치마다 커밋. 중간 예외 시 지금까지의 `deleted`를 담아 `RuntimeError`를 올리고 라우트는 500 `{"detail": "...", "deleted": n}`.
   - image: 행 삭제와 같은 트랜잭션에서 `UPDATE beacon_commands SET image_asset_id=NULL WHERE image_asset_id IN (...)`. `vision_runs`·`vision_observations`는 FK `ON DELETE SET NULL`이 처리한다. **커밋 후** 파일 삭제: `p = (data_root / file_path).resolve()`, `allowed = (data_root / "raw" / "beacons" / node_id).resolve()`; `allowed in p.parents`일 때만 `p.unlink(missing_ok=True)`. 범위를 벗어나거나 `OSError`면 `file_errors += 1`(로그에 asset_id만).
   - command: 같은 트랜잭션에서 `DELETE FROM beacon_sensor_results WHERE command_id IN (지운 id)`.
6. **감사 기록** 1행(4.1). dry_run 제외.
7. **응답**:
```json
{"kind":"sensor","mode":"before","dry_run":false,
 "matched":1234,"deleted":1234,"skipped_busy":0,"skipped_current":0,
 "freed_bytes":0,"file_errors":0,
 "range":{"from":"2026-10-30T00:00:00+00:00","to":"2026-11-12T23:30:00+00:00"}}
```
`matched` = 조건에 맞은 행 수(제외 포함), `deleted` = 실제 삭제 수. ids 모드에서 남의 노드 id·없는 id는 `matched`에 넣지 않는다. `range`는 삭제 대상(제외 뺀) 시각의 최소·최대, 없으면 `null`.

### 4.6 백엔드 테스트 (`services/api/tests/test_beacon_store_ui.py`)

표준 `unittest`만 쓴다. `setUp`: `tempfile.TemporaryDirectory()`, `SQLiteStore(db).initialize()` → `BeaconStore(db, data_root).initialize()` → 계정 1·2의 프로필, 센서 행, 측정 10건, 이미지 행 + 실제 JPEG 바이트 파일 3개, 체크인 5건, 작업(done 3, queued 1)을 직접 INSERT.

| 테스트 | 검증 |
|---|---|
| `test_latest_readings_order_and_values` | 온도 → 습도 순, 값·단위·시각이 최신 행과 같음 |
| `test_detail_has_ids_and_counts` | `reading_id`, `reading_count`, `image_count`, `checkin_count` |
| `test_delete_sensor_ids` | 지정 3건만 삭제, 감사 1행 |
| `test_delete_sensor_ids_foreign_ignored` | 다른 노드의 reading_id 섞어도 그 행은 그대로, `matched`에서 빠짐 |
| `test_delete_sensor_before_scoped` | `sensor_ids`로 한 센서만, `before` 이전만 |
| `test_dry_run_writes_nothing` | 모든 kind에서 행 수·파일·감사 테이블 불변, 건수 정확 |
| `test_delete_all_requires_label` | 이름 불일치 `ValueError`, 일치 시 전부 삭제 |
| `test_delete_image_removes_file_and_row` | 행·파일 삭제, `freed_bytes`, `beacon_commands.image_asset_id` NULL |
| `test_delete_image_path_escape_blocked` | `file_path='../../evil.jpg'` 행: 행은 지워도 바깥 파일은 남고 `file_errors=1` |
| `test_delete_checkin_keeps_latest` | `all`이어도 최신 1건 남음, `skipped_current=1` |
| `test_delete_command_skips_busy` | queued 작업은 남고 `skipped_busy=1`, 결과 행도 함께 삭제 |
| `test_not_owner_is_keyerror` | 계정 2가 계정 1 노드 삭제 시 `KeyError` |
| `test_bad_id_format` | `"abc"` → `ValueError` |
| `test_request_model_modes` | `BeaconDataDeleteRequest`: 모드 0개·2개, 시간대 없는 before, sensor_ids 오용 → 검증 오류 |

실행(컨테이너, 테스트 폴더만 마운트):
```bash
timeout 900 docker compose -f infra/compose.yaml build api
timeout 300 docker compose -f infra/compose.yaml run --rm --no-deps \
  -v "$PWD/services/api/tests:/app/tests:ro" api \
  python -m unittest discover -s tests -v 2>&1 | tee docs/_logs/api_tests.log
```

---

## 5. 프론트 공통

### 5.1 `app/tokens.css`
샘플 HTML `<style>`의 첫 `:root{...}` 블록을 **값 그대로** 옮긴다(UI-4.1). 추가 규칙 없음. `layout.tsx` import 순서: `globals.css` → `tokens.css` → `dashboard.css` → `beacon.css`.

### 5.2 `app/beacon.css`
샘플의 나머지 스타일을 옮기되 모든 클래스에 `bx-` 접두를 붙이고, 모든 규칙을 `.bx-root` 또는 다이얼로그·팝오버 루트(`.bx-dialog`, `.bx-pop`, `.bx-toasts`) 아래로 한정한다. 옮기지 않는 것: `.workspace`, `.chat-mock`, `.handle`, `.dash`, `.demo-switch`, `.page-head`, `body`·`html` 규칙, `.mini-map`(실제 지도를 쓴다).

| 샘플 | 구현 | 비고 |
|---|---|---|
| `.tabs` `.tab` | `.bx-tabs` `.bx-tab` | ChatApp 탭(7.1) |
| `.context` `.farm-switch` `.sys-pill` `.pulse` `.sync` | `.bx-context` `.bx-farm-switch` `.bx-sys-pill` `.bx-pulse` `.bx-sync` | |
| `.btn` `.btn-primary` `.btn-secondary` `.btn-ghost` `.btn-danger` `.btn-danger-ghost` `.btn-green` `.btn-icon` `.btn-sm` `.btn-group` | `.bx-btn` + `--primary` `--secondary` `--ghost` `--danger` `--danger-ghost` `--green` `--icon` `--sm`, `.bx-btn-group` | BEM 수식어 |
| `.badge` `.b-ok` … `.plain` | `.bx-badge` `.bx-badge--ok` … `.bx-badge--plain` | |
| `.hero` `.hstat` | `.bx-hero` `.bx-hero-stat` | |
| `.sec-head` `.search` | `.bx-sec-head` `.bx-search` | |
| `.cards` `.dcard` `.dico` `.add-card` `.pend` `.batt*` | `.bx-cards` `.bx-card` `.bx-dev-icon` `.bx-card-add` `.bx-pending` `.bx-batt*` | |
| `.backdrop` `.dialog` `.dialog.lg` | `dialog.bx-dialog` `.bx-dialog--lg`, 배경은 `::backdrop` | 5.4 |
| `.dd-*` `.delivery` `.cycle` `.subtabs` `.subtab` | `.bx-dd-*` `.bx-delivery` `.bx-cycle` `.bx-subtabs` `.bx-subtab` | |
| `.stat*` `.spark` `.sig` `.sensor-row` `.s-ico` `.energy` | `.bx-stat*` `.bx-spark` `.bx-sig` `.bx-sensor-row` `.bx-s-ico` `.bx-energy` | |
| `.timeline` `.tl-*` `.steps` `.kv` `.danger-zone` `.dz-row` | `.bx-timeline` `.bx-tl-*` `.bx-steps` `.bx-kv` `.bx-danger-zone` `.bx-dz-row` | |
| `.pop` `.mi` `.msep` `.mlabel` `.sys-pop` | `.bx-pop` `.bx-menu-item` `.bx-menu-sep` `.bx-menu-label` `.bx-sys-pop` | Popover API(5.4) |
| `.explorer` `.src-*` `.ex-*` `.crumbs` `.segmented` `.src-chip` | `.bx-explorer` `.bx-src-*` `.bx-ex-*` `.bx-crumbs` `.bx-segmented` `.bx-src-chip` | |
| `.metric*` `.chart-card` `.chart` `.tip` | `.bx-metric*` `.bx-chart-card` `.bx-chart` `.bx-chart-tip` | |
| `table.data` `.data-scroll` `.cb` `.cb-col` | `table.bx-table` `.bx-table-scroll` `.bx-checkbox` `.bx-cb-col` | |
| `.gallery` `.shot` `.day-label` | `.bx-gallery` `.bx-shot` `.bx-day-label` | |
| `.bulkbar` | `.bx-selection-bar` | |
| `.del-ico` `.summary` `.callout` `.radio-list` `.radio-row` `.field` | `.bx-del-ico` `.bx-summary` `.bx-callout` `.bx-choices` `.bx-choice` `.bx-field` | |
| `.stepper` `.stp` `.presets` `.preset` | `.bx-stepper` `.bx-step` `.bx-presets` `.bx-preset` | |
| `.toasts` `.toast` `.undo` `.bar` | `.bx-toasts` `.bx-toast` `.bx-toast-action` `.bx-toast-bar` | |
| `.empty` | `.bx-empty` | |

`.bx-root{container-type:inline-size;container-name:dash}`를 두고, 샘플의 `@container dash (...)` 규칙을 그대로 쓴다. 뷰포트 기준 규칙은 두 개만 남긴다: 다이얼로그 아래 시트(`@media (max-width:640px)`), `prefers-reduced-motion`.

### 5.3 `types.ts`

```ts
export type NodeState = "ATTACHED" | "DISCOVERED" | "DETACHED" | "HIBERNATING" | "UNKNOWN";
export type HealthKey = "ok" | "warn" | "offline" | "idle";
export type FleetFilter = "all" | "ok" | "warn" | "offline";

export type Location = { site?: string | null; zone?: string | null; row?: string | null; position?: string | null; latitude?: number | null; longitude?: number | null };
export type SensorInfo = { sensor_id?: string; type?: string; model?: string; address?: string | number; fields?: string[]; units?: Record<string, string> };
export type BeaconMetadata = { schema_version?: number; label?: string; location?: Location; installed_at?: string | null; hardware?: Record<string, unknown>; sensors?: SensorInfo[] };
export type LatestReading = { sensor_id: string; display_name: string; sensor_type: string; value: number | null; unit: string; recorded_at: string | null };

export type BeaconNode = {
  node_id: string; state: NodeState; online: boolean; registered: boolean; farm_id: string | null;
  label: string; metadata: BeaconMetadata; interval_s: number; requested_data: ("sensor" | "image")[];
  first_seen: number | null; last_seen: number | null; next_given: number | null; next_expected_at: number | null;
  last_ip: string | null; last_rssi: number | null; last_vbat_mv: number | null; last_seq: number | null; last_ch: number | null; fw: string | null;
  last_boot: string | null; last_wifi_ms: number | null; last_fast: number | null; last_prev_awake_ms: number | null; last_prev_result: string | null;
  sensor_count: number; pending_commands: number; latest_readings: LatestReading[];
};
export type NodesResponse = { reachable: boolean; error?: string; nodes: BeaconNode[] };

export type Reading = { reading_id: number; value: number; unit: string; recorded_at: string; quality: string | null };
export type SensorEntry = { device: { sensor_id: string; display_name: string; sensor_type: string; unit: string; status: string; metadata: Record<string, unknown> }; latest_reading: Reading | null; readings: Reading[]; reading_count: number };
export type ImageEntry = { asset_id: string; captured_at: string; byte_size: number | null; width: number | null; height: number | null; content_type: string | null };
export type CommandState = "queued" | "dispatched" | "done" | "failed" | "expired";
export type CommandEntry = { command_id: number; node_id: string; command_type: "sensor" | "image" | "config" | "hibernate"; params: Record<string, unknown> | null; state: CommandState; reason: string | null; attempts: number; created_at: number | null; dispatched_at: number | null; done_at: number | null; result: Record<string, unknown> | null; image_asset_id: string | null };
export type Checkin = { checkin_id: number; node_id: string; received_at: number; seq: number | null; boot: string | null; vbat_mv: number | null; rssi: number | null; channel: number | null; wifi_ms: number | null; fast: number | null; prev_awake_ms: number | null; prev_result: string | null; next_given: number | null };
export type BeaconDetail = { node: BeaconNode; profile: { farm_id: string | null; metadata: BeaconMetadata; interval_s: number; requested_data: ("sensor" | "image")[] }; sensors: SensorEntry[]; images: ImageEntry[]; image_count: number; commands: CommandEntry[]; checkins: Checkin[]; checkin_count: number };
export type Energy = { interval_s: number; observed_checkins_24h: number; fast_success_fraction_24h: number; images_24h: number; sensor_commands_24h: number; estimated_mAh_day: number; usable_mah: number; estimated_days_remaining: number | null; assumptions: Record<string, number> };
export type UsbPort = { port: string; kind: string; label?: string };
export type Farm = { id: string; name: string; latest_boundary: unknown | null; [key: string]: unknown };

export type DeleteKind = "sensor" | "image" | "checkin" | "command";
export type DeleteRequest = { kind: DeleteKind; ids?: string[]; sensor_ids?: string[]; before?: string; all?: boolean; confirm_label?: string; dry_run?: boolean };
export type DeleteResponse = { kind: DeleteKind; mode: "ids" | "before" | "all"; dry_run: boolean; matched: number; deleted: number; skipped_busy: number; skipped_current: number; freed_bytes: number; file_errors: number; range: { from: string; to: string } | null };
```
`Energy`의 `estimated_days_remaining`은 이름과 달리 **만충 기준 수명**이다(UI-2.3). 화면 문구는 항상 "만충 기준 수명".

### 5.4 브라우저 기본 기능 사용 규칙 (중요)

- **다이얼로그**: `<dialog className="bx-dialog">` + `showModal()`. 닫기: `cancel` 이벤트(Esc), `×`, 배경 클릭(`onClick`에서 `e.target === dialogRef.current`). 열 때 `document.activeElement`를 저장하고 닫을 때 그 요소로 `focus()`. 초기 포커스는 `autoFocus` 지정 요소, 없으면 닫기 버튼. 여러 개가 쌓이면 Esc는 맨 위 것만 닫는다(기본 동작).
- **메뉴·팝오버**: 모달 다이얼로그는 top layer에 올라가므로 `document.body`에 그린 일반 요소는 그 **아래에 깔린다**. 메뉴·시스템 팝오버는 HTML Popover API(`popover="auto"` + `showPopover()`)로 띄워 top layer에 올린다. 위치는 앵커의 `getBoundingClientRect()`로 `position:fixed` 좌표를 계산하고, 화면 밖으로 나가면 8 px 안쪽으로 붙인다. 바깥 클릭·Esc 닫힘은 기본 동작을 쓴다.
- **토스트**: 같은 이유로 컨테이너를 `popover="manual"`로 띄운다. 토스트를 추가할 때마다 `hidePopover(); showPopover();`를 호출해 열려 있는 다이얼로그보다 위로 다시 올린다.
- 다이얼로그 열림 애니메이션에는 `transform`을 쓰지 않는다(`opacity`만). 다이얼로그 안의 `position:fixed` 요소 좌표가 틀어지지 않게 하기 위해서다.

### 5.5 `api.ts`

```ts
export class ApiError extends Error { constructor(public status: number, message: string, public body?: unknown) { super(message); } }
type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
export function createBeaconApi(fetchProtected: Fetch) { return {
  listNodes(signal?: AbortSignal): Promise<NodesResponse>,                       // GET  /api/backend/dashboard/beacons
  getNode(id: string, signal?: AbortSignal): Promise<BeaconDetail>,              // GET  …/beacons/{id}
  getEnergy(id: string, signal?: AbortSignal): Promise<Energy>,                  // GET  …/beacons/{id}/energy
  listUsb(): Promise<{ reachable: boolean; ports: UsbPort[] }>,                  // GET  …/beacons/usb
  resetUsb(port: string): Promise<unknown>,                                      // POST …/beacons/usb/{port}/reset  body {}
  configure(id: string, body: ConfigureBody): Promise<unknown>,                  // PUT  …/beacons/{id}/configure
  action(id: string, name: "detach"|"watch"|"session"|"hibernate", body: object): Promise<unknown>, // POST …/actions/{name}
  command(id: string, body: { type: "sensor"|"image"; fs?: string; q?: number; warm?: number }): Promise<{ command_id: number }>, // POST …/commands
  deleteData(id: string, body: DeleteRequest, signal?: AbortSignal): Promise<DeleteResponse>, // POST …/beacons/{id}/data/delete
  listFarms(): Promise<Farm[]>,                                                  // GET  /api/backend/api/v1/farms
}; }
```
- 모든 요청 `cache: "no-store"`, JSON 본문은 `content-type: application/json`.
- 응답이 2xx가 아니면 `ApiError(status, detail)`. `detail`은 `body.detail`이 문자열이면 그것, 객체면 `detail.message`, 그 외 "요청을 완료하지 못했습니다.".
- `fetchProtected`의 401 처리(로그아웃)는 기존대로 ChatApp이 한다.
- `command()` 응답에서 `command_id`가 없으면 `ApiError(500, "명령 번호를 받지 못했습니다.")`.

### 5.6 `format.ts` (UI-8, UI-4.4)

| 함수 | 규칙 |
|---|---|
| `health(node): {key: HealthKey; label: string; tone: "ok"|"warn"|"danger"|"green"|"idle"}` | UI-4.4 표 순서. `state==="UNKNOWN"`(서버 연결 불가 캐시)는 `idle`·"정보 없음" |
| `vbatLevel(mv)` | `<3300` danger, `<3450` warn, 그 외 ok, `null` idle. 상수 `VBAT_WARN=3450`, `VBAT_CRIT=3300` |
| `vbatFill(mv)` | `clamp((mv−3300)/(4200−3300), 0.06, 1)` |
| `signalLevel(rssi)` | ≥−55 → 4, ≥−67 → 3, ≥−75 → 2, 그 외 1, `null` → 0 |
| `relTime(sec)` | <45 "방금", <3600 "N분 전", <86400 "N시간 전", 그 외 "N일 전" |
| `countdown(sec)` | `M분 SS초` / `S초` / ≤0 "곧" |
| `intervalLabel(sec)` | 3600 배수 → 시간, 60 배수 → 분, 그 외 초 |
| `clock(t)`, `dateTime(t)`, `dayLabel(t)` | `Intl.DateTimeFormat("ko-KR")`, 24시간제. `t`는 epoch 초 또는 ISO 문자열 |
| `bytes(n)` | KB(소수 1) / MB(소수 2), `null` → "크기 미상" |
| `metricLabel(sensor_type, fallback)` | temperature 온도, humidity 습도, soil_moisture 토양 수분, illuminance 조도, co2 CO₂ |
| `unitShort(unit)` | `%RH` → `%`, 그 외 그대로 |
| `value1(v)` | 소수 1자리 고정(`17` → `17.0`) |
| `commandLabel`, `commandStateLabel`, `failReason(reason)` | UI-8 표. `no_result` → "결과 없음(3회 전달)", `low_battery` → "배터리 부족으로 거부" |
| `deliveryInfo(node, now)` | `{pct, left, late, note}`: pct=`(now−last_seen)/next_given·100`(0~100), left=`next_expected_at−now`, late=`left<−30`, note=`next_given≤60 && interval_s>60` → "자주 확인 모드", `next_given>interval_s` → "저전압으로 연장됨" |

### 5.7 `energy.ts`
```ts
export const ENERGY_DEFAULTS = { usableMah: 1560, activeMa: 120, camMa: 160, offUa: 20, fastS: 1.5, imageS: 1.2, imagesPerDay: 24 };
export function estimateDays(intervalS: number, withImage: boolean, c = ENERGY_DEFAULTS): number
// 일 소모 = (86400/T)·activeMa·fastS/3600 + (withImage ? imagesPerDay·camMa·imageS/3600 : 0) + offUa·24/1000
export function daysLabel(d: number): string // d > 365 → "1년 이상", 그 외 `약 ${d}일`
```
값은 `services/beacon/config.json`의 `energy`(`i_active_ma 120`, `i_cam_ma 160`, `i_off_ua 20`, `usable_mah 1560`, `checkin_fast_s 1.5`, `image_active_s 1.2`)와 같다(2026-11-20 `9931d45`에서 확인). D0에서 다시 읽어 다르면 보고하고 파일 값을 쓴다.

### 5.8 `csv.ts`
`toCsv(columns: {key: string; label: string}[], rows: object[]): string`. 첫 글자 UTF-8 BOM(`﻿`, 엑셀 한글), 구분자 `,`, 줄바꿈 `\r\n`, `"`·`,`·줄바꿈이 있으면 큰따옴표로 감싸고 `"`는 `""`로. `downloadCsv(name, text)`는 `Blob` + 임시 `<a download>`. 파일명 `${node_id}_${kind}_${YYYYMMDD-HHmm}.csv`.

### 5.9 훅

```ts
// hooks/usePolling.ts
export function usePolling(
  task: (signal: AbortSignal) => Promise<void>,
  opts: { intervalMs: number; enabled: boolean; deps?: unknown[] },
): { refresh: () => void; failures: number }
```
- `enabled`가 true가 되면 즉시 1회, 이후 `intervalMs`마다. `document.hidden`이면 멈추고 `visibilitychange`로 보이면 즉시 1회.
- 실행 중이면 다음 틱을 건너뛴다. 언마운트·`deps` 변경 시 `AbortController.abort()`.
- 연속 실패 3회부터 간격을 `max(intervalMs, 30000)`으로 늘리고, 성공하면 원래대로. `failures`를 돌려준다.

```ts
// hooks/useNow.ts — 구독한 컴포넌트만 리렌더
export function useNow(enabled: boolean, stepMs = 1000): number // epoch 초
```

```ts
// hooks/useBeaconDetail.ts
export function useBeaconDetail(nodeId: string | null, opts: { intervalMs: number; paused?: boolean }):
  { detail: BeaconDetail | null; error: string | null; loading: boolean; reload: () => void }
```
- `nodeId`가 바뀌면 `detail=null`로 비우고 새로 부른다. `paused`면 폴링만 멈추고(값 유지) `reload()`는 동작.
- 같은 장치를 두 화면이 동시에 보는 경우는 없으므로(팝업은 Beacon 탭, 본문은 데이터 서버 탭) 공유 캐시는 만들지 않는다.

```ts
// hooks/useSelection.ts
export function useSelection(): { ids: Set<string>; has(id: string): boolean; toggle(id: string): void; setMany(ids: string[], on: boolean): void; clear(): void; size: number }
```

```ts
// hooks/usePendingDeletes.ts — BeaconFleetProvider 안에서 1개만 생성
type Pending = { key: string; nodeId: string; kind: DeleteKind; request: DeleteRequest; label: string; count: number;
                 hides: (item: { id: string; t: number; sensorId?: string }) => boolean; timer: number };
export function usePendingDeletes(api, toasts, onCommitted: (nodeId: string) => void): {
  schedule(p: Omit<Pending, "key" | "timer">): void;   // 6000 ms 후 api.deleteData
  undo(key: string): void;
  isHidden(nodeId: string, kind: DeleteKind, item: { id: string; t: number; sensorId?: string }): boolean;
  hasPending(nodeId: string): boolean;
}
```
- `schedule`: 즉시 `isHidden`에 반영, 토스트(제목 `${종류} ${count}${단위} 삭제됨`, 본문 `${label} · 6초 후 서버에서 확정됩니다`, 행동 `실행 취소`, 6000 ms). 6 s 후 `api.deleteData(nodeId, request)`.
- 성공: 항목 제거 후 `onCommitted(nodeId)`(상세 다시 불러오기). `deleted < count`이면 경고 토스트 "요청 ${count}건 중 ${deleted}건만 삭제되었습니다". `skipped_current`·`skipped_busy`가 있으면 사유를 붙인다.
- 실패: 항목 제거(행 다시 보임) + 오류 토스트(자동 닫힘 없음, `다시 시도` → 같은 요청을 바로 전송).
- `pagehide`: 대기 중인 타이머를 모두 취소하고 **보내지 않는다**.
- ids 모드의 `hides`는 `ids.has(item.id)`, before 모드는 `item.t < beforeEpoch && (!sensorIds || sensorIds.has(item.sensorId))`, all은 항상 true(체크인은 최신 1건 제외).

### 5.10 UI 기본 부품 (`ui/`)

| 파일 | 계약 |
|---|---|
| `Icon.tsx` | `<Icon name="trash" size={14|16} />`. 이름과 path는 샘플 HTML의 `<symbol id="i-*">`에서 **스크립트로 추출**해 `const PATHS: Record<IconName, string>`로 만든다(손으로 옮기지 않는다). `aria-hidden="true"` 기본 |
| `Button.tsx` | `variant: "primary"|"secondary"|"ghost"|"danger"|"danger-ghost"|"green"`, `size?: "sm"`, `icon?: IconName`, `iconOnly?: boolean`(이때 `aria-label` 필수, 타입으로 강제), 나머지는 `button` 속성 그대로 |
| `Badge.tsx` | `tone: "ok"|"warn"|"danger"|"green"|"idle"|"orange"`, `dot?: boolean` |
| `Dialog.tsx` | `open`, `onClose`, `size?: "md"|"lg"`, `labelledBy`, `children`. 5.4 규칙 구현 |
| `Menu.tsx` | `<Menu anchor={ref} open onClose items={[{label, hint?, icon?, danger?, onSelect, kbd?} | "sep" | {heading}]} />`. Popover API, `role="menu"`, ↑/↓/Home/End/Enter |
| `Toasts.tsx` | `ToastProvider` + `useToasts().push({title, body?, tone: "ok"|"wait"|"error", action?: {label, onClick}, durationMs?: number | null})`. 최대 3개(넘치면 가장 오래된 것 제거), 호버 중 타이머 정지, `null`이면 자동 닫힘 없음 |
| `Segmented.tsx` | `options: {value, label, icon?, count?}[]`, `value`, `onChange`. `role="group"` + 각 버튼 `aria-pressed` |
| `Checkbox.tsx` | `checked`, `indeterminate`, `disabled`, `title`, `onChange`, `ariaLabel`. `indeterminate`는 ref로 설정 |
| `Battery.tsx` | `mv`, `showValue` → 막대 + `3.98 V`, `aria-label="배터리 3.98 V, 정상"` |
| `SignalBars.tsx` | `rssi` → 4칸, `aria-label="신호 −55 dBm"` |
| `Sparkline.tsx` | `values: number[]`, `color` → 160×28 viewBox SVG, 면 10% + 선 1.6 px(`vector-effect: non-scaling-stroke`) |
| `EmptyState.tsx` | `icon`, `title`, `body?`, `action?` |

---

## 6. 상태: `BeaconFleetProvider`

ChatApp의 대시보드 영역 전체(농장·Beacon·데이터 서버 탭)를 감싼다. `useBeaconFleet()`로 읽는다.

```ts
type DashboardTab = "farm" | "jeju-weather" | "data-server" | "beacon";
type AddDraft = { mode: "add" | "edit"; step: 1 | 2 | 3; nodeId: string | null; label: string;
                  intervalS: number; sensor: boolean; image: boolean; location: Location; metadata: BeaconMetadata };
type FleetCtx = {
  api: ReturnType<typeof createBeaconApi>;
  // 농장
  farms: Farm[]; farmId: string | null; farm: Farm | null; hasBoundary: boolean;
  setFarmId(id: string | null): void; reloadFarms(): Promise<void>;
  // 노드
  allNodes: BeaconNode[]; nodes: BeaconNode[];          // nodes = registered && farm_id === farmId
  discoverable: BeaconNode[];                           // !registered
  reachable: boolean | null; error: string | null; lastSyncAt: number | null; refreshNodes(): void;
  // 상세 팝업
  openDeviceId: string | null; openDevice(id: string): void; closeDevice(): void;
  highlightId: string | null;                           // 저장 직후 2 s 강조할 카드
  // 추가/편집 다이얼로그와 지도 배치
  addDraft: AddDraft | null; openAdd(): void; openEdit(nodeId: string): void; updateDraft(p: Partial<AddDraft>): void; closeAdd(): void;
  placement: { nodeId: string } | null;
  beginPlacement(): void;                               // addDraft 유지, 탭 → farm
  completePlacement(nodeId: string, point: [number, number]): void; // draft.location 갱신, 탭 → beacon, step 3
  cancelPlacement(): void;                              // 탭 → beacon, step 3
  // 데이터 서버 진입
  dataSelection: { nodeId: string; sensorId?: string } | null; openData(nodeId: string, sensorId?: string): void;
  // 삭제 대기
  pendingDeletes: ReturnType<typeof usePendingDeletes>;
};
```
Props: `{ fetchProtected, activeTab: DashboardTab, onNavigate: (tab: DashboardTab) => void, children }`.

규칙:
- **농장**: 마운트 시 `listFarms()`. 선택값은 `sessionStorage["mirgam.beacon.ui"].farmId`(try/catch)를 먼저, 없거나 목록에 없으면 첫 농장. `hasBoundary = Boolean(farm?.latest_boundary)`.
- **노드 폴링**: `usePolling(listNodes, {intervalMs: activeTab === "farm" ? 30000 : 10000, enabled: activeTab !== "jeju-weather"})`. 실패 시 `reachable=false`, 직전 목록 유지. `/dashboard/beacons`를 부르는 곳은 앱 전체에서 **여기 하나뿐**이다.
- **ID 형식**: 노드 ID는 `tc-[0-9a-f]{6}`. 이를 벗어나면 목록에서 제외하고 콘솔에 1회 경고.
- **배치 흐름**:
  ```
  AddBeaconDialog 3단계 → beginPlacement() → placement={nodeId}, onNavigate("farm")
     SavedFarmMap 클릭 → completePlacement(nodeId, [lon,lat]) → draft.location 갱신, placement=null, onNavigate("beacon"), draft.step=3
     지도에서 취소     → cancelPlacement()                    → placement=null, onNavigate("beacon"), draft.step=3
  ```
  탭을 바꿔도 `addDraft`는 Provider에 있으므로 유지된다. Beacon 탭으로 돌아오면 `addDraft`가 있으면 다이얼로그가 다시 열린다.
- **삭제 대기**: `usePendingDeletes(api, toasts, onCommitted)`를 여기서 만든다(탭을 바꿔도 6 s 타이머가 살아 있도록).
- `openData(nodeId, sensorId)`: `dataSelection` 설정, `closeDevice()`, `onNavigate("data-server")`.
- 농장이 바뀌면 `openDeviceId`, `addDraft`, `placement`를 비운다.

---

## 7. 기존 파일 수정

### 7.1 `ChatApp.tsx`
1. import에서 `DataServerDashboard` 제거, `BeaconFleetProvider`, `ToastProvider`, `DashboardTabs`, `ContextBar`, `BeaconWorkspace`, `DataWorkspace` 추가.
2. `dataSelection` 상태와 탭 클릭 시 `setDataSelection(null)` 제거(Provider로 이동, 마지막 선택 유지 — UI-7.6).
3. `<section className="farm-dashboard">` 안을 다음 구조로 바꾼다(헤더 `dashboard-header`의 eyebrow·h1·접기 버튼은 그대로):
```tsx
<ToastProvider>
  <BeaconFleetProvider fetchProtected={fetchProtected} activeTab={dashboardTab} onNavigate={setDashboardTab}>
    <DashboardTabs value={dashboardTab} onChange={setDashboardTab} />   {/* .bx-tabs, Beacon 개수 배지는 Provider nodes.length */}
    {dashboardTab === "jeju-weather" && <JejuWeatherDashboard fetchProtected={fetchProtected} />}
    {dashboardTab === "farm" && <>
      <FarmGeographyPanel /* 7.2: beacon 관련 props 제거 */ ... />
      {/* 기존 sensor-panel 블록 그대로 */}
    </>}
    {dashboardTab === "beacon" && <div className="bx-root"><ContextBar /><BeaconWorkspace /></div>}
    {dashboardTab === "data-server" && <div className="bx-root"><ContextBar /><DataWorkspace /></div>}
  </BeaconFleetProvider>
</ToastProvider>
```
4. 탭 순서와 라벨: `농장 현황`, `제주 날씨`, `Beacon`, `데이터 서버`(UI-5.1). 내부 값은 기존 문자열(`farm`, `jeju-weather`, `beacon`, `data-server`)을 유지한다.

### 7.2 `FarmGeographyPanel.tsx`
- 삭제: `BeaconDashboard` import, 645행의 `farm-beacon-dashboard-section` 블록 전체, `beaconDashboardSectionRef`, 자체 `/dashboard/beacons` 폴링 `useEffect`(171~186행), `beacons`·`beaconPlacementNodeId`·`pickedBeaconLocation`·`selectedMapBeaconId` 상태와 관련 콜백, `view`·`onViewChange`·`onOpenData` props.
- 농장 상태를 Provider로: `farms`·`selectedFarmId`·`setSelectedFarmId`·`loadFarms`를 `useBeaconFleet()`의 `farms`·`farmId`·`setFarmId`·`reloadFarms`로 바꾼다. 농장 생성·수정·경계 저장 뒤에 부르던 `loadFarms()`는 `reloadFarms()`로. 새 농장 만들기(`isCreatingFarm`) 중 선택 해제는 `setFarmId(null)`.
- `SavedFarmMap` props 연결:
  - `beacons` ← `nodes.map(n => ({ node_id, label, location: n.metadata?.location }))`
  - `placementNodeId` ← `placement?.nodeId ?? null`
  - `onBeaconLocationPicked(nodeId, point)` → `completePlacement(nodeId, point)`
  - `onCancelPlacement` → `cancelPlacement()`
  - `onSelectBeacon(nodeId)` → `openData(nodeId)` (기존 동작: 마커 → 데이터 서버)
- `placement`가 null이 아니게 되면 저장 지도 영역으로 `scrollIntoView({block:"center"})`(기존 `beginBeaconPlacement`의 스크롤을 `useEffect`로 옮김).
- 그 밖의 지도·경계·경로·타일 기능은 바꾸지 않는다. 회귀 확인은 13절 R1~R4.

---

## 8. Beacon 탭 컴포넌트

### 8.1 `ContextBar` (두 탭 공통, UI-5.2)
- 농장 select(`farms`, 비어 있으면 "농장을 먼저 등록하세요" + 농장 현황 탭 버튼).
- 수신 서버 알약: `reachable` true "수신 서버 정상"(맥박 점) / false "수신 서버 연결 불가"(danger) / null "확인 중". 클릭 → `SystemPopover`.
- 동기화 문구: `useNow(true, 5000)` 기준 `lastSyncAt` 상대 시간, 클릭 → `refreshNodes()`.
- `reachable===false`면 바 아래에 한 줄 배너: "Beacon 서버에 연결할 수 없습니다. 저장된 정보만 표시합니다." (닫기 없음, 복구되면 사라짐).

### 8.2 `SystemPopover` (UI-6.8)
열릴 때 `listUsb()`. 포트별 `리셋 후 확인`: 기존 `BeaconDashboard.resetUsbPort` 로직을 옮긴다(리셋 → 1.8 s 간격 목록 조회, 최대 45 s, 이전보다 `last_seen`이 0.5 s 이상 커진 노드가 있으면 확인). 결과는 토스트. 리셋 중에는 다른 포트 버튼 비활성.

### 8.3 `BeaconWorkspace`
상태: `filter: FleetFilter`(sessionStorage 보존), `query: string`. 렌더: `FleetHero` → `.bx-sec-head`(제목 + 검색) → `DeviceGrid` → `DeviceDialog`(openDeviceId) → `AddBeaconDialog`(addDraft).
농장이 없으면 전체 대신 `EmptyState`("농장을 먼저 등록하세요", 버튼 → 농장 현황 탭).

### 8.4 `FleetHero` (UI-6.1)
입력: `nodes`. 계산: 상태 키별 개수(`health().key`), `max(last_seen)`, `Σ pending_commands`. 상태 버튼 4개(`전체`·`정상`·`주의`·`오프라인`)는 `aria-pressed` 토글 필터. `장치 추가` → `openAdd()`(농장 없으면 비활성).

### 8.5 `DeviceGrid` / `DeviceCard` (UI-6.3)
- 필터: `filter==="all" || health(n).key===filter`, 검색: `label + 위치 문자열 + node_id` 소문자 부분 일치(120 ms 디바운스).
- 정렬: offline(0) → warn(1) → ok(2) → idle(3), 같으면 `label.localeCompare(…, "ko")`.
- 카드 값: `latest_readings` 앞 2개, `value1(value)` + `unitShort(unit)` + `metricLabel(sensor_type, display_name)`. 값이 없으면 `—`와 "수집 대기".
- 바닥: `Battery`, `relTime(now − last_seen)`, `pending_commands>0`이면 `⏱ 대기 n`.
- `highlightId===node_id`면 2 s 동안 주황 링(`box-shadow: 0 0 0 2px var(--orange)`) + `scrollIntoView({block:"nearest"})`.
- 필터·검색이 없을 때 마지막에 `.bx-card-add`.
- 첫 로드(`lastSyncAt===null`)에는 스켈레톤 카드 3장.
- 카드 `aria-label`: "`${label}`, `${health.label}`, 상세 열기".

### 8.6 `DeviceDialog` (UI-6.4)
- `Dialog size="lg"`. 데이터: `node`(Provider 목록에서 id로), `useBeaconDetail(id, {intervalMs: 7000})`, 에너지는 `usePolling(getEnergy, {intervalMs: 60000, enabled: open})`.
- 상세 7 s 폴링 보정: `now ≥ next_expected_at − 3`이면 다음 1회를 2 s 뒤로 당긴다(체크인 직후 결과 반영).
- 머리: 아이콘, 이름, `ID 복사`(클립보드 + 토스트 "ID를 복사했습니다"), 위치(`site · zone · row`), 상태 배지, 닫기.
- 작업 줄:

| UI | 호출 | 비활성 조건 |
|---|---|---|
| `센서 읽기` | `command(id, {type:"sensor"})` | `!registered || state!=="ATTACHED"` |
| `촬영` | `command(id, {type:"image", fs:"VGA", q:12, warm:500})` | 같음 |
| `촬영 ▾` → QVGA/VGA/SVGA/XGA | `fs`만 바꿔 같은 호출 | 같음 |
| `데이터` | `openData(id)` | — |
| `⋯ → 1분간 즉시 응답` | `action(id,"session",{hold_s:60})` | 같음 |
| `⋯ → 10분간 자주 확인` | `action(id,"watch",{minutes:10})` | 같음 |
| `⋯ → 설정 편집` | `openEdit(id)` | — |
| `⋯ → 절전` / `연결 해제` | `ConfirmDialog` → `action(id,"hibernate"|"detach",{})` | `!registered` |
- 오프라인이어도 명령은 허용(UI-6.5). 성공 후: 응답의 `command_id`로 낙관적 `queued` 항목을 `ActivityTab`에 즉시 추가(상세에 같은 id가 오면 대체), 하위 탭을 `작업`으로, 토스트 "`${종류} #${id} 요청됨`" + "약 `${countdown}` 후 다음 체크인 때 실행됩니다"(오프라인이면 "장치가 다시 연결되면 전달됩니다"), `refreshNodes()`.
- `DeliveryBar`: `useNow(open)` 구독, `deliveryInfo()`로 그린다. 매초 리렌더되는 것은 이 컴포넌트뿐이다.
- 하위 탭 `상태 · 작업(n) · 설정`(`role="tablist"`).

### 8.7 `StatusTab` / `ActivityTab` / `SettingsTab`
- `StatusTab`: 2×2 스탯. 원천은 `detail.checkins`(48건): 배터리(`vbat_mv` 스파크라인, 의미색) · 신호(`rssi` 스파크라인 + `SignalBars`, 채널·IP) · Wi-Fi 접속(`wifi_ms` 중앙값, `fast` 비율) · 깨어 있는 시간(`prev_awake_ms` 중앙값, "상한 25초"). 체크인 0건이면 노드 목록의 `last_*` 값으로 숫자만, 스파크라인 생략. 센서 행(`detail.sensors`), 행 클릭 → `openData(id, sensor_id)`. 전력 카드: `estimated_mAh_day`, `estimated_days_remaining` → "만충 기준 수명", 가정값 안내 1줄. 에너지 실패 시 카드에 "자료 없음".
- `ActivityTab`: `detail.commands` + 낙관 항목, 최신순. 3단 스텝: queued(1칸) / dispatched(2칸). 소요 = `done_at − created_at`.
- `SettingsTab`: 정의 목록(표시 이름, 위치 + 좌표 6자리, 수집 주기 `intervalLabel`, 수집 데이터, 펌웨어, 보고한 센서 `model · 0x주소`) + `설정 편집` + 위험 구역 2줄.

### 8.8 `ConfirmDialog`
`{title, body, confirmLabel, tone: "danger", requireText?: string, onConfirm: () => Promise<void>}`. `requireText`가 있으면 입력란과 정확히 일치할 때만 확인 버튼 활성. 절전은 `requireText = node.label`, 연결 해제는 없음. 실행 중 버튼 스피너, 실패 시 다이얼로그 안에 오류 문구.

### 8.9 `AddBeaconDialog` (UI-6.6)
`addDraft` 기반. `mode==="edit"`이면 스테퍼 숨김, 2↔3단계만.

| 단계 | 내용 | `다음` 활성 조건 |
|---|---|---|
| 1 장치 선택 | `discoverable` 라디오 목록(ID 모노, `last_ip`, `relTime(last_seen)` 체크인, `now−first_seen<600` → "새로 발견" 배지). 0개면 안내 + `다시 찾기`(`refreshNodes`) | 하나 선택 |
| 2 이름·수집 | 표시 이름(필수, 1~64자) · 주기 프리셋 60/300/900/3600 + `직접 입력`(정수 60~14400) · 각 프리셋 아래 `daysLabel(estimateDays(T, image))` · 수집 데이터 체크(최소 1개) · 정보 띠 "예상 배터리 수명 … · 목표 30일 충족/미달" | 이름 유효 && 주기 유효 && 데이터 ≥1 |
| 3 설치 위치 | 좌표가 있으면 `위도, 경도`(6자리) + `지도에서 위치 변경`, 없으면 `지도에서 위치 선택`. `hasBoundary=false`면 버튼 비활성 + "먼저 농장 경계를 등록하세요" + `농장 지도로 이동` | 위도·경도 숫자 |

저장(`연결하고 저장` / 편집은 `저장`):
```ts
api.configure(nodeId, {
  farm_id: farmId,
  metadata: { ...draft.metadata, label: draft.label.trim(), location: { ...draft.location, site: draft.location.site ?? farm.name } },
  interval_s: draft.intervalS,
  requested_data: [draft.sensor && "sensor", draft.image && "image"].filter(Boolean),
  attach: true,
})
```
성공 → `closeAdd()`, `refreshNodes()`, `highlightId = nodeId`, 토스트 "장치를 연결했습니다"(편집: "설정을 저장했습니다") + "다음 체크인 때 장치에 전달됩니다". 실패 → 다이얼로그 안 오류 문구(입력값 유지). 422 메시지는 그대로 보여 준다.
`metadata`에 비밀정보 성격의 키를 넣지 않는다(서버 `main._reject_beacon_secrets`의 금지 키 목록에 걸리면 422).

---

## 9. 데이터 서버 탭 컴포넌트

### 9.1 `DataWorkspace`
상태: `nodeId`(`dataSelection?.nodeId` → sessionStorage → `nodes[0]`), `kind: DeleteKind`(기본 sensor), `metricId`(`dataSelection?.sensorId` → 첫 센서), `selectMode: boolean`, `selection = useSelection()`, `deleteDialog: null | {mode:"picked"} | {mode:"range"}`, `lightboxAssetId`.
- 상세: `useBeaconDetail(nodeId, {intervalMs: 15000, paused: selectMode || pendingDeletes.hasPending(nodeId)})`.
- 장치·종류를 바꾸면 `selection.clear()`, 펼친 JSON 행 닫기. `selectMode`는 유지.
- 모든 목록은 렌더 직전에 `pendingDeletes.isHidden(nodeId, kind, item)`으로 거른다.
- 레이아웃: `.bx-explorer` = `SourceRail` | (`.bx-ex-head`: 브레드크럼, `KindSegment`, 저장 위치 칩, `선택` 토글, `CSV`, `⋯`) + 본문 + `SelectionBar`.
- 브레드크럼: `${farm.name} › beacons › ${label} › ${sensors|images|checkins|commands}`.
- 저장 위치 칩: sensor `SQLite · sensor_readings`, image `SSD · raw/beacons/${nodeId}/`, checkin `SQLite · beacon_node_checkins`, command `SQLite · beacon_commands`.
- `⋯` 메뉴: `항목 선택해서 삭제`(selectMode=true), `기간으로 삭제…`(danger, `deleteDialog={mode:"range"}`).

### 9.2 `SourceRail`
검색 + `BEACONS n` + 장치 행(상태 점, 이름, `relTime(last_seen)`). 선택 행 `aria-current="true"`(녹색 채움). 하단 저장 방식 범례 2줄. 샘플의 장치별 건수는 목록 응답에 없으므로 **표시하지 않는다**.

### 9.3 `KindSegment`
`센서 Σreading_count` · `이미지 image_count` · `체크인 checkin_count` · `작업 commands.length`(숨김 처리분을 뺀 값). 숫자는 `toLocaleString("ko-KR")`.

### 9.4 `SensorView` + `LineChart`
- 메트릭 카드(센서별): `metricLabel · 모델`(모델은 `device.metadata.sensor_type` 대문자), 최신값, "1시간 전 대비 ±x"(최신 시각 − 3600 s 이하인 가장 가까운 측정과 비교, 없으면 생략), "`reading_count`건 저장". 선택 카드 `aria-pressed`.
- 차트: 숨김 제외 `readings`(최대 96) → `LineChart`.
- 표: 최신순, 열 `[선택] 수신 시각 · 값 · 단위 · 품질`. 품질 `reported`/`ok`/null → "정상"(ok 배지), 그 외 → "확인 필요"(warn). 96건 아래에 "최근 96건 표시 · 전체 `reading_count`건 — 오래된 기록은 기간으로 삭제할 수 있습니다".

`LineChart` props: `{ points: {t: number; v: number; flag?: boolean}[]; unit: string; height?: number }`.
- `ResizeObserver`로 폭을 재고 viewBox 폭 = 실제 픽셀 폭(글자 왜곡 금지, `preserveAspectRatio` 기본값).
- 여백 L36 R8 T10 B24. y 눈금: `step = nice((max−min)/4)`(1·2·5×10ⁿ), `floor(min/step)·step ~ ceil(max/step)·step`. x 라벨: 폭 < 480 px이면 32점 간격, 아니면 16점.
- 선 `--orange` 2 px, 면 주황 22%→0% 그라데이션, `flag` 점은 `--warn` 원.
- 호버/포커스: 세로 점선 + 점(녹색 테두리) + 툴팁 `값 단위 · 날짜 시각`. `tabIndex=0`, ←/→/Home/End로 이동, 툴팁 내용을 `aria-live="polite"` 영역에도 넣는다.
- 점 0개면 `EmptyState`.

### 9.5 `ImageGallery` / `Lightbox`
- `dayLabel`로 묶음, 그룹 머리 `[그룹 체크박스] 11월 20일 (금) · 8장 · 397 KB`.
- 썸네일 `<img src="/api/backend/dashboard/assets/{id}/preview" loading="lazy" decoding="async">`를 4:3 고정 박스에(`object-fit: cover`). 이미지 오류 시 회색 박스 + "파일 없음".
- 선택 모드: 썸네일 클릭 = 선택 토글(라이트박스 열지 않음), 체크박스 왼쪽 위.
- 아래에 "최근 30장 표시 · 전체 `image_count`장".
- `Lightbox`(`Dialog size="lg"`): 원본 이미지, 파일명 `${node}/${cmd}.jpg`, 시각·해상도·크기, ←/→ 이전/다음(현재 목록 기준), `원본 내려받기`(`<a href=preview download>`), `삭제`(danger-ghost → `selection`을 그 1장으로 두고 `deleteDialog={mode:"picked"}`).

### 9.6 `CheckinTable` / `CommandTable`
- 체크인 열: `[선택] 수신 시각 · 부팅 · 전압(3자리, 의미색) · RSSI · Wi-Fi 접속(ms + 빠름/전체 스캔) · 활성 시간 · 직전 결과(ok=ok, wifi_fail·http_fail=warn, awake_cap·rtc_fail=danger) · 다음 주기`. 최신 1행의 체크박스는 비활성 + 툴팁 "가장 최근 체크인은 다음 수신 때 다시 기록되어 삭제할 수 없습니다".
- 작업 열: `[선택] ID · 종류 · 상태 · 요청 · 완료 · 소요 · JSON`. `queued`·`dispatched` 행 체크박스 비활성 + 툴팁 "진행 중인 작업은 삭제할 수 없습니다". JSON 펼침은 `{params, result, reason}` 들여쓰기 2.
- 표 공통: `.bx-table-scroll`(최대 높이 520 px), 헤더 sticky, `<th scope="col">`, 머리 체크박스는 **보이는 행 중 선택 가능한 행**만 대상(일부면 indeterminate).

### 9.7 `SelectionBar`
`selectMode`일 때만, 본문 아래 sticky. `${n}개 선택됨` · `선택 해제`(n>0) · `완료`(selectMode=false) · `삭제`(danger, n=0이면 비활성 → `deleteDialog={mode:"picked"}`). `role="region" aria-label="선택 작업"`, 개수는 `aria-live="polite"`.

### 9.8 `DeleteDialog` (UI-7.7)

**picked 모드**
- 대상: `selection.ids`. 시각 범위는 현재 메모리의 항목으로 계산. 요청: `{kind, ids:[...]}`.
- 이미지는 크기 합계도 표시.

**range 모드**
- 대상(센서만): `현재 센서만`(`sensor_ids=[metricId]`) / `이 장치의 모든 센서`(생략).
- 기간: 3·7·30일보다 오래된 기록, 전체. `before = new Date(Date.now() − d·86400000).toISOString()`.
- 열 때와 대상을 바꿀 때 네 선택지의 `dry_run`을 `Promise.all`로 호출해 각 줄 오른쪽에 `matched − skipped_*` 건수를 표시(응답 전 스피너, 실패 시 "—"). 선택을 바꿀 때는 다시 부르지 않는다(이미 받은 값 사용). 250 ms 디바운스.
- `전체` 선택 시 이름 입력란, `confirm_label`로 보냄.

**공통**
- 요약 표(장치, 종류, 삭제 대상 수(+용량), 기간, 저장 위치) + 경고 문구(UI-7.7 원문, 이미지·작업 추가 문장 포함) + 바닥 "삭제 후 6초 동안 실행 취소할 수 있습니다".
- 버튼 문구 `${count}${단위} 삭제`(단위: 센서·체크인·작업 "건", 이미지 "장"). 0건이면 비활성. 초기 포커스는 `취소`.
- 확인 → `pendingDeletes.schedule({...})`, `selection.clear()`, 다이얼로그 닫기. 라이트박스가 열려 있으면 함께 닫는다.

### 9.9 CSV
현재 보기의 **숨김 제외 행**만. 센서: 수신 시각(ISO)·값·단위·품질. 체크인: 표의 모든 열 + `checkin_id`. 작업: ID·종류·상태·요청·완료·소요·사유. 이미지 보기에서는 버튼 숨김.

---

## 10. 이벤트 → API 표

| 화면 동작 | 메서드·경로 | 본문 | 성공 후 |
|---|---|---|---|
| 노드 목록(Provider) | GET `/dashboard/beacons` | — | `nodes` 갱신 |
| 농장 목록 | GET `/api/v1/farms` | — | `farms` 갱신 |
| 상세(팝업·데이터 서버) | GET `/dashboard/beacons/{id}` | — | `detail` |
| 에너지 | GET `/dashboard/beacons/{id}/energy` | — | 전력 카드 |
| 센서 읽기 / 촬영 | POST `/dashboard/beacons/{id}/commands` | `{type, fs?, q?, warm?}` | 낙관 항목 + 토스트 |
| 즉시 응답 / 자주 확인 | POST `/dashboard/beacons/{id}/actions/session|watch` | `{hold_s:60}` / `{minutes:10}` | 토스트, `refreshNodes` |
| 절전 / 연결 해제 | POST `/dashboard/beacons/{id}/actions/hibernate|detach` | `{}` | 팝업 닫기, `refreshNodes` |
| 장치 추가·편집 | PUT `/dashboard/beacons/{id}/configure` | 8.9 | 강조, 토스트 |
| USB 목록 / 리셋 | GET `/dashboard/beacons/usb`, POST `/dashboard/beacons/usb/{port}/reset` | `{}` | 8.2 |
| 미리보기 | GET `/dashboard/assets/{asset_id}/preview` | — | `<img>` |
| 기간 삭제 건수 | POST `/dashboard/beacons/{id}/data/delete` | `{…, dry_run:true}` | 다이얼로그 건수 |
| 삭제 확정(6 s 후) | POST `/dashboard/beacons/{id}/data/delete` | 9.8 | 상세 다시 불러오기 |

모든 경로 앞에 프론트에서는 `/api/backend`가 붙는다.

---

## 11. 절차

각 단계 끝에 `git add -A && git commit -m "beacon-ui: <단계> <요약>"`. 로그는 `docs/_logs/`에 저장한다(커밋에 포함).

### D0 사전 점검 (게이트)
각각 따로 실행하고 결과를 보고서 1절에 붙인다.
```bash
cd ~/mirgam_mcp && pwd
git status --short | head -50           # 사람이 배치한 docs/ 세 파일 외의 변경이 있으면 중단하고 보고
git rev-parse --short HEAD               # 9931d45 또는 그 이후. 다르면 차이(git log 9931d45..HEAD --oneline)를 보고하고 진행
test -f docs/SPEC_UI_BEACON.md && test -f docs/design/beacon-dashboard-sample.html && test -f docs/SPEC_DEV_BEACON_UI.md && echo DOCS_OK
git switch -c ui/beacon-v1.1
git add docs/SPEC_UI_BEACON.md docs/SPEC_DEV_BEACON_UI.md docs/design/beacon-dashboard-sample.html && git commit -m "beacon-ui: D0 add specs and design sample"
python3 --version; node --version || echo NODE_MISSING; docker --version; docker compose version
timeout 60 docker compose -f infra/compose.yaml ps
python3 -c "import json;print(json.load(open('services/beacon/config.json')).get('energy'))"   # 5.7 상수 대조
grep -n "beacon_node_checkins\|beacon_commands\|camera_assets" services/api/app/services/beacon_store.py | head
mkdir -p docs/_logs
```
- `DOCS_OK`가 안 나오면 중단(사람이 세 문서를 배치해야 한다).
- `NODE_MISSING`이면 웹 검사는 컨테이너로 한다:
  `timeout 900 docker run --rm -v "$PWD/apps/web:/app" -w /app node:22-alpine sh -c "npm install --no-audit --no-fund && npm run lint"`
  (`node_modules`가 `apps/web`에 생기므로 `.gitignore`에 있는지 확인. 없으면 중단하고 보고.)

### D1 백엔드 (4절)
1. 4.1~4.5 구현.
2. 4.6 테스트 작성, 컨테이너 실행 → 전부 통과.
3. 기존 API가 뜨는지: `timeout 900 docker compose -f infra/compose.yaml build api` 종료 코드 0.
게이트: 테스트 로그 `OK`. 실패는 소스만 고쳐 최대 3회 재시도.

### D2 프론트 기반 (5절)
`tokens.css`, `beacon.css`(이 단계에서는 `.bx-` 규칙만 추가, 기존 CSS는 건드리지 않음), `types.ts`~`csv.ts`, 훅, `ui/*`. `Icon.tsx`의 path는 아래처럼 추출:
```bash
python3 - <<'PY'
import re,json
s=open('docs/design/beacon-dashboard-sample.html',encoding='utf-8').read()
syms=dict(re.findall(r'<symbol id="i-([a-z]+)" viewBox="0 0 24 24">(.*?)</symbol>',s,re.S))
open('docs/_logs/icons.json','w').write(json.dumps(syms,ensure_ascii=False,indent=1))
print(len(syms),sorted(syms))
PY
```
게이트: `npm run lint` 종료 코드 0.

### D3 Provider와 통합 (6, 7절)
`BeaconFleetProvider`, `DashboardTabs`, `ContextBar`, `SystemPopover`, ChatApp·FarmGeographyPanel 수정. 이 단계에서 Beacon·데이터 서버 탭에는 임시로 `EmptyState("준비 중")`를 둔다.
게이트: lint 통과 + 13절 R1~R4(농장 지도 회귀)를 사람이 확인.

### D4 Beacon 탭 (8절)
게이트: lint, 13절 B1~B10.

### D5 데이터 서버 읽기 (9.1~9.6, 9.9)
게이트: lint, D1~D6.

### D6 삭제 (9.7, 9.8, 5.9 `usePendingDeletes`)
게이트: lint, X1~X9. 실제 삭제(X1·X2·X4·X6)는 사람이 브라우저에서 수행하고 Codex는 전후 행 수를 읽기 전용 쿼리로 확인한다:
```bash
timeout 30 docker compose -f infra/compose.yaml exec -T api python -c "import sqlite3;d=sqlite3.connect('file:/workspace/storage/state/mirgam.db?mode=ro',uri=True);print([d.execute(f'select count(*) from {t}').fetchone()[0] for t in ('sensor_readings','camera_assets','beacon_node_checkins','beacon_commands','beacon_data_deletions')])"
```

### D7 정리 (UI-11)
1. 기존 3개 컴포넌트 삭제. `grep -rn "BeaconDashboard\|DataServerDashboard\|BeaconDataExplorer" apps/web` 결과 0.
2. `dashboard.css`에서 셀렉터가 `.beacon-`, `.data-server-`, `.farm-beacon-dashboard-section`, `.beacon-farm-picker`, `.dashboard-folder-tabs`로 시작하는 규칙 삭제. 다른 셀렉터와 묶인 규칙(`a, .beacon-x {…}`)은 해당 셀렉터만 빼고 규칙은 남긴다. 전후 측정:
```bash
wc -c apps/web/app/dashboard.css
grep -o "\.beacon-[a-z-]*\|\.data-server-[a-z-]*\|\.dashboard-folder-tabs" apps/web/app/dashboard.css | wc -l
```
3. `docs/beacon-dashboard-ui-spec.md` 삭제.
게이트: lint + `npm run build`(또는 `docker compose build web`) 종료 코드 0, 농장 현황·제주 날씨 화면 전후 스크린샷(사람).

### D8 검증과 보고
14절 기준 판정, 16절 보고서 작성, 커밋. push는 사람이 한다.

---

## 12. 성능·품질 규칙

- `/dashboard/beacons` 호출 지점은 Provider 하나. `grep -rn "dashboard/beacons\"" apps/web/components | grep -v beacon/api.ts` 결과 0.
- 매초 리렌더: `DeliveryBar`만. 카드 그리드·표는 폴링 응답이 바뀔 때만 리렌더(`React.memo` + 노드 객체 비교는 `node_id`·`last_seen`·`pending_commands`·`latest_readings[0].recorded_at`).
- 큰 목록은 가상화하지 않는다(최대 표시 96·48·100·30행).
- 이미지 `loading="lazy"`, 차트 `ResizeObserver`는 120 ms 디바운스.
- `any` 금지(`unknown` + 좁히기). `// @ts-ignore` 금지.
- 사용자에게 보이는 문구는 UI-8 규칙(존댓말 평서문). 원시 상태값(`ATTACHED`, `queued`)을 화면에 그대로 보이지 않는다(체크인 표의 `boot`·`prev_result`는 진단용 모노 표기로 예외).

---

## 13. 검증 시나리오

회귀(R) — D3 이후:
R1 농장 현황 탭에서 농장 생성 → 경계 저장 → 저장 지도에 표시. R2 경로 추가·삭제. R3 지도 타일 준비 버튼 동작. R4 농장 현황에서 농장을 바꾸면 Beacon·데이터 서버 탭의 농장도 바뀜(그 반대도).

Beacon(B):
B1 요약 배너 숫자 = 카드 수, 상태 버튼으로 거르기. B2 카드 클릭 → 팝업, 카운트다운이 매초 줄어듦, Esc로 닫으면 그 카드에 포커스. B3 센서 읽기 → 토스트 + 작업 탭 대기 항목 → 다음 체크인 후 완료. B4 촬영 ▾ SVGA → 네트워크 탭 요청 본문 `fs:"SVGA"`. B5 오프라인 장치에 센서 읽기 → 안내 문구가 다름. B6 `⋯ → 10분간 자주 확인` → 다음 체크인 후 배지 "자주 확인 중". B7 장치 추가 3단계(지도 왕복 포함), 저장 후 카드 강조. B8 절전 확인에서 이름 불일치 시 버튼 비활성. B9 Beacon 컨테이너 중지(사람) → 알약 danger, 한 줄 배너, 카드는 남음. B10 뷰포트 640 px 이하에서 팝업이 아래 시트.

데이터 서버(D):
D1 팝업 `데이터` → 팝업 닫히고 같은 장치·센서. D2 차트 호버와 ←/→ 툴팁. D3 라이트박스 이전/다음/Esc. D4 체크인 결과 배지 색. D5 작업 JSON 펼침. D6 CSV 행 수 = 표시 행 수, 엑셀에서 한글 정상.

삭제(X):
X1 측정 3건 선택 → 삭제 → 즉시 사라짐 → 6 s 후 POST 1회 → DB −3. X2 같은 흐름에서 실행 취소 → POST 0회, 행 복귀. X3 머리 체크박스(보이는 행만, indeterminate). X4 이미지 날짜 그룹 삭제 → 행·사본 파일 삭제, Beacon 원본은 그대로(`ls /mnt/nvme/beacon/images/<node>` 사람 확인). X5 기간 삭제: dry-run 건수 = 확정 응답 `deleted`. X6 전체 삭제: 이름 불일치 비활성, 일치 시 실행. X7 진행 중 작업·최신 체크인 체크박스 비활성. X8 삭제 실패(사람: 확인 직후 6 s 안에 `docker compose stop api`, 확인 뒤 `start`) → 행 복귀 + 오류 토스트 + `다시 시도`로 재전송. X9 삭제 대기 중 탭 이동 → 6 s 후에도 확정됨, 탭 닫기 → 확정 안 됨.

---

## 14. 수락 기준

| ID | 기준 | 확인 |
|---|---|---|
| AC1 | `npm run lint`, `npm run build` 종료 코드 0 | Codex |
| AC2 | API 단위 테스트 전부 통과(4.6의 14개 이상) | Codex |
| AC3 | `package.json`·`pyproject.toml` 변경 없음 | Codex(`git diff --stat`) |
| AC4 | `/dashboard/beacons` 호출 지점 1곳, 탭 보일 때 10 s당 최대 1회, 문서 숨김 시 0회 | Codex(grep) + 사람(네트워크 탭) |
| AC5 | 농장 선택 UI가 대시보드에 1개(농장 현황의 지도 패널 select 포함 시 둘이 같은 값) | 사람 |
| AC6 | Beacon 카드에 RSSI·다음 체크인·IP·펌웨어·전력 없음, 팝업에는 모두 있음 | 사람 |
| AC7 | 주황 채움 버튼: Beacon 기본 화면 1개, 상세 팝업 1개 | 사람 |
| AC8 | `window.confirm`·`alert` 사용 0 | Codex(grep) |
| AC9 | 매초 리렌더는 `DeliveryBar`뿐(React DevTools Profiler 10 s 기록) | 사람 |
| AC10 | 화면 어디에도 "잔여"라는 단어 없음, 전력은 "만충 기준" | Codex(grep) |
| AC11 | 대시보드 폭 600 / 760 / 1020 / 1400 px에서 겹침·가로 스크롤 없음 | 사람(스크린샷 4장) |
| AC12 | 키보드만으로 UI-10의 두 경로 완료, 11 px 미만 글자 0 | 사람 |
| AC13 | `dashboard.css`의 `.beacon-`·`.data-server-`·`.dashboard-folder-tabs` 0, 파일 크기 40% 이상 감소 | Codex |
| AC14 | 실행 취소 시 삭제 POST 0회, 확정 시 1회 | 사람(네트워크 탭) |
| AC15 | 진행 중 작업·최신 체크인은 UI에서 선택 불가, API로 보내도 건너뜀 | Codex(테스트) + 사람 |
| AC16 | 이미지 삭제 시 행·사본 파일 함께 삭제, 원본 유지 | 사람 |
| AC17 | 샘플 HTML과 같은 폭에서 나란히 비교한 스크린샷(Beacon 기본·팝업·데이터 서버 센서·삭제 다이얼로그) | 사람 판정 |

---

## 15. 실패 처리

- 단계별 재시도는 명시한 횟수만(소스 수정 후 최대 3회).
- 중단할 때 보고: 실패한 단계, 정확한 명령, 종료 코드, 로그 마지막 30줄, 원인 가설(**가설**이라고 표시), 사람이 할 조치.
- 중단 시점까지의 산출물·로그·커밋은 지우지 않는다(`git reset --hard`, `git clean` 금지).
- 이 문서의 계약(경로, 응답 형식, 파일 이름)을 바꿔야 할 것 같으면 바꾸지 말고 멈춰서 제안만 보고한다.

---

## 16. 보고서 (`docs/report_ui_beacon.md`)

1. 환경: 커밋 범위, Node·Python·Docker 버전, 웹 검사 방식(호스트/컨테이너), `energy` 상수 대조 결과.
2. 단계표: 단계 · 담당 · 명령 · 종료 코드 · 결과 한 줄 · 커밋 해시.
3. 백엔드: 테스트 결과 요약, 새 엔드포인트 예시 요청/응답(dry_run).
4. 프론트: 새 파일 목록과 줄 수, 삭제한 파일, `dashboard.css` 전후 크기·셀렉터 수.
5. 시나리오 결과: R·B·D·X 각각 통과/실패/미실시(사람 확인 대기 포함).
6. 수락 기준 표(AC1~AC17) 판정.
7. 알려진 문제와 가정: 이미지 미리보기 소유권 미확인(기존), 측정 삭제 후에도 `beacon_commands.result_json`에 원값이 남음, 목록 API의 `farm_id` 무시, 기타 발견 사항. 추론은 "추정"으로 구분.
