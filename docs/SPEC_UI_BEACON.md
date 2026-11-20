# Beacon 관리 · 데이터 서버 UI 개편 명세서 (SPEC_UI_BEACON v1.1)

작업자: Codex(구현) + 사람(시각 검수). 대상 저장소 `yangjunwon1309/mirgam_mcp` `main`. 이 문서가 이번 UI 개편의 유일한 요구사항이며 `docs/beacon-dashboard-ui-spec.md`를 대체한다. 시각 기준은 함께 전달한 `beacon-dashboard-sample.html`이다(같은 토큰·컴포넌트 이름 사용). 명세와 현실이 어긋나면 추측하지 말고 13절 절차대로 멈추고 보고한다.

**v1.1 변경(2026-11-20)**: ① 색을 원래 브랜드(짙은 녹색·녹색·주황·크림)에 가깝게 재조정(4.1). ② 기본 화면을 요약 배너 + 장치 카드로 단순화하고, 신호 세기·다음 체크인 등 진단 정보는 카드를 누르면 뜨는 상세 팝업으로 이동(6.1~6.4). ③ 데이터 서버에 골라서 삭제·기간으로 삭제·실행 취소 추가, 이를 위한 백엔드 API 1개 추가(7.7, 7.8).

---

## 0. 요약

| 무엇 | 지금 | 바꾼 뒤 |
|---|---|---|
| 정보 구조 | Beacon 관리가 `FarmGeographyPanel` 안의 숨은 섹션이고, 농장 선택이 두 군데(Beacon·데이터 서버)에 따로 있다 | 두 탭이 하나의 **컨텍스트 바**(농장 · 수신 서버 상태 · 동기화 시각)를 공유한다 |
| 첫 화면 | 서버/USB 카드가 맨 위를 차지하고, 장치는 카드 목록, 상세는 같은 무게의 버튼 7개 | **요약 배너(상태 필터 겸용) → 장치 카드(센서값·배터리·마지막 체크인만)**. 진단 정보는 카드를 누르면 뜨는 **상세 팝업**으로. 서버/USB는 상태 알약 뒤 팝오버로 |
| 핵심 개념 | "명령이 다음 체크인 때 전달된다"는 사실이 알림 문장으로만 나온다 | 상세 팝업 상단 **전달 타임라인**(체크인 주기 진행 바 + 카운트다운) |
| 작업 피드백 | 한 개의 `beacon-notice` 배너가 성공·오류·안내를 모두 처리 | 토스트(일시) + 작업 탭 타임라인(지속, `queued → dispatched → done`) |
| 데이터 서버 | SQLite 행을 `.csv`/`.json` 가짜 파일 트리로 표현, 센서는 표만, 체크인/작업은 JSON 원문 | 소스 레일 + 세그먼트(센서·이미지·체크인·작업) + 차트·갤러리·정형 테이블 |
| 데이터 삭제 | 기능 없음(API도 없음) | 선택 모드 + 기간 삭제 + 확인 다이얼로그 + 6초 실행 취소, `POST …/data/delete`(dry-run 지원) |
| 스타일 | `dashboard.css` 89 KB, Beacon 관련 셀렉터 306개를 545번 정의(같은 셀렉터 최대 7회 재정의), 고유 색 624개, 글자 크기 21종(8~40 px), CSS 변수 0개 | 토큰 파일 1개 + Beacon 전용 CSS 1개. 글자 크기 7단계, 최소 11 px |

기술 스택은 그대로다: Next.js 15(App Router) · React 19 · TypeScript · 전역 일반 CSS · `react-markdown` 외 런타임 의존성 없음. **새 npm 패키지를 추가하지 않는다**(차트·아이콘·팝오버 모두 직접 구현). 백엔드는 P0에서 **두 가지만** 바꾼다: 삭제 API 1개(7.8)와 목록 응답에 센서 최신값 추가(9.2).

---

## 1. 범위

포함: `ChatApp`의 대시보드 헤더·탭(Beacon·데이터 서버 탭에 한해), `BeaconDashboard`, `DataServerDashboard`, `BeaconDataExplorer`, 이 셋이 쓰는 CSS, 그리고 `services/api`의 삭제 API·목록 응답 보강(7.8, 9.2). `FarmGeographyPanel`은 Beacon 섹션을 떼어내고 지도 배치(placement) 연동만 남긴다.

제외: 채팅 패널, 농장 현황 탭의 센서·카메라 카드, 제주 날씨, 농장 지도 자체의 디자인, 로그인 화면, 백엔드 정책(4절 SPEC_NET). 다크 모드는 토큰 구조만 대비하고 구현하지 않는다.

---

## 2. 현황 진단 (코드 근거)

### 2.1 정보 구조
- `ChatApp.tsx`의 탭은 `farm | jeju-weather | data-server | beacon`인데, `beacon` 탭은 `FarmGeographyPanel`을 `view="beacon"`으로 렌더하고 그 안의 `.farm-beacon-dashboard-section`을 `hidden` 속성으로 토글한다. 그래서 **농장 현황 탭에서도 `BeaconDashboard`가 마운트된 채 보이지 않게 폴링한다**(2.6).
- 농장 선택이 `FarmGeographyPanel`의 `#beacon-farm` select와 `DataServerDashboard`의 select로 두 번 존재하고 서로 동기화되지 않는다.
- 페이지 헤더 `h1 "Beacon 관리"` 바로 아래에 `h3 "Beacon 센서 관리"` + kicker + 설명이 다시 나온다(제목 중복).

### 2.2 시각 계층
- 헤더 액션 3개(새로고침·선택 장치 설정·연결 가능한 Beacon)와 상세 액션 7개(데이터 서버 열기·센서 읽기·촬영·1분 응답 대기·10분간 자주 확인·절전·연결 해제)가 모두 같은 모양이다. 파괴적 작업(절전·연결 해제)이 주 작업과 나란히 있고, 절전 확인은 `window.confirm`이다.
- 화면 맨 위를 "ESP32 수신 서버 / USB 직렬 포트" 카드가 차지한다. 진단용 정보라 평소에는 필요 없다.
- 장치 카드에 작은 글씨 3줄(이름 / ID·위치·좌표 / 온라인·체크인 시각) + 오른쪽 `ATTACHED` 같은 원시 상태값.

### 2.3 데이터 표현
- 배터리·RSSI를 `"-55 dBm · 3.98 V"`처럼 한 칸에 문자열로 붙인다. 임계값(SPEC_NET 4절 3450/3300 mV) 색 구분이 없다.
- 체크인 기록(`beacon_node_checkins`, 최근 48건: `vbat_mv`, `rssi`, `wifi_ms`, `fast`, `prev_awake_ms`, `prev_result`, `next_given`)이 이미 API에 오는데, 추세로 쓰지 않고 데이터 서버에서 `JSON.stringify` 원문으로만 보여 준다.
- 센서 측정(최근 96건)은 표로만 나오고 차트가 없다.
- `/energy`의 `estimated_days_remaining`은 `usable_mah / 일 소모량`, 즉 **만충 기준 수명**이다(`beacon_server.py:351`). 현재 UI는 "추정 잔여 N일"로 표기해 의미가 틀린다.

### 2.4 상호작용·피드백
- 명령 요청 후 사용자에게 남는 것은 배너 문장 하나다. `pending_commands`, 명령 이력(`commands`)이 있는데 진행 상태를 보여 주지 않는다.
- 촬영은 항상 `VGA q12 warm500`으로 고정. API는 `fs`(QVGA~UXGA), `q`(4~40), `warm`(0~3000)을 받는다.
- 오프라인 장치는 센서·촬영 버튼이 비활성인데, 풀 방식에서는 대기열에 넣어 두면 다음 체크인에 전달되므로 막을 이유가 약하다(6.5에서 정책 정리).
- 모달에 포커스 가두기·Escape 닫기·포커스 복귀가 없다.

### 2.5 CSS 부채 (`apps/web/app/dashboard.css`, 89,304 B)
- Beacon/데이터 서버/폴더 탭 관련 셀렉터 306개를 545번 정의. `.beacon-modal` 7회, `.beacon-heading-actions` 6회 등 뒤에서 덮어쓰는 패치 누적.
- 광범위 덮어쓰기: `.beacon-dashboard button:not(:disabled):not(.beacon-device-card):not(.beacon-sensor-pills button)` 류. `!important` 11개.
- 고유 hex 색 624개, `font-size` 21종(8 px 15회, 9 px 44회), `border-radius` 19종, 미디어 쿼리 20개, CSS 사용자 정의 속성 0개.

### 2.6 폴링·성능
| 위치 | 엔드포인트 | 주기 | 문제 |
|---|---|---|---|
| `FarmGeographyPanel` | `/dashboard/beacons` | 10 s | 지도 마커용 |
| `BeaconDashboard` | `/dashboard/beacons` | 10 s | 위와 같은 요청 중복, 탭이 숨겨져도 계속 |
| `BeaconDashboard` | `/dashboard/beacons/{id}` | 7 s | 선택 장치 상세 |
| `DataServerDashboard` | `/dashboard/beacons` + `/api/v1/farms` | 15 s | |
| `BeaconDataExplorer` | `/dashboard/beacons/{id}` | 15 s | |

`GET /dashboard/beacons`는 매번 `update_node_snapshot → record_checkin_snapshot`으로 SQLite에 쓰기를 한다(`beacon_store.py`). 중복 폴링이 곧 중복 쓰기다. 문서가 숨겨져 있을 때(`document.hidden`)도 멈추지 않는다.

### 2.7 접근성
- 파일 트리가 `role="tree"`가 아니고 키보드 탐색이 없다. 상태를 점 색으로만 구분한다. 9 px 이하 글자 다수.

---

## 3. 디자인 원칙

1. **장치보다 함대(fleet)가 먼저.** 첫 화면은 "지금 문제 있는 장치가 있나"에 3초 안에 답한다(요약 배너의 상태 수 + 카드 배지). 진단 정보는 한 번 눌러야 보인다.
2. **풀 방식을 숨기지 말고 보여 준다.** 모든 요청은 "다음 체크인"에 묶여 있다. 남은 시간을 수치와 진행 바로 항상 노출하고, 요청 직후 피드백도 그 시각을 말한다.
3. **하나의 주 작업.** 화면(또는 팝업)마다 강조 버튼은 하나. 나머지는 보조/고스트/오버플로 메뉴, 파괴적 작업은 설정 탭의 위험 구역으로.
4. **원시값 대신 의미, 의미 옆에 원시값.** `ATTACHED → 연결됨`, `3291 mV → 3.29 V(빨강)`. 단 원시값은 툴팁·모노 글꼴로 언제든 확인 가능하게.
5. **추정은 추정이라고 쓴다.** 에너지·수명은 "만충 기준 추정"과 가정값을 함께 표기한다.

---

## 4. 디자인 토큰

`apps/web/app/tokens.css`를 새로 만들고 `layout.tsx`에서 `globals.css` 다음, `dashboard.css` 앞에 import한다. 값은 샘플 HTML `:root`와 동일하다. 기존 브랜드(짙은 녹색 `#10251d`, 주황 `#e67c2d`, 크림 배경 `#f0f0e7`)를 유지하되 대비를 맞춰 미세 조정했다.

### 4.1 색 (v1.1: 원래 브랜드 톤)

기존 화면의 색(`globals.css`·`dashboard.css`에서 가장 많이 쓰인 값)을 기준으로 정했다: 채팅 패널 `#10251d`, 폴더 탭 활성 `#295b3b`, 강조 `#e67c2d`/`#d66e24`, 배경 `#f0f0e7`, 카드 `#fbfcf6`, 테두리 `#cbd8c6` 계열, 본문 `#173d2b`.

| 토큰 | 값 | 용도 |
|---|---|---|
| `--bg` | `#f0f0e7` | 대시보드 캔버스(기존과 동일) |
| `--surface` / `--surface-2` / `--sunken` | `#fdfdf9` / `#f5f8f0` / `#e9efe3` | 카드 / 표 머리·보조면 / 입력·트랙·세그먼트 바탕 |
| `--border` / `--border-strong` / `--divider` | `#d9e3d3` / `#bccdb7` / `#e6ece1` | 녹색 기운의 테두리 3단 |
| `--text` / `--text-2` / `--text-3` | `#173d2b` / `#4d6d54` / `#7a907f` | 본문(기존 대시보드 글자색) / 보조 / 캡션 |
| `--forest` / `--forest-2` | `#10251d` / `#1a382a` | 요약 배너, 선택 막대, 토스트, 상세 팝업 아이콘 |
| `--green` / `--green-hover` / `--green-soft` / `--green-line` | `#295b3b` / `#214c31` / `#e3eddf` / `#b9d0b6` | **선택·위치 표시**: 활성 탭, 선택된 소스, 선택 모드 버튼, 프리셋 선택, 전달 타임라인 상자 |
| `--orange` / `--orange-hover` / `--orange-soft` / `--orange-line` / `--orange-text` | `#e67c2d` / `#d66e24` / `#fff2e4` / `#f2c49c` / `#b9581c` | **행동·데이터 강조**: 주 버튼, 하위 탭 밑줄, 체크된 행·썸네일·체크박스, 포커스 링, 대기 작업 표시, 차트 선, 보고 있는 메트릭 카드 |
| `--ok` `--warn` `--danger` `--idle` | `#3d8a4f` `#b26a12` `#c03d2a` `#7f8f84` | 상태 의미색. 각각 `-soft`·`-line` 짝 |

역할 분담: **녹색 = 지금 어디에 있는가**(활성 탭, 선택된 소스, 세그먼트, 프리셋, 선택 모드 버튼), **주황 = 행동과 그 대상**(주 버튼, 체크된 항목, 포커스 링, 대기 작업) **및 데이터 강조**(차트 선, 보고 있는 메트릭 카드). 경고는 주황이 아니라 황토(`--warn`)로 구분해 행동 버튼과 섞이지 않게 한다. 정보 배지(`자주 확인 중`)는 녹색 연한 배지를 쓴다(v1의 파란색 `--info` 삭제).

### 4.2 타이포그래피
- 글꼴: 기존 스택 유지(`Inter, ui-sans-serif, system-ui, -apple-system, "Apple SD Gothic Neo"`). 앞에 `"Pretendard Variable", Pretendard`를 두되 **로컬 설치 시에만** 적용(웹폰트 다운로드 추가 안 함). ID·경로는 `--mono`.
- 크기 단계: 11 · 12 · 13(기본) · 14 · 17(다이얼로그 제목·스탯) · 20 · 22(배너 제목) · 24(카드 값) px. 페이지 제목만 28 px 예외. **11 px 미만 금지.**
- 숫자 데이터에는 `font-variant-numeric: tabular-nums`(`.num`).
- 굵기: 400 / 600 / 700 / 800(숫자 값 전용).

### 4.3 간격·모서리·그림자·모션
- 간격 4 px 그리드: 4 · 8 · 12 · 16 · 20 · 24 · 32.
- 모서리: `--r-sm 7px`(버튼·입력) · `--r-md 10px`(내부 블록) · `--r-lg 14px`(카드) · `--r-xl 18px`(요약 배너·다이얼로그) · 알약 999 px.
- 그림자 3단계: `--shadow-1`(카드) · `--shadow-2`(팝오버·호버) · `--shadow-3`(모달·토스트).
- 포커스: `--ring: 0 0 0 3px rgba(230,124,45,.35)`, 모든 대화형 요소 `:focus-visible`에 적용.
- 모션 120~220 ms, `cubic-bezier(.2,.7,.2,1)`. `prefers-reduced-motion: reduce`이면 전부 끈다.

### 4.4 상태 매핑 (단일 진실원: `components/beacon/format.ts`)

| 조건(위에서 먼저 걸리는 것) | 배지 | 의미색 | 필터 칩 |
|---|---|---|---|
| `state !== "ATTACHED"` | `연결됨/발견됨/해제됨/절전` 한국어 라벨 | idle | — |
| `online === false` | 오프라인 | danger | 오프라인 |
| `last_vbat_mv < 3300` | 배터리 위험 | danger | 주의 |
| `last_vbat_mv < 3450` | 배터리 낮음 | warn | 주의 |
| 워치 모드(`next_given ≤ 60` 이고 `interval_s > 60`) | 자주 확인 중 | green(연한 녹색 배지) | 정상 |
| 그 외 | 정상 | ok | 정상 |

전압 임계값은 SPEC_NET 4절과 같은 상수(`VBAT_WARN=3450`, `VBAT_CRIT=3300`)를 쓴다. 배터리 막대는 3.30~4.20 V 선형 채움이며 **퍼센트로 표기하지 않는다**(방전 곡선 미측정).

신호 막대(상세 팝업에서만): RSSI ≥ −55 → 4칸, ≥ −67 → 3칸, ≥ −75 → 2칸, 그 외 1칸. 채운 칸은 `--green`.

---

## 5. 정보 구조와 레이아웃

### 5.1 탭
`농장 현황 · 제주 날씨 · Beacon(개수) · 데이터 서버`. 기존 폴더 탭의 "녹색 채움"을 살려 **알약형 세그먼트 탭**으로 바꾼다: 바탕 `#e2e9dc` 트랙(패딩 4 px, 모서리 12 px), 탭 높이 34 px, 활성 탭은 `--green` 채움 + 흰 글자, 개수 배지는 반투명 흰색. `role="tablist"/"tab"`, 좌우 화살표로 이동.

페이지 헤더의 eyebrow/h1은 유지하고, Beacon·데이터 서버 화면 안의 중복 제목(`beacon-heading`, `beacon-data-heading`)은 삭제한다.

### 5.2 컨텍스트 바 (두 탭 공유)
`[농장 선택 ▾] [● 수신 서버 정상 · USB 1 ▾] ............ ↻ 12초 전 동기화`

- 농장 선택은 하나만 둔다. 상태는 `BeaconFleetProvider`(9.2)가 갖고 Beacon·데이터 서버·지도 마커가 같은 값을 읽는다.
- 수신 서버 알약: `reachable`에 따라 `정상(ok, 맥박 점)` / `연결 불가(danger)` / `확인 중(idle)`. 클릭하면 **시스템 팝오버**(6.8).
- 동기화 시각: 마지막 성공 폴링 기준 상대 시간. 클릭하면 즉시 새로고침.

### 5.3 반응형: 미디어 쿼리 대신 컨테이너 쿼리
대시보드 폭은 채팅 분할(38~65%)에 따라 바뀌므로 뷰포트가 아니라 `.farm-dashboard`에 `container-type: inline-size; container-name: dash`를 주고 `@container dash (…)`로 분기한다.

| 대시보드 폭 | Beacon 화면 | 데이터 서버 |
|---|---|---|
| ≥ 1100 px | 카드 4~5열 | 소스 레일 210 px \| 본문 |
| 700~1099 px | 카드 2~3열 | 같음 |
| < 700 px | 카드 1~2열, 요약 배너의 상태 버튼이 줄바꿈 | 소스 레일이 위로(최대 210 px) |

카드 열 수는 `auto-fill, minmax(260px, 1fr)`이 정하므로 별도 분기가 필요 없다. 상세 팝업·다이얼로그는 대시보드가 아니라 **뷰포트** 기준(`@media (max-width:640px)` → 아래 시트).

---

## 6. Beacon 화면 명세

v1.1 원칙: **기본 화면은 "농장 센서가 괜찮은가"에만 답한다.** 신호 세기, 다음 체크인, Wi-Fi 접속 시간, 전력 추정, 작업 이력 같은 진단 정보는 카드를 눌렀을 때 뜨는 **상세 팝업**(6.4)에서만 보여 준다.

### 6.1 요약 배너 (`FleetHero`)
짙은 녹색 그라데이션 카드 한 장(`--forest → --forest-2`, 오른쪽 위 주황 방사형 하이라이트).
```
FARM NETWORK
Beacon 6대 연결            [전체 6] [● 정상 4] [● 주의 1] [● 오프라인 1]          [+ 장치 추가]
마지막 수신 방금 · 전달 대기 2건
```
- 숫자 `6`만 주황(`#ffb978`)으로 강조한다.
- 상태 버튼 4개가 곧 **필터**다(`aria-pressed`). 선택된 버튼은 크림색 채움 + 짙은 녹색 글자. 점 색: 정상 `#7fd08f`, 주의 `#f2b14f`, 오프라인 `#ff8a73`(짙은 배경 위 대비용 밝은 톤).
- `장치 추가`(주황)가 기본 화면의 유일한 강조 버튼이다.
- v1의 KPI 카드 4개(최저 배터리, 예상 수명 등)는 삭제한다. 최저 배터리는 카드의 배지·배터리 색으로, 수명은 상세 팝업으로 옮긴다.

### 6.2 목록 머리
`장치` 제목(필터 적용 시 `장치 · 주의`) + 오른쪽 검색(이름·위치·ID 부분 일치, 120 ms 디바운스). 툴바·필터 칩·정렬 UI는 따로 두지 않는다.

### 6.3 장치 카드 (`DeviceCard`)
그리드 `repeat(auto-fill, minmax(260px, 1fr))`, 간격 12 px. 카드 전체가 하나의 `<button>`이다.

```
[아이콘] 북쪽 하우스 1                 ● 정상
         북쪽 하우스 · 3열 입구
16.8 °C     60.0 %
온도         습도
──────────────────────────────────────
[▮▮▮ ] 3.98 V · 1분 전                ⏱ 대기 1
```

| 영역 | 내용 | 원천 |
|---|---|---|
| 머리 | 녹색 연한 배경 아이콘, 이름(14 px 700), 위치 한 줄, 4.4 상태 배지 | `label`, `metadata.location`, 상태 |
| 값 | 센서 최대 2개의 최신값(24 px 800, 단위 13 px) + 이름 | 상세 응답이 아닌 **목록 응답에 최신값 추가 필요** — 9.2 참조 |
| 바닥 | 배터리 아이콘(채움 3.30~4.20 V 선형, 의미색) + 전압, 마지막 체크인 상대 시간, 대기 작업이 있으면 주황 `⏱ 대기 n` | `last_vbat_mv`, `last_seen`, `pending_commands` |

- 정렬: 오프라인 → 주의 → 정상 → 기타, 같은 등급은 이름순.
- 오프라인 카드: 아이콘·값을 회색으로, 값은 마지막으로 받은 값 그대로(상대 시간이 낡음을 알려 준다).
- 호버: 테두리 `--orange-line`, `--shadow-2`, 1 px 위로.
- 필터·검색이 없을 때 마지막 칸에 점선 `+ 새 Beacon 연결` 카드.
- **카드에 넣지 않는 것**: RSSI, 다음 체크인, 펌웨어, IP, Wi-Fi 시간, 전력 추정, 명령 버튼.
- 빈 상태: 등록 장치 0 → "이 농장에 연결된 Beacon이 없습니다" + `장치 추가`. 필터 결과 0 → "조건에 맞는 장치가 없습니다".
- 로딩: 첫 로드에만 카드 스켈레톤 3장.

### 6.4 상세 팝업 (`DeviceDialog`)
카드를 누르면 화면 위에 오버레이로 뜬다. 네이티브 `<dialog>` + `showModal()`, 폭 `min(660px, 100%)`, 최대 높이 `100vh − 48px`(본문만 스크롤), 배경은 `rgba(16,37,29,.42)` + 3 px 블러. 폭 640 px 이하 뷰포트에서는 아래에서 올라오는 시트(모서리 위쪽만 둥글게, 높이 92vh). Esc·배경 클릭·× 버튼으로 닫고, 닫으면 눌렀던 카드로 포커스를 돌려준다. URL은 바꾸지 않는다(P1 후보: `?beacon=tc-…`).

구성(위에서 아래로):
1. **머리**: 42 px 짙은 녹색 아이콘(주황 글리프), 이름(17 px), `ID 복사` 칩, 위치, 상태 배지, 닫기.
2. **작업 줄**: `[센서 읽기]`(주황 primary) `[촬영 | ▾]`(해상도 메뉴 QVGA/VGA/SVGA/XGA) ··· `[데이터]`(데이터 서버로 이동하며 팝업 닫기) `[⋯]`(1분간 즉시 응답 · 10분간 자주 확인 · 설정 편집 · 절전 · 연결 해제).
3. **전달 타임라인** (`DeliveryBar`) — 연한 녹색 상자:
   ```
   ⏱ 요청은 다음 체크인에 전달됩니다                    약 3분 45초 후
   [녹색→주황 그라데이션 진행 바·····························]
   마지막 체크인 23:24                                 주기 5분 · 자주 확인 모드
   ```
   진행률 `(now − last_seen) / next_given`, 남은 시간 `next_expected_at − now`, 30 s 넘게 지나면 "N분 지연", 오프라인이면 빨간 상자에 "N시간 이후 체크인이 없습니다. 대기 작업은 다시 연결되면 전달됩니다". `next_given ≤ 60` → "자주 확인 모드", `next_given > interval_s` → "저전압으로 연장됨". 1초 틱은 이 컴포넌트만 갱신한다.
4. **하위 탭** `상태 · 작업(n) · 설정` (활성 밑줄 주황)
   - 상태: 2×2 스탯(배터리 전압+48회 스파크라인 / 신호 세기+막대+스파크라인, 채널·IP / Wi-Fi 접속 중앙값·빠른 접속 비율 / 깨어 있는 시간 중앙값·상한 25초) → 센서 행 목록(아이콘, 이름, 모델·I²C 주소·측정 시각, 값, "데이터 서버 ›") → 전력 카드(`예상 소모 X mAh/일` · `만충 기준 수명 N일` + 가정값 안내, "잔여" 금지).
   - 작업: 명령 타임라인(대기·전달 = 주황, 완료 = 녹색, 실패·만료 = 빨강/회색), 진행 중이면 3단 스텝 막대, 실패 사유는 사람 말로, 소요 시간.
   - 설정: 정의 목록(표시 이름, 설치 위치+좌표, 수집 주기, 수집 데이터, 펌웨어, 보고한 센서) + `[설정 편집]` + 위험 구역(절전, 연결 해제).
- 팝업이 열려 있는 동안에만 상세(7 s)·에너지(60 s)를 폴링한다(9.3).
- 팝업 위에 다른 다이얼로그(설정 편집, 확인)가 뜨면 두 번째 `<dialog>`로 쌓고, Esc는 맨 위 것만 닫는다.

### 6.5 명령 요청 정책
- 센서·촬영 버튼은 `registered && state==="ATTACHED"`이면 활성. **오프라인이어도 활성**으로 두고, 토스트에서 "다시 연결되면 전달됩니다"라고 안내한다(서버 만료 규칙 `max(2×next_given, 900 s)`에 따라 만료될 수 있음을 툴팁으로 표기).
- 요청 직후: 낙관적으로 상세 팝업의 작업 탭에 `queued` 항목을 추가하고 하위 탭을 `작업`으로 전환, 토스트 "촬영 #32 대기열 등록 — 북쪽 하우스 1이 약 3분 46초 후 체크인할 때 실행됩니다". 다음 상세 폴링에서 서버 값으로 대체한다.
- 응답 대기(`session`)·자주 확인(`watch`)도 "다음 체크인부터" 적용됨을 토스트에 쓴다.

### 6.6 장치 추가 모달 (3단계)
기존 "연결 가능한 Beacon" 목록 모달 + 설정 모달을 하나의 단계형 흐름으로 합친다.
1. **장치 선택**: `availableNodes`(미등록 또는 이 농장 소속) 라디오 목록. 행: ID(모노), IP, "N분 전 체크인", 배지(`10분 이내 처음 본 장치 → 새로 발견`, 그 외 `발견됨`). 하단 안내: 서버 주소와 "발견된 장치는 15분마다 체크인" (SPEC_NET 4절 `DISCOVERED next=900`).
2. **이름·수집**: 표시 이름(필수, 64자) · 체크인 주기 프리셋 `1분/5분/15분/1시간`(+직접 입력 60~14,400 s) — 각 프리셋 아래 만충 기준 예상 수명(365일 초과는 "1년 이상") · 수집 데이터 토글(센서/이미지) · 하단 정보 띠 "이 설정의 예상 배터리 수명 105일 · 목표 30일 충족/미달".
   예상 수명 계산은 서버 `energy` 설정과 같은 식을 클라이언트에서 쓴다: `일 소모 = (86400/T)·i_active·t_checkin/3600 + (이미지 ? 24·i_cam·t_img/3600 : 0) + i_off·24/1000`, 수명 = `usable_mah / 일 소모`. 상수는 P0에서 하드코딩(서버 `config.json`과 같은 기본값), P1에서 API로 받는다(11절).
3. **설치 위치**: "지도에서 위치 선택" → 기존 흐름대로 농장 지도 배치 모드로 전환 후 선택/취소 시 모달 3단계로 복귀. 좌표가 있으면 미니 요약(좌표 + "변경")을 보여 준다. 농장 경계가 없으면 이 단계에서 "먼저 농장 경계를 등록하세요" + 농장 지도로 가는 버튼.
- 버튼: `이전` / `취소` / `다음`·`연결하고 저장`(primary). 각 단계 필수값이 없으면 `다음` 비활성.
- 저장 성공 → 모달 닫기, 새 장치 선택, 토스트 "장치를 연결했습니다 · 다음 체크인 때 토큰과 설정이 전달됩니다".
- 기존 장치의 `설정 편집`은 같은 모달을 2단계부터 연다(1단계 숨김).

### 6.7 파괴적 작업 확인
`window.confirm` 대신 확인 모달:
- 절전: "북쪽 하우스 1을 절전할까요? 타이머 없이 전원이 꺼집니다. 다시 켜려면 장치에서 전원을 넣어야 합니다." → 장치 이름 입력 후 `절전`(danger) 활성.
- 연결 해제: "대기 중인 작업 n건이 만료되고, 장치는 1시간마다 짧게 체크인합니다." → `연결 해제`(danger). 이름 입력은 요구하지 않는다(되돌릴 수 있음).

### 6.8 시스템 팝오버
수신 서버(`Docker · beacon-server · 노드 API :8080`, 상태 배지) + USB 직렬 포트 목록(라벨, `/dev/…`, `리셋 후 확인`) + 기존 안내 문구(리셋은 Wi-Fi 설정을 바꾸지 않음, 포트-장치 대응 미보장). 리셋 확인 루프(최대 45 s)는 기존 로직을 그대로 옮기고, 결과는 토스트로 알린다. 포트가 없을 때 안내 문구는 기존 것을 유지.

### 6.9 토스트
- 오른쪽 아래, 최대 3개, 5.2 s 후 사라짐(호버 중 정지), 닫기 버튼. `aria-live="polite"`. 바탕 `--forest`, 아래쪽에 남은 시간 주황 막대.
- 행동 버튼 하나를 붙일 수 있다(예: 삭제의 `실행 취소`, 주황 글자). 행동 버튼이 있는 토스트는 정해진 시간(삭제는 6 s) 동안 유지한다.
- 종류: 성공(✓) / 대기(⏱) / 오류(!, 자동 닫힘 없음). 오류 토스트에는 `다시 시도`가 붙을 수 있다.
- `beacon-notice` 배너는 **수신 서버 연결 불가** 같은 지속 상태에만 쓴다(컨텍스트 바 아래 한 줄).

---

## 7. 데이터 서버 화면 명세

### 7.1 레이아웃
`[소스 레일 220px] | [브레드크럼 / 세그먼트 · 저장 위치 칩 · CSV] / [본문]` 하나의 카드 안에 둔다.

- **소스 레일**: 검색 → `BEACONS n` 그룹 → 장치 행(상태 점, 이름, 측정 건수) → 하단에 저장 방식 범례(`측정·이벤트 · SQLite state/mirgam.db`, `이미지 원본 · SSD raw/images/`). 기존 "파일" 은유는 이 범례와 브레드크럼으로만 남긴다.
- **브레드크럼**: `한라봉 1농장 › beacons › 북쪽 하우스 1 › sensors` (마지막은 모노).
- **세그먼트**: `센서 n · 이미지 n · 체크인 n · 작업 n`. 기존 "자료 종류" select와 폴더 접기/펴기를 대체한다.
- **저장 위치 칩**: 현재 보기의 출처 테이블/경로(`SQLite · sensor_readings`, `SSD · raw/images/tc-a1b2c3/`).
- **CSV**: 현재 보기 행을 클라이언트에서 CSV로 생성해 내려받기(`Blob`). 이미지 보기에서는 숨긴다.
- **선택 / ⋯**: 삭제 진입점(7.7). `[선택]`은 토글 버튼(`aria-pressed`, 켜지면 녹색), `⋯` 메뉴에 `항목 선택해서 삭제`, `기간으로 삭제…`(빨간 글자).
- 소스 레일의 선택된 장치는 `--green` 채움 + 흰 글자, 세그먼트의 선택 항목은 흰 바탕 + 녹색 글자, 선택된 센서 메트릭 카드는 주황 테두리 + 위쪽 주황 그라데이션.

### 7.2 센서
- 상단 메트릭 카드(센서별 1장): 이름·모델, 최신값(24 px), "1시간 전 대비 ±x"(4건 전 값과 비교). 선택 카드 강조.
- 차트 카드: 제목 + 최저/평균/최고. **SVG 라인 + 영역 그라데이션, 직접 구현**(`components/beacon/LineChart.tsx`):
  - viewBox 폭 = 실제 픽셀 폭(`ResizeObserver`), `preserveAspectRatio` 기본값 — 글자 왜곡 금지.
  - y축 "nice" 눈금(1·2·5×10ⁿ), x축 시각 라벨은 폭에 따라 16/32건 간격.
  - 호버: 세로 점선 + 점 + 툴팁(`값 단위 · 날짜 시각`). 키보드 ←/→로도 이동, 툴팁 내용은 `aria-live`.
  - 품질 `suspect` 점은 warn 색 점으로 표시.
- 표: 최신순, sticky 헤더, 최대 높이 300 px 스크롤. 품질은 배지.
- 비어 있음: "아직 센서 결과가 없습니다 — Beacon 화면에서 센서 읽기를 요청하면 다음 체크인 후 여기에 쌓입니다."

### 7.3 이미지
- 날짜별 그룹("11월 20일 (금)") + 4:3 썸네일 그리드(`minmax(150px,1fr)`), 캡션: 시각, 해상도·크기.
- 썸네일은 `/api/backend/dashboard/assets/{id}/preview`, `loading="lazy"`, 고정 비율 박스로 레이아웃 흔들림 방지.
- 클릭 → 라이트박스 모달: 파일명(모노), 촬영 시각·해상도·크기, 원본 경로, `원본 내려받기`. ←/→ 이전/다음, Esc 닫기.
- 비어 있음: 이미지 수집이 꺼져 있으면 그 사실과 `지금 촬영 요청` 버튼.

### 7.4 체크인
정형 테이블(최신순): 수신 시각 · 부팅(`boot`, 모노) · 전압(의미색, 3자리) · RSSI · Wi-Fi 접속(ms + `빠름`/`전체 스캔` 배지) · 활성 시간 · 직전 결과(`ok` ok, `wifi_fail`·`http_fail` warn, `awake_cap`·`rtc_fail` danger) · 다음 주기. JSON 원문은 행 펼침으로만.

### 7.5 작업
테이블: ID · 종류 · 상태 배지 · 요청 · 완료 · 소요 · `JSON` 펼침(`params`, `result`, `reason`을 들여쓴 `pre`).

### 7.6 진입 경로
- 상세 팝업의 `데이터`/“데이터 서버 ›” → 팝업을 닫고 데이터 서버 탭, 해당 장치·센서 선택(`dataSelection` 유지).
- 지도 마커 클릭 → 기존처럼 데이터 서버 해당 장치.
- 탭을 직접 클릭하면 마지막 선택을 유지한다(현재는 `setDataSelection(null)`로 초기화됨 — 제거).

### 7.7 데이터 삭제 (UX)

삭제는 데이터 서버에서만 한다(Beacon 화면·상세 팝업에는 넣지 않는다). 진입점은 두 가지다.

**① 골라서 삭제** — 툴바 `[선택]` 토글(또는 `⋯ → 항목 선택해서 삭제`)
- 선택 모드에서 표 맨 앞에 체크박스 열이 생기고, 머리 체크박스는 **현재 보이는 행 전체** 선택/해제(일부 선택이면 indeterminate). 이미지는 썸네일 왼쪽 위 체크박스 + 날짜 그룹 머리 체크박스(그 날 전체). 선택 모드에서 썸네일을 누르면 라이트박스 대신 선택이 토글된다.
- 선택된 행은 `--orange-soft` 배경, 썸네일은 주황 2 px 테두리.
- 본문 아래에 짙은 녹색 **선택 막대**(sticky, `--forest`)가 뜬다: `3개 선택됨 · [선택 해제] [완료] [🗑 삭제]`(삭제는 `--danger` 채움, 0개면 비활성).
- 진행 중(`queued`·`dispatched`) 작업 행은 체크박스 비활성 + 툴팁 "진행 중인 작업은 삭제할 수 없습니다".
- 자료 종류·장치를 바꾸면 선택은 비워진다(선택 모드는 유지).
- 라이트박스 바닥에 `[🗑 삭제]`(빨간 외곽선) — 한 장 삭제의 지름길.

**② 기간으로 삭제** — 툴바 `⋯ → 기간으로 삭제…`
- 대상(센서만): `현재 센서(온도)만` / `이 장치의 모든 센서`.
- 기간 라디오: `3일보다 오래된 기록` · `7일보다 오래된 기록` · `30일보다 오래된 기록` · `전체 삭제`. 각 줄 오른쪽에 **서버가 계산한 예상 건수**(`dry_run`, 7.8)를 보여 준다. 라디오를 바꿀 때마다 dry-run을 다시 호출(250 ms 디바운스, 응답 전에는 건수 자리에 스피너).
- `전체 삭제`를 고르면 "확인을 위해 장치 이름 **북쪽 하우스 1**을 입력하세요" 입력란이 나오고, 정확히 일치할 때만 버튼이 켜진다.

**확인 다이얼로그(두 경로 공통)**
```
[🗑]  센서 측정 3건을 삭제할까요?                         ×
      선택한 항목만 지웁니다.
 ┌ 장치      북쪽 하우스 1 tc-a1b2c3
 │ 종류      센서 측정 · 온도
 │ 삭제 대상  3건 (이미지는 + 용량)
 │ 기간      11. 20. 22:24 ~ 11. 20. 23:24
 └ 저장 위치  SQLite · sensor_readings
 ⚠ 삭제한 기록은 되돌릴 수 없습니다. 차트, 데이터 서버, 농장 AI의 답변 근거에서도 사라집니다.
   (이미지) Beacon 수신 서버에 남은 원본(/mnt/nvme/beacon/images)은 이 화면에서 지우지 않습니다.
   (작업)   대기·전달 중인 작업은 삭제되지 않습니다.
 삭제 후 6초 동안 실행 취소할 수 있습니다        [취소] [🗑 3건 삭제]
```
- 버튼 문구에 건수를 넣는다(`3건 삭제`, `40장 삭제`). 초기 포커스는 `취소`.

**실행과 실행 취소**
- 확인을 누르면 화면에서 즉시 사라지게 하고(클라이언트 `pendingDeletes`에 id를 넣어 필터링), 토스트 "센서 측정 3건 삭제됨 · 6초 후 서버에서 확정됩니다 [실행 취소]"를 6 s 진행 막대와 함께 띄운다.
- 6 s가 지나면 그때 `POST …/data/delete`를 호출한다. 실행 취소를 누르면 호출하지 않고 목록을 되돌린다. 탭이 닫히거나 페이지를 떠나면(`pagehide`) 대기 중인 삭제는 **보내지 않는다**(지워지지 않는 쪽으로 실패).
- 서버 응답의 `deleted` 수가 요청과 다르면 경고 토스트("요청 12건 중 10건만 삭제되었습니다 — 2건은 이미 없거나 진행 중")를 띄우고 상세를 다시 불러온다.
- 실패(4xx/5xx)면 숨겼던 행을 되돌리고 오류 토스트(자동 닫힘 없음, `다시 시도`).
- 삭제 후 센서 메트릭 카드의 "N건 저장", 세그먼트 건수, 소스 레일 건수가 즉시 줄어든다.

### 7.8 데이터 삭제 API (백엔드, P0 필수)

현재 삭제 엔드포인트가 없다. 웹 프록시(`app/api/backend/[...path]/route.ts`)는 `DELETE` 요청의 **본문을 버리므로** 본문이 필요한 삭제는 `POST`로 설계한다.

```
POST /dashboard/beacons/{node_id}/data/delete
{
  "kind": "sensor" | "image" | "checkin" | "command",
  "ids": ["..."],                     // ①: 골라서 삭제. ②와 동시 사용 금지
  "sensor_ids": ["..."],              // ② kind=sensor일 때 대상 센서(생략 = 이 장치의 모든 센서)
  "before": "2026-11-13T00:00:00Z",   // ② 이 시각 이전만. "all": true와 배타
  "all": false,
  "confirm_label": "북쪽 하우스 1",    // all=true일 때 필수, 장치 label과 일치해야 함
  "dry_run": false
}
→ 200 { "kind": "sensor", "matched": 1234, "deleted": 1234, "skipped_busy": 0,
        "freed_bytes": 0, "range": {"from": "...", "to": "..."}, "dry_run": false }
```

| kind | id 형식 | 지우는 것 | 지우지 않는 것 |
|---|---|---|---|
| `sensor` | `reading_id`(정수) | `sensor_readings` 행. `sensor_id`가 이 장치 소유(`sensor_devices.metadata_json.beacon_node_id = node_id`)인 것만 | `sensor_devices`(센서 정의), 작업의 `result_json` |
| `image` | `asset_id` | `camera_assets` 행 + `data_root` 안의 사본 파일(`raw/beacons/<node>/<cmd>.jpg`). `vision_runs/observations.asset_id`는 FK `ON DELETE SET NULL` | Beacon 서버 원본(API 컨테이너에 `:ro` 마운트라 불가) |
| `checkin` | `checkin_id` | `beacon_node_checkins` 행 | Beacon 서버 DB의 체크인(에너지 추정은 그쪽 기준이라 영향 없음) |
| `command` | `command_id` | `beacon_commands` + `beacon_sensor_results` 행(state ∈ done/failed/expired) | 진행 중 작업(`skipped_busy`로 집계), 이미 생성된 측정·이미지 |

구현 규칙:
- 권한: 기존 `_assert_owner(account_id, node_id)` 재사용. 다른 계정 장치·다른 장치 id가 섞이면 해당 id는 무시하고 `matched`에서 뺀다(존재 여부를 노출하지 않음).
- 한 트랜잭션(`BEGIN IMMEDIATE`)에서 행 삭제 → 커밋 후 파일 삭제. 파일 경로는 `(data_root / file_path).resolve()`가 `data_root/raw/beacons/<node_id>/` 아래인지 확인한 뒤에만 `unlink(missing_ok=True)`. 파일 삭제 실패는 로그만 남기고 응답 `file_errors`에 개수로 보고.
- 한 요청 최대 `ids` 1,000개, 범위 삭제는 내부적으로 5,000행씩 나눠 지운다(WAL 잠금 시간 제한).
- `dry_run=true`면 같은 조건으로 `COUNT(*)`, `MIN/MAX(시각)`, (이미지) `SUM(byte_size)`만 계산한다.
- `sensor_daily_rollups`에 해당 센서의 `source='beacon'` 집계가 있으면 영향받은 `local_date`를 다시 계산한다(현재 Beacon 측정은 집계를 만들지 않으므로 보통은 없음 — 14절).
- 감사 기록: 새 테이블 `beacon_data_deletions(id, account_id, node_id, kind, matched, deleted, criteria_json, created_at)`에 한 줄. 로그에는 개수만 남기고 값은 남기지 않는다.
- 읽기 응답 보강: 상세 `GET /dashboard/beacons/{id}`의 `readings` 항목에 `reading_id`, `checkins`에 `checkin_id`를 포함한다(지금은 없음 — `beacon_store.detail()`의 SELECT에 추가).
- 단위 테스트(`services/api/tests/test_beacon_delete.py`, 표준 `unittest`): 소유권, busy 작업 건너뜀, 경로 탈출(`../`) 거부, dry_run이 아무것도 지우지 않음, `all` + 이름 불일치 422, 이미지 행·파일 동시 삭제.


---

## 8. 표시 규칙 (`format.ts`)

| 대상 | 규칙 | 예 |
|---|---|---|
| 상대 시간 | < 45 s "방금", < 1 h "N분 전", < 24 h "N시간 M분 전", 이후 "N일 전". 툴팁에 절대 시각 | `3분 전` |
| 카운트다운 | `M분 SS초`, < 60 s `S초`, ≤ 0 `곧`, 지연 30 s 초과 `M분 SS초 지연` | `3분 46초` |
| 주기 | 3600 배수 → 시간, 60 배수 → 분, 그 외 초 | `5분` |
| 절대 시각 | `Intl.DateTimeFormat("ko-KR")`, 24시간제 | `11. 20. 22:56` |
| 전압 | `(mv/1000).toFixed(2) V`, 체크인 표만 3자리 | `3.98 V` |
| 크기 | KB(소수 1자리) / MB(2자리) | `48.2 KB` |
| 상태 라벨 | `ATTACHED 연결됨 · DISCOVERED 발견됨 · DETACHED 해제됨 · HIBERNATING 절전`, 명령 `queued 대기 · dispatched 전달됨 · done 완료 · failed 실패 · expired 만료` | |
| 문장 | 존댓말 평서문, 마침표. 버튼은 동사 2~5자(`센서 읽기`, `촬영`, `연결하고 저장`) | |

---

## 9. 구현 구조

### 9.1 파일

```
apps/web/app/
  tokens.css                    NEW  4절 토큰
  beacon.css                    NEW  .bx- 접두 Beacon/데이터 서버 전용 스타일 (샘플 HTML 2~MODAL 블록 이식)
  dashboard.css                 EDIT Beacon/데이터 서버/폴더 탭 규칙 삭제(11절)
apps/web/components/beacon/
  BeaconFleetProvider.tsx       NEW  농장 선택, 노드 목록 폴링, 선택 장치, 토스트 큐 (React context)
  usePolling.ts                 NEW  가시성 인식 폴링 훅
  useNow.ts                     NEW  1초 틱(구독한 컴포넌트만 리렌더)
  format.ts                     NEW  8절 규칙 + 4.4 상태 매핑 + 에너지 추정식
  Icon.tsx                      NEW  인라인 SVG 30여 개(샘플 sprite와 같은 path)
  ContextBar.tsx, SystemPopover.tsx
  FleetHero.tsx, DeviceCard.tsx, DeviceGrid.tsx
  DeviceDialog.tsx, DeliveryBar.tsx, CommandTimeline.tsx, Sparkline.tsx
  AddBeaconDialog.tsx, ConfirmDialog.tsx
  data/ SourceRail.tsx, SensorView.tsx, LineChart.tsx, ImageGallery.tsx, Lightbox.tsx,
        CheckinTable.tsx, CommandTable.tsx, SelectionBar.tsx, DeleteDialog.tsx,
        useSelection.ts, usePendingDeletes.ts   (선택 Set, 6초 지연 삭제·실행 취소)
  ui/ Button.tsx, Badge.tsx, Menu.tsx, Popover.tsx, Dialog.tsx, Toasts.tsx, Segmented.tsx
apps/web/components/
  BeaconDashboard.tsx           REWRITE 위 조각 조립(목표 150줄 이하)
  DataServerDashboard.tsx       REWRITE 자체 폴링·농장 select 제거, Provider 사용
  BeaconDataExplorer.tsx        REWRITE 7절 (SourceRail, SensorView+LineChart, ImageGallery, CheckinTable, CommandTable)
  FarmGeographyPanel.tsx        EDIT  Beacon 섹션 제거, 마커는 Provider의 nodes 사용, placement 콜백 유지
  ChatApp.tsx                   EDIT  Provider로 Beacon·데이터 서버·농장 탭 감싸기, 탭 이름 변경
services/api/app/
  main.py                       EDIT  POST /dashboard/beacons/{node_id}/data/delete 라우트
  schemas.py                    EDIT  BeaconDataDeleteRequest (Pydantic, extra=forbid)
  services/beacon_store.py      EDIT  delete_data(), detail()에 reading_id·checkin_id, 목록에 latest_readings, beacon_data_deletions 테이블
services/api/tests/
  test_beacon_delete.py         NEW   7.8 단위 테스트
```

`Dialog`는 네이티브 `<dialog>` + `showModal()`을 사용한다(포커스 가두기·Esc·`::backdrop` 무료). `Popover`/`Menu`는 `position: fixed` + 앵커 `getBoundingClientRect`, 바깥 클릭·Esc 닫기, 메뉴는 ↑/↓/Home/End 포커스 이동(`role="menu"/"menuitem"`).

### 9.2 데이터 흐름
- `BeaconFleetProvider`가 **유일하게** `/dashboard/beacons`(?farm_id)를 폴링하고 `nodes`, `reachable`, `lastSyncAt`를 제공. 지도 마커(`onNodesChange`)·Beacon 화면·데이터 서버가 모두 여기서 읽는다.
- 카드에 센서값을 보여 주려면 목록 응답에 노드별 `latest_readings: [{sensor_id, display_name, sensor_type, value, unit, recorded_at}]`(센서 정의 순 최대 4개)를 추가한다(`update_node_snapshot`과 `cached_nodes` 양쪽, 센서당 `ORDER BY recorded_at DESC LIMIT 1`). 노드마다 상세를 따로 부르는 방식(N+1 요청)은 쓰지 않는다.
- 상세 `/dashboard/beacons/{id}`는 상세 팝업이 열려 있거나 데이터 서버 본문이 **보일 때만** 폴링(같은 id면 한 번만 — Provider 안의 id별 캐시 + 구독 수 카운트).
- `/energy`는 상세 팝업이 열린 장치만, 60 s 주기.
- 선택 모드이거나 삭제 대기(6 s) 중에는 데이터 서버 상세 폴링을 멈춘다(선택한 행이 갱신으로 밀리거나, 숨긴 행이 다시 나타나는 것 방지). 삭제 확정 응답 후 즉시 1회 다시 불러온다.
- `/usb`는 시스템 팝오버를 열 때만.

### 9.3 폴링 정책 (`usePolling`)
| 대상 | 보일 때 | 숨겨졌을 때(`document.hidden` 또는 탭 비활성) |
|---|---|---|
| 노드 목록 | 10 s | 멈춤(지도 탭이 보이면 30 s) |
| 상세(팝업 열림 또는 데이터 서버) | 7 s / 데이터 서버 15 s, 단 `now ≥ next_expected_at − 3 s`면 다음 1회를 2 s 후로 당김(체크인 직후 반영) | 멈춤 |
| 에너지 | 60 s | 멈춤 |
- 가시성 복귀 시 즉시 1회. 요청 중이면 다음 틱 건너뜀(`AbortController`). 실패 3회 연속이면 30 s로 백오프하고 컨텍스트 바에 경고.
- 1초 카운트다운은 `useNow()`를 구독한 `DeliveryBar`만 리렌더한다. 카드 목록은 매초 렌더하지 않는다(카드의 상대 시간은 폴링 주기마다 갱신으로 충분).

### 9.4 상태 보존
선택 농장·필터·데이터 서버 장치·종류는 `sessionStorage`(`mirgam.beacon.ui`)에 저장해 탭 이동·새로고침 후에도 유지(읽기/쓰기는 try/catch).

---

## 10. 접근성 요구
- 모든 상태는 색 + 텍스트(배지 라벨) 이중 부호화. 신호·배터리 막대에는 `aria-label`("배터리 3.98 V, 정상").
- 대비: 본문 4.5:1, 큰 숫자·아이콘 3:1 이상. 11 px 미만 글자 없음.
- 탭(`tablist`), 세그먼트(`group` + `aria-pressed`), 메뉴(`menu`), 모달(`dialog` + `aria-labelledby`), 토스트(`aria-live=polite`), 표(`<table>` + `<th scope>`).
- 키보드만으로: 탭 전환 → 상태 필터 → 카드 선택(Tab, Enter) → 상세 팝업에서 센서 읽기 → 메뉴 → Esc로 닫고 카드로 포커스 복귀, 그리고 데이터 서버에서 선택 모드 → 체크박스(Space) → 삭제 → 확인까지 가능해야 한다.
- 선택 막대는 `role="region" aria-label="선택 작업"`, 선택 수 변화는 `aria-live="polite"`로 읽힌다. 체크박스마다 `aria-label`("11월 20일 22:24 측정 선택").
- 포커스 링은 `:focus-visible`에서만, 제거 금지.

---

## 11. CSS 마이그레이션
1. `tokens.css`, `beacon.css` 추가. 새 컴포넌트는 **`.bx-` 접두 클래스만** 쓴다(기존 `.beacon-*`와 충돌 방지).
2. 샘플 HTML의 클래스 이름(`.hero`, `.dcard`, `.dialog`, `.bulkbar` …)은 이식할 때 모두 `.bx-` 접두로 바꾼다(`.bx-hero`, `.bx-card` …).
3. 새 컴포넌트로 교체한 뒤 `dashboard.css`에서 다음 접두의 규칙을 전부 삭제: `.beacon-`, `.data-server-`, `.farm-beacon-dashboard-section`, `.dashboard-folder-tabs`. 삭제 전후 `grep -c` 결과를 보고서에 남긴다.
4. 삭제 후 `dashboard.css` 크기와 고유 색 수를 다시 측정해 보고(목표: Beacon 관련 셀렉터 0, 파일 크기 40% 이상 감소).
5. 농장 현황·제주 날씨 화면이 시각적으로 바뀌지 않았음을 전후 스크린샷으로 확인.

(선택, P2) 나머지 화면의 색을 토큰으로 치환하는 작업은 별도 PR.

---

## 12. 작업 순서와 수락 기준

### 12.1 PR 단위
| PR | 내용 | 확인 |
|---|---|---|
| P0-1 | `tokens.css`, `beacon.css`, `ui/*`, `Icon`, `format.ts`(+단위 테스트 없이 순수 함수) | `npm run lint`(tsc) 통과 |
| P0-2 | `BeaconFleetProvider`, `usePolling`, `useNow`; `FarmGeographyPanel`·`DataServerDashboard` 폴링 제거 | 네트워크 탭에서 `/dashboard/beacons`가 10 s당 1회 |
| P0-3 | 백엔드: 목록 `latest_readings`, 상세 `reading_id`·`checkin_id`, 삭제 API + 감사 테이블 + 테스트(7.8) | `python -m unittest discover -s services/api/tests -v` 통과 |
| P0-4 | Beacon 화면(6.1~6.9): 요약 배너, 카드, 상세 팝업 | 13절 시나리오 B1~B10 |
| P0-5 | 데이터 서버(7.1~7.6) | 시나리오 D1~D6 |
| P0-6 | 데이터 삭제 UX(7.7) | 시나리오 X1~X8 |
| P0-7 | CSS 삭제(11절), 문서 교체 | 크기 측정, 전후 스크린샷 |
| P1 | API 보강(아래) | — |

P1 API 보강(선택, 백엔드 작업 별도 승인 후):
- Beacon 서버 원본 이미지까지 지우는 관리 API(`POST /admin/nodes/{id}/images/delete`) — 지금은 API 컨테이너가 원본 폴더를 읽기 전용으로 마운트한다.
- 삭제 대신 보존 기간 설정(예: 센서 180일, 이미지 30일 지나면 자동 정리).
- `GET /dashboard/beacons/energy-config` — 6.6 추정식 상수를 서버 `config.json`에서 받기.
- `GET /dashboard/beacons/{id}/readings?sensor_id=&since=` — 96건 제한을 넘어 기간 선택.

### 12.2 수락 기준
| ID | 기준 |
|---|---|
| UC1 | `npm run lint`, `npm run build` 종료 코드 0 |
| UC2 | 새 npm 의존성 0개(`package.json` diff 없음) |
| UC3 | 한 탭이 보일 때 `/dashboard/beacons` 요청이 10 s당 최대 1회, 문서가 숨겨지면 0회 |
| UC4 | 농장 선택이 화면 전체에 1개이며, Beacon·데이터 서버·지도 마커가 같은 농장을 보여 줌 |
| UC5 | 주황 채움 버튼이 Beacon 기본 화면에 1개(`장치 추가`), 상세 팝업에 1개(`센서 읽기`)뿐 |
| UC5a | 기본 화면(카드)에 RSSI·다음 체크인·IP·펌웨어·전력 추정이 나오지 않고, 상세 팝업에는 모두 나옴 |
| UC6 | 절전·연결 해제가 첫 화면에 노출되지 않고 확인 모달을 거침, `window.confirm` 사용 0 |
| UC7 | 상세 팝업의 카운트다운과 진행 바가 1초마다 갱신되고, 카드 목록은 1초마다 리렌더되지 않음(React Profiler로 확인) |
| UC8 | 에너지 표기에 "잔여"가 없고 "만충 기준"이 있음 |
| UC9 | 대시보드 폭 600 / 760 / 1020 / 1400 px에서 가로 스크롤·겹침 없음(스크린샷 4장) |
| UC10 | 키보드만으로 10절 경로 완료, 11 px 미만 글자 0(계산된 스타일 검사) |
| UC11 | `dashboard.css`에 `.beacon-`·`.data-server-`·`.dashboard-folder-tabs` 셀렉터 0 |
| UC12 | 샘플 HTML과 같은 폭에서 나란히 비교한 스크린샷 제출(사람이 판정) |
| UC13 | 삭제는 확인 다이얼로그를 거치며, 확정 전 6 s 동안 실행 취소 시 서버 요청 0회(네트워크 탭) |
| UC14 | 진행 중 작업은 선택 불가, API에 섞어 보내도 `skipped_busy`로 남고 지워지지 않음 |
| UC15 | 이미지 삭제 후 `camera_assets` 행과 `storage/raw/beacons/…jpg` 파일이 함께 없어지고, Beacon 서버 원본은 그대로 |
| UC16 | `all` 삭제는 장치 이름 정확히 일치할 때만 가능(프론트 버튼 비활성 + 백엔드 422) |

---

## 13. 검증 시나리오와 실패 처리

Beacon(B):
B1 서버 정상·장치 6대 → 요약 배너 숫자와 카드 수 일치, 상태 버튼으로 거르기. B2 카드 클릭 → 상세 팝업, 카운트다운 동작, Esc로 닫으면 카드로 포커스 복귀. B3 센서 읽기 → 토스트 + 작업 탭 `queued`, 다음 체크인 후 `done`. B4 촬영 ▾ → SVGA 선택 시 요청 본문 `fs=SVGA`. B5 오프라인 장치에 센서 읽기 → 대기열 등록, 안내 문구 다름. B6 `⋯ → 10분간 자주 확인` → 다음 체크인 후 배지 "자주 확인 중", 주기 1분. B7 장치 추가 3단계 완료(지도 왕복 포함). B8 절전 확인 모달에서 이름 불일치 시 버튼 비활성. B9 수신 서버 중지 → 알약 danger, 배너 1줄, 저장된 카드는 계속 보임. B10 폭 640 px 이하 뷰포트에서 상세 팝업이 아래 시트로 뜸.

데이터 서버(D):
D1 상세 팝업에서 진입 시 팝업이 닫히고 같은 장치·센서 선택. D2 차트 호버/←→ 툴팁. D3 이미지 라이트박스 이전/다음/Esc. D4 체크인 표 결과 배지 색. D5 작업 JSON 펼침. D6 CSV 내려받기 행 수 = 표시 행 수.

삭제(X):
X1 선택 모드에서 측정 3건 선택 → 삭제 → 확인 → 표·차트·건수에서 즉시 사라짐, 6 s 후 API 1회 호출, DB 행 3개 감소. X2 같은 흐름에서 `실행 취소` → API 호출 0회, 행 복귀. X3 머리 체크박스 → 보이는 행만 전부 선택, 일부 선택 시 indeterminate. X4 이미지 날짜 그룹 선택 → 삭제 → 파일·행 삭제 확인. X5 기간 삭제 `30일보다 오래된` → dry-run 건수와 실제 `deleted` 일치. X6 `전체 삭제` → 이름 불일치 시 버튼 비활성, 일치 시 실행. X7 진행 중 작업 체크박스 비활성. X8 API를 강제로 500으로 만들면 숨긴 행 복귀 + 오류 토스트.

실패 처리: 시나리오가 실패하면 실패 ID, 재현 절차, 콘솔/네트워크 로그, 스크린샷, 원인 가설(가설임을 표시)을 보고하고 다음 PR로 넘어가지 않는다. 산출물은 지우지 않는다.

---

## 14. 가정과 열린 질문
- 전압 → 잔량(%) 변환은 방전 곡선 실측(SPEC_NET 13절) 전까지 하지 않는다.
- 삭제의 "실행 취소"는 서버 휴지통이 아니라 **클라이언트 지연 전송**이다. 6 s 안에 탭을 닫으면 삭제되지 않는다(의도된 안전 방향). 서버 측 휴지통이 필요하면 P1에서 `deleted_at` 소프트 삭제로 바꾼다.
- 측정을 지워도 같은 값이 `beacon_commands.result_json`·`beacon_sensor_results.raw_json`(센서 결과 원문)에 남는다. "완전 삭제"가 필요하면 작업 기록도 함께 지워야 한다는 안내를 확인 다이얼로그에 추가할지 결정이 필요하다.
- Beacon 측정은 현재 `sensor_daily_rollups`를 만들지 않는 것으로 보인다(집계 INSERT는 `sqlite_store.py`의 데모·시드 경로에만 있음, 확인 필요). 그렇다면 7.8의 집계 재계산은 사실상 동작하지 않는다.
- MCP 서버는 같은 SQLite를 읽기 전용으로 연다. 삭제 직후 AI 답변이 옛 값을 인용하지 않는지는 MCP 쪽 캐시 유무에 달려 있다(확인 필요).
- 노드 목록 응답(`beacon_store.update_node_snapshot`)에는 이미 `first_seen`, `next_given`, `last_wifi_ms`, `last_fast`, `last_prev_awake_ms`, `last_prev_result`가 있지만 프론트 `BeaconNode` 타입에는 빠져 있다. 타입에 추가해 쓴다. "새로 발견" 배지는 `now − first_seen < 600 s`로 판단한다.
- 서버 캐시 경로(`cached_nodes`, Beacon 서버 연결 불가 시)는 `next_expected_at: null`, `pending_commands: 0`을 돌려준다. 이때 카운트다운·대기 칸은 `—`로 표시하고 "저장된 정보" 배지를 컨텍스트 바에 붙인다.
- 워치 모드 여부를 `next_given ≤ 60`으로 추론한다. 서버가 `watch_until`을 노출하면 그 값을 쓰는 것이 정확하다(P1 후보).
- 지도 배치 모드 왕복은 기존 `onPlacementStart / pickedLocation / onPlacementCancel` 계약을 그대로 쓴다고 가정한다.
