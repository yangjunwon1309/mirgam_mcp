# Beacon UI 구현·검증 보고

## 1. 환경

- 브랜치 `ui/beacon-v1.1`, 기준 `559c1ef`; 단계 커밋은 아래 표 참고.
- 호스트 Python 3.12.16 (`~/.venvs/mirgam-api`)과 Node 22.11.0. Docker 명령은 실행하지 않았고 버전도 확인하지 않았다.
- 에너지 가정: 프런트의 1560mAh, 120mA, 160mA, 20µA, 빠른 접속 1.5초, 이미지 1.2초는 `services/beacon/config.json`과 같다. 프런트는 빠른 연결과 이미지 하루 24장을 가정하며, 서버는 실제 최근 사용 건수·빠른 연결 비율·센서 소비를 반영한다. 따라서 추정값은 서로 다를 수 있다.

## 2. 단계

| 단계 | 명령 및 종료 코드 | 결과 | 커밋 |
| --- | --- | --- | --- |
| D0 | 기존 작업 | 명세 및 시각 샘플 | `559c1ef` |
| D1 | 호스트 unittest, 0 | 백엔드 삭제·테스트 | `f36ceb2` |
| D2 | 호스트 npm lint, 0 | 공통 스타일·타입·훅 | `a8e91a7` |
| D3 | 호스트 npm lint, 0 | Provider·지도 연동 | `104cba3` |
| D4 | `npm run lint --prefix apps/web`, 0 | Beacon 카드·팝업 | `05417fe` |
| D5 | `npm run lint --prefix apps/web`, 0 | 데이터 조회 | `68a5f4b` |
| D6 | `npm run lint --prefix apps/web`, 0 | 삭제 확인·실행 취소 | `bd107ac` |
| D7 | 호스트 lint/build, 0 | 이전 UI·CSS 제거 | `15538ac` |
| D8 | 호스트 검사 및 문서 | 검수 기록과 후속 보완 | 이 보고서가 포함된 커밋 |

D4 첫 검사에서는 기존 미완성 파일의 TypeScript nullable 오류가 발생했고 이후 수정해 통과했다. 최종 빌드와 별도 lint를 동시에 실행한 한 차례에는 빌드가 `.next/types`를 재생성하면서 lint가 TS6053으로 실패해, 빌드 완료 후 순차 재실행했다. 브라우저 게이트는 사람 확인 대기.

## 3. 백엔드

`cd services/api && timeout 600 ~/.venvs/mirgam-api/bin/python -m unittest discover -s tests -v` 종료 0, 14개 통과. `app.schemas`, `app.services.beacon_store`, `app.services.sqlite_store`, `app.main` import 종료 0. 로그 `docs/_logs/api_tests_final.log`. 테스트 DB는 임시 디렉터리만 사용했다.

삭제 endpoint: `POST /dashboard/beacons/{node_id}/data/delete`. 예시 요청은 `{"kind":"sensor","before":"2026-10-01T00:00:00Z","dry_run":true}`이고 응답 계약은 `kind`, `mode`, `matched`, `deleted`, `skipped_busy`, `skipped_current`, `freed_bytes`, `file_errors`, `range`를 포함한다. 예시는 계약 설명이며 운영 API 호출 결과가 아니다. 운영 DB 삭제·dry-run은 수행하지 않았다.

## 4. 프런트

`apps/web/components/beacon/{fleet,data,ui,hooks,shell}` 아래 파일을 사용한다. 새 파일별 줄 수는 `wc -l apps/web/components/beacon/{fleet,data,ui,hooks,shell}/*`로 확인할 수 있다. 기존 `BeaconDashboard.tsx`, `BeaconDataExplorer.tsx`, `DataServerDashboard.tsx`, 이전 디자인 요약을 삭제했다. `dashboard.css`: 89,351 → 51,397 bytes (42.5% 감소), 이전 선택자 537 → 0. `package.json`과 `pyproject.toml` diff 없음.

## 5. 시나리오

R1~R4, B1~B10, D1~D6, X1~X9는 브라우저·하드웨어 및 실제 삭제가 필요하여 **사람 확인 대기**. 검수는 `docs/verify_ui_beacon.md`에 기록한다. 검수 스크립트는 작성 및 `bash -n`만 실행했다.

## 6. 수락 기준

| ID | 결과 | 근거 |
| --- | --- | --- |
| AC1 | PASS | `npm run lint` 및 호스트 `npm run build` 종료 0. `docs/_logs/web_final_lint.log`, `docs/_logs/web_final_build.log` |
| AC2 | PASS | 임시 DB unittest 14개, 종료 0 |
| AC3 | PASS | `git diff 559c1ef -- apps/web/package.json services/api/pyproject.toml` 출력 없음 |
| AC4 | 부분 PASS | `rg 'listNodes\\(' apps/web/components/beacon`: API 정의와 Provider 호출 각 1개. 네트워크 확인은 사람 대기 |
| AC5~AC7 | 사람 확인 대기 | 브라우저 시나리오 |
| AC8 | PASS | `rg 'window\\.confirm|window\\.alert|\\balert\\(' apps/web/components apps/web/app` 결과 없음 |
| AC9 | 사람 확인 대기 | Profiler 확인 |
| AC10 | PASS | `rg '잔여' apps/web/components apps/web/app` 결과 없음, 에너지 화면에 만충 기준 표기 |
| AC11~AC12 | 사람 확인 대기 | 화면 폭·접근성 |
| AC13 | PASS | `dashboard.css` 관련 선택자 0, 42.5% 감소 |
| AC14 | 사람 확인 대기 | 네트워크에서 확인 |
| AC15 | 부분 PASS | API의 최신 체크인·진행 중 작업 보존 테스트 통과. UI는 사람 확인 대기 |
| AC16~AC17 | 사람 확인 대기 | 실제 파일·시각 비교 |

## 7. 알려진 문제와 구현 결정

- 기존 이미지 미리보기 API는 세션은 확인하지만 이미지 소유 계정은 확인하지 않는다. 이 작업 범위에서 변경하지 않았다.
- 센서 측정 삭제 후에도 작업 결과 원문이 `beacon_commands.result_json`, `beacon_sensor_results.raw_json`에 남을 수 있다.
- 목록 API는 `farm_id` 쿼리를 무시하므로 Provider에서 농장별 필터를 적용한다.
- 결정: 지도 좌표는 수동 입력 없이 지도에서 선택한다 / 근거: 이 프로젝트의 기존 사용자 지시 / 대안: 위도·경도 입력 필드.
- 결정: 카메라·센서 데이터는 목록 응답의 최근 항목만 보여 준다 / 근거: 기존 API의 30장·96건 제한 / 대안: 추가 페이지 API.
- 결정: 실행 취소는 6초 지연 전송 / 근거: 명세 / 대안: 서버 휴지통. 요청 전 탭을 닫으면 전송하지 않는다.
- 시각 디자인·접근성·실기 동작은 사람 검수 전까지 완료로 판단하지 않는다.
- 작업 시작 시 이미 있던 미추적 `docs/CODEX_PROMPT_BEACON_UI.md`와 `docs/beacon-dashboard-sample.html`은 사용자 파일로 보존하고 커밋에서 제외했다. 따라서 이 파일들이 남은 상태에서는 검수 스크립트의 작업 트리 확인이 실패한다.
