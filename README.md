# gemma-mcp

Jetson 기반 스마트팜 AI 에이전트 대시보드의 로컬 우선 최소 프레임워크입니다.

## 구성

```text
Next.js Web → FastAPI agent → OpenAI 호환 llama.cpp / Gemma endpoint
                         ├─ SQLite (대화·센서·이미지 메타데이터·기상 캐시·도구 호출 이력)
                         ├─ SSD files (카메라 원본 이미지, Parquet, RAG 원본)
                         └─ FastMCP HTTP (센서·비전·예측·분석 도구)
Host model runner ── RTMDet TensorRT / Timestral CPU (one process at a time)
```

대화 이력은 `storage/state/mirgam.db`의 SQLite에 저장됩니다. 카메라 원본은
`storage/raw/images/` 같은 SSD 파일 경로에 두고 SQLite에는 경로·촬영시각·해시·비전
추론 결과만 저장합니다. 이 방식은 8 GB Jetson에서 상시 S3 서버를 실행하지 않습니다.

## 실행

1. Jetson Orin Nano 8 GB에서는 `scripts/install-gemma4-e2b.sh`를 한 번 실행한 뒤
   `scripts/serve-gemma4-e2b.sh`로 Gemma 4 E2B Q4 서버를 실행합니다. 이 구성은 검증된
   1K 컨텍스트와 작은 배치(16/8)를 사용하며, Jetson CUDA graph 할당 실패를 피하도록
   CUDA graphs를 기본 비활성화합니다. `curl http://127.0.0.1:8000/v1/models`로 준비 상태를
   확인할 수 있습니다.
2. `.env.example`을 `.env`로 복사합니다. 기본 `GEMMA_BASE_URL`과 `GEMMA_MODEL`은 위
   서버를 가리킵니다. endpoint는 OpenAI Chat Completions 호환이어야 합니다.
3. TensorRT/Timestral MCP 도구도 사용할 때는 별도 터미널에서 `scripts/serve-model-runner.sh`를
   실행합니다.
4. `docker compose --env-file .env -f infra/compose.yaml up --build`를 실행합니다.
5. 브라우저에서 <http://localhost:3100>을 엽니다.

`GEMMA_BASE_URL`의 기본값은 Jetson 호스트의 추론 서버에 접속하는 주소입니다. Beacon 서버는
`services/beacon`에 포함되어 `docker compose up`으로 API·웹과 함께 실행됩니다. ESP32가 보내는
체크인 포트 `8080`만 호스트에 공개하고, 인증 없는 관리 API `8081`은 Compose 내부 네트워크에서만
API 컨테이너가 호출합니다. Beacon DB와 JPEG는 `BEACON_DATA_ROOT`(기본 `/mnt/nvme/beacon`)에
보존됩니다. USB 직렬 포트(`/dev/ttyUSB*`, `/dev/ttyACM*`)도 Beacon 컨테이너에 제한된 장치 규칙으로
전달해, 로그인한 대시보드에서 포트를 확인하고 보드를 리셋한 뒤 새 Wi-Fi 체크인을 확인할 수 있습니다.
USB 리셋은 펌웨어의 Wi-Fi 자격정보나 서버 주소를 바꾸지 않습니다. Next.js BFF와 FastAPI는
Compose 서비스 DNS로 통신합니다. 모델 서버를 Compose에 포함하지 않은 이유는 모델 파일·GPU·러너가
각 개인 환경에 따라 달라서입니다.

`/health`는 llama.cpp 연결 상태, `gemma-4-e2b` 별칭, MCP 도구 발견 여부를 함께 반환합니다.
서버가 꺼져 있으면 대화 API는 원인과 시작 명령을 포함한 HTTP 503을 반환합니다.
도메인별 동작은 `.env`의 `GEMMA_SYSTEM_PROMPT`로 설정합니다. 스마트팜 요약 기본값은
출력 최대 384 토큰(`GEMMA_MAX_OUTPUT_TOKENS`)이며, 요약 속도를 위해 Gemma 4의 thinking은
기본적으로 끕니다(`GEMMA_ENABLE_THINKING=false`). 필요하면 이 값을 `true`로 바꿀 수 있습니다.
thinking을 켠 상태에서 사용자에게 보이는 답이 비어 있으면 끄고 한 번 재시도하며, 그래도 비면
대체 문구를 저장하지 않고 HTTP 502 오류를 반환합니다.

### 로그인 연동

로그인 화면은 SQLite Cloud의 기존 `accounts`를 읽기 전용으로 조회합니다. API 컨테이너의
서버 환경변수 `MIRGAM_DATABASE_URL`에 실제 연결 문자열을 설정하세요. `.env.example`의 주석을
참고해 `.env`에만 넣고, `NEXT_PUBLIC_*` 변수나 프런트엔드 설정에는 넣지 않습니다. 계정 조회는
`name`(농장명) 또는 `username`(사용자 ID), `is_active = 1` 조건을 사용하고,
`werkzeug.security.check_password_hash()`로 기존 비밀번호 해시를 검증합니다.

성공하면 API가 랜덤 세션 쿠키를 발급하고 토큰 해시와 계정 ID·농장명만 로컬
`storage/state/mirgam.db`의 `auth_sessions`에 저장합니다. 고객·주문 정보나 비밀번호 해시는 복사하지
않으며, Cloud의 `auth_sessions`도 수정하지 않습니다. 쿠키는 HttpOnly와 SameSite=Lax이고 기본
수명은 12시간입니다. HTTPS 배포에서는 `AUTH_COOKIE_SECURE=true`로 설정하세요. 로그아웃 시 로컬
세션만 폐기합니다. `/health`와 로그인 경로를 제외한 채팅·스레드·대시보드 API는 유효한 로컬 세션을
요구합니다.

로그인한 계정의 농장명은 대시보드 제목과 평면도 이름에 표시됩니다. 현재 센서·이미지·대화 데이터는
단일 로컬 SQLite에 저장되므로 계정별 데이터 분리 기능은 아직 없습니다. 여러 농장을 동시에 지원할
때는 센서·카메라·대화 행에 계정/농장 소유 범위를 추가해야 합니다.

FastAPI는 `http://localhost:8100`, MCP는 `http://localhost:8765/mcp`로 노출됩니다.

### ESP32 Beacon

Beacon 서버는 Compose의 `beacon` 서비스로 관리됩니다. ESP32 펌웨어의 `SERVER_HOST`에는 Jetson의
Wi-Fi 주소를 지정하고 `SERVER_PORT`는 `8080`을 사용합니다. 대시보드의 장치 찾기는 실제 LAN/USB
스캔이 아니라 Beacon 서버에 체크인한 목록을 새로고침합니다. 등록되지 않은 보드는 첫 체크인 후
`DISCOVERED`로 표시됩니다.

`BEACON_DATA_ROOT`(기본 `/mnt/nvme/beacon`)에 Beacon DB와 JPEG 원본을 보존합니다. API는 JPEG를
로컬 `storage/raw/beacons/`로 복사한 뒤 기존 `camera_assets`에 메타데이터를 기록합니다. 센서 결과는
SQLite 측정 기록에 저장되고, 별도 `데이터 서버` 화면에서 Beacon → 센서 CSV/이미지/체크인/명령 파일
형태로 조회합니다. USB 포트는 초기 설정 및 보드 리셋 확인용입니다. 대시보드에서 Wi-Fi 비밀번호나
펌웨어의 서버 주소를 변경하지 않습니다. 센서/이미지 요청은 ESP32의 다음 체크인 때 실행될 수 있으며,
전력 사용 값은 실측이 아닌 설정값 기반 추정치입니다.

## 디렉터리

- `apps/web`: Next.js 대화 UI와 FastAPI BFF 프록시
- `services/api`: SQLite 대화 저장, Gemma client, MCP tool orchestration
- `services/mcp`: FastMCP와 SQLite·Parquet·비전·예측 도구
- `services/model_runner`: 호스트 TensorRT/CPU 모델을 순차 실행하는 게이트웨이
- `packages/rag`: 로컬 벡터 인덱스의 인터페이스
- `storage`: SSD의 로컬 데이터 루트. 실제 데이터는 Git에 넣지 않음
- `services/beacon`: 컨테이너에서 실행하는 ESP32 HTTP 수신·관리 서버
- `infra/compose.yaml`: Web, API, MCP, Beacon의 로컬 실행 구성

## MCP 확장

`services/mcp/app/tools/`에 모듈을 추가하고 `server.py`에서 import하면 도구가
등록됩니다. 기본 `query_parquet` 도구는 `storage/silver`, `storage/gold` 아래의
Parquet만 읽으며, SELECT/WITH 쿼리만 허용합니다.

FastAPI는 Streamable HTTP MCP client입니다. 농장 데이터 질문에만 관련 도구의
function-calling schema를 제공하고, 첫 Gemma 호출은 도구 선택과 인자 생성만 합니다.
FastAPI가 MCP를 실행한 뒤 SQL에서 집계한 JSON만 넣어 두 번째 Gemma 호출이 답변합니다.
도구 프로토콜 메시지는 채팅에 저장하지 않고, 호출 인자·결과·오류는 SQLite
`mcp_tool_calls` 테이블에 기록합니다. 일반 대화에는 MCP schema를 제공하지 않습니다.

### KMA 날씨 도구

기상청 API허브의 초단기실황·초단기예보·단기예보를 MCP `get_weather` 하나로 조회합니다.
기존 HTTP MCP 서버에 등록되므로 별도 stdio 서버를 실행하지 않습니다. 루트 `.env`에
URL 인코딩하지 않은 원문 `KMA_API_KEY`를 설정하면 Compose가 해당 값을 MCP 컨테이너에만
전달하고 요청 코드가 쿼리 인코딩합니다. 조회 위치는 남원읍과 공천포이며 `scope`는
`now`, `next6h`, `forecast5d`, `all`입니다. KST 기준 발표시각을 계산하고 03 NO_DATA는
한 번 이전 발표로 재시도합니다. 같은 발표 자료는 SQLite와 메모리에서 10분 캐시합니다.

`KMA_API_KEY`가 없거나 API 호출이 실패하면 예외 대신 한국어 오류 텍스트를 반환해 Gemma가
실제 기상값을 추정하지 않게 합니다. 공천포의 격자 `(55, 33)`은 현재 후보값이며, 정확한
좌표 기반 격자 변환 API 조회로 아직 확정하지 않았습니다.

우측 대시보드의 `DATA SOURCE` 탭에서 `농장 · 로컬 DB`와 `제주 날씨 · API`를 전환할 수 있습니다.
날씨 화면은 앱에 포함된 제주 행정구역 지도를 사용하고 MCP 패키지의 `area_grids.json`으로
고유 격자별 현재 관측·강수확률을 MCP가 기상청에서 받아 색칠합니다. 지도 구역을 누르면 해당
격자의 현재 관측, 향후 6시간, 최대 5일 예보를 봅니다. 대시보드 지도·지역 예보 결과와 원본 API 응답은
`storage/state/mirgam.db`의 `kma_weather_cache`에 저장합니다. 지도·지역 자료는 최근 20분 동안 SQLite에서
바로 사용하고, 더 오래된 자료는 기상청에서 갱신합니다. 갱신에 실패하면 저장된 이전 자료를 표시하고
오래된 자료임을 알립니다.
MCP 컨테이너를 재시작해도 저장 캐시는 유지됩니다. 브라우저는 KMA 키를 받지 않습니다.

행정구역 매핑 파일의 `approx-centroid` 값은 경계 중심으로 산출한 근사 격자라 선택 지역에 안내가
표시됩니다. `남원읍`은 기상청 예시 격자를 사용하고 `공천포`는 지명 대표 좌표에서 계산한 후보
격자입니다. 농장 GPS 위치를 기준으로 하는 것이 행정구역 대표값보다 정확합니다.

## SQLite 데이터

API 시작 시 다음 테이블을 자동 생성합니다.

- `auth_sessions`: 로그인 계정 ID와 농장명, 만료시간, 세션 토큰의 해시. 평문 토큰은 DB에 저장하지 않음
- `threads`, `messages`: 대화와 메시지. `messages.trace_json`은 진행 단계와 MCP 입출력을 보존
- `farm_zones`, `sensor_devices`, `sensor_aliases`: 위치·센서·사용자 지정 센서 별칭
- `sensor_readings`, `sensor_daily_rollups`: 원시 측정 시계열과 일별 집계
- `camera_devices`, `vision_observations`, `vision_daily_rollups`: 카메라와 비전 결과
- `camera_assets`: SSD 이미지 파일의 메타데이터
- `vision_runs`: 비전 모델 실행 상태와 결과 JSON
- `kma_weather_cache`: 기상청 응답·제주 지도·선택 지역 날씨 JSON과 저장 시각
- `mcp_tool_calls`: 에이전트의 MCP 도구 호출 감사 이력

기존 메시지 테이블은 API 시작 시 `trace_json` 컬럼을 추가합니다. 이전 assistant 메시지에 연결 가능한
`mcp_tool_calls` 감사 기록이 있으면 도구 인자와 결과를 복원해 진행 패널에 표시합니다.

### Farm data layers

```text
farm_zones → sensor_devices → sensor_readings (raw, 시간별/주기별)
                              → sensor_daily_rollups (일별 min/max/mean/stddev/p05/p50/p95)

farm_zones → camera_devices → camera_assets (SSD 이미지 파일 메타데이터)
                              → vision_runs → vision_observations (개별 모델 결과)
                                             → vision_daily_rollups (일별 생육 지표)
```

MCP는 대시보드의 FastAPI가 호출하는 read-only 데이터 계층입니다. llama.cpp는 MCP에 직접 연결되지
않습니다. 센서 질문은 다음과 같은 작은 도구 집합으로 처리합니다.

- `list_sensors`: 등록 센서와 별칭 확인
- `get_sensor_snapshot`: 센서 ID·별칭·온실/베드와 센서 종류로 최신 측정값 조회
- `get_sensor_trend`: KST 날짜 단위 추이를 SQL에서 시간 버킷으로 집계해 최대 96개 지점 반환
- `get_camera_summary`: 최신 이미지 메타데이터와 날짜별 비전 집계 반환
- `detect_camera_objects`: 저장된 카메라 이미지에 RTMDet을 호출해 박스 검출과 클래스별 개수 반환
- `forecast_sensor`: Timestral-28M CPU로 센서 시계열 예측
- `get_weather`: 남원읍·공천포의 기상청 현재 관측 또는 예보를 한국어 텍스트로 반환

`temp_A_01`은 온실 A 온도 센서, `humidity_A_01`은 온실 A 습도 센서의 별칭입니다. 별칭은
`sensor_aliases`에 저장하고, 응답에는 별칭과 실제 센서 ID를 함께 포함합니다. 오늘 추이는 KST
자정부터 현재 시각까지만 반환하며, 미래 시각을 측정값처럼 만들지 않습니다.

농장 데이터 질문은 짧은 2단계 호출로 처리합니다. 첫 번째 Gemma 호출은 질문에 맞는 MCP 도구 하나를
선택하고 인자를 생성합니다. MCP가 SQLite에서 집계한 작은 JSON 결과만 두 번째 Gemma 호출에 전달하며,
두 번째 호출은 그 결과에 있는 사실만 사용해 답합니다. 일반 인사에는 MCP 도구 스키마를 보내지 않습니다.
라우팅과 답변 모두 thinking을 끄고 짧은 토큰 한도를 사용합니다. 오래된 assistant 답변은 센서 데이터
사실로 프롬프트에 다시 넣지 않습니다. 전체 대화는 SQLite에 계속 저장됩니다.

`/chat/stream`은 진행 단계, 실제 MCP 도구 호출 인자, 반환 JSON을 SSE로 전송합니다. 채팅의
접이식 진행 패널에서 최종 답변이 나오기 전에도 이 정보를 확인할 수 있습니다. 내부 reasoning 텍스트는
전달하지 않습니다. `get_camera_summary`는 최신 이미지 메타데이터와 저장된 SQLite 집계를 읽습니다.
아래 모델 MCP 도구는 이미지 분석이나 시계열 예측이 필요할 때만 실제 모델을 실행합니다.

### RTMDet / Timestral 모델 MCP 도구

TensorRT가 설치된 호스트에서 RTMDet과 Timestral을 실행하고, MCP 컨테이너는
`MODEL_RUNNER_URL`로 요청합니다. Jetson에서 별도 터미널에 모델 러너를 켜 두세요.

```bash
scripts/serve-model-runner.sh
```

기본 RTMDet 엔진은 메모리 workspace 상한 64 MiB로 빌드한
`rtmdet-tiny-coco-fp16-ws64.engine`입니다. 다시 빌드할 때는 Gemma 서버를 먼저 종료한 뒤 실행합니다.

```bash
scripts/build-rtmdet-engine-ws64.sh
```

러너는 Docker 브리지 주소에만 바인딩합니다. HTTP 요청은 한 번에 하나씩 받고, 각각의 모델을
별도 자식 프로세스에서 실행한 뒤 프로세스를 종료해 할당 메모리를 반환합니다. FastAPI도 채팅 한 턴
전체를 잠금으로 감싸 Gemma의 도구 선택, MCP 모델 실행, Gemma 답변 작성이 대시보드 요청끼리
겹치지 않게 합니다. Compose의 API는 기본 단일 worker 설정을 유지해야 합니다.

직렬 실행은 두 모델의 추론 연산을 겹치지 않게 할 뿐, 상주 중인 llama.cpp의 Gemma 가중치와 컨텍스트
메모리를 내리지는 않습니다. Jetson은 CPU/GPU가 8 GB 통합 메모리를 공유하므로 RTMDet 실행 시에도
Gemma 메모리는 남아 있습니다. 따라서 64 MiB workspace 엔진도 Gemma가 상주한 상태에서
OOM 없이 실행된다는 보장은 없으며, 실제 카메라 요청으로 확인해야 합니다.

러너 시작 로그에 나온 Docker 브리지 주소로 MCP 컨테이너에서 상태를 확인할 수 있습니다.

```bash
sudo docker compose --env-file .env -f infra/compose.yaml exec -T mcp \
  python -c 'import os,urllib.request; u=os.getenv("MODEL_RUNNER_URL"); print(urllib.request.urlopen(u+"/health",timeout=5).read().decode())'
```

- `detect_camera_objects`: 카메라의 최신 SQLite 등록 이미지를 RTMDet TensorRT FP16 엔진으로
  분석해 클래스별 박스 수, 신뢰도, 좌표를 반환합니다. 현재 엔진은 COCO-80이므로 `orange` 등은
  인식하지만 나무 클래스는 없습니다. 나무 개수를 세려면 수관 또는 줄기 중 개수 단위를 정해 박스로
  라벨링한 데이터로 RTMDet만 파인튜닝하고, TensorRT 엔진과 클래스 목록을 교체하면 됩니다.
- `forecast_sensor`: SQLite 센서 시계열을 균일한 시간 간격으로 정리하고 빠진 구간을 표시해
  Timestral-28M CPU 추론을 요청합니다. 중앙값 및 10/90 분위 예측과 데이터 커버리지를 반환합니다.

RTMDet의 박스 검출은 한 이미지 안의 후보 개체 수를 세지만, 궤적을 따라 같은 나무가 재관측되는지
추적하지 않습니다. 현장 분포를 만들 때는 RTMDet 출력에 ByteTrack 등 시간 추적을 붙이고, 카메라와
이동 궤적으로 방향/상대 위치를 계산한 뒤 중복 관측을 최적화해야 합니다. 인스턴스 마스크는 이 흐름에
필요하지 않습니다. 파인튜닝은 Orin Nano보다 별도 CUDA PC에서 진행하는 편이 안전합니다. Nano의
8 GB 통합 메모리는 실행 중인 Gemma와 공유되며 학습은 추론보다 메모리를 더 요구합니다.

대시보드는 뷰포트 높이에 맞춰 고정되고 채팅 이력과 농장 현황은 각각 내부 스크롤을 사용합니다.
넓은 화면에서는 주황색 경계선을 드래그해 패널 너비를 조절하고, 대시보드를 접어 채팅 영역만
넓혀 볼 수 있습니다. 온실 평면도에 센서와 카메라 위치를 표시하며, 위치 버튼을 선택하면 아래에서
센서 차트 또는 카메라 이미지와 요약값을 확인합니다.

이전 도구 이름을 가진 오래된 MCP 컨테이너가 남아 있다면 API와 MCP를 함께 다시 빌드하세요.

### Demo seed

다음 명령은 실제 레코드를 변경하지 않고 `demo-seed` 출처의 mock 행만 다시 만듭니다.
온도·습도·토양수분의 7일간 시간별 noisy raw 데이터 504건과 일별 집계, 그리고
`services/api/app/demo_assets/`의 세 카메라 프레임을 SSD와 SQLite `camera_assets`에 등록합니다.
API가 실행 중이면 세 demo 센서는 기본 15초 간격으로 작은 연속 노이즈값을 raw 테이블에 추가합니다.
실제 센서 수집을 연결할 때는 `.env`의 `DEMO_SIMULATOR_ENABLED=false`로 끄면 됩니다.

```bash
sudo docker compose --env-file .env -f infra/compose.yaml exec api \
  python -m app.seed_demo_data
```

API/MCP 이미지가 변경되었으므로 필요하면 아래 명령으로 다시 빌드하세요.

```bash
sudo docker compose --env-file .env -f infra/compose.yaml up --build
```

기존 SeaweedFS 채팅은 이전하지 않습니다. 이전 Compose 실행에서 남은 SeaweedFS 컨테이너는
새 구성에 포함되지 않으며, 아래 명령으로 안전하게 중지할 수 있습니다. 기존 volume은 자동으로
삭제하지 않습니다.

```bash
sudo docker compose --env-file .env -f infra/compose.yaml down --remove-orphans
```
