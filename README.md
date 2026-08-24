# gemma-mcp

개인용 LLM 대시보드와 MCP 서버를 위한, 도메인 비종속 최소 프레임워크입니다.
충전기·공공 API·MySQL·OpenSearch에는 의존하지 않습니다.

## 구성

```text
Next.js Web → FastAPI → OpenAI 호환 Gemma endpoint
                    ├─ SeaweedFS S3 (대화·첨부·RAG 원본·분석 결과)
                    ├─ DuckDB (Parquet 조회)
                    ├─ 로컬 벡터 인덱스 (packages/rag, S3 백업)
                    └─ FastMCP (읽기 전용 분석 도구)
```

대화 이력은 `s3://gemma-mcp/threads/<id>.json`에 저장합니다. 개인용 단일 사용자
기준이라 별도 데이터베이스가 필요 없습니다. S3는 조회 엔진이 아니므로 분석은
MCP 서비스의 DuckDB가 Parquet를 직접 읽습니다.

## 실행

1. `.env.example`을 `.env`로 복사하고 `GEMMA_BASE_URL`, `GEMMA_MODEL`을 실행 중인
   Gemma 서버에 맞춥니다. endpoint는 OpenAI Chat Completions 호환이어야 합니다.
2. `docker compose --env-file .env -f infra/compose.yaml up --build`를 실행합니다.
3. 브라우저에서 <http://localhost:3100>을 엽니다.

`GEMMA_BASE_URL`의 기본값은 Docker Desktop에서 호스트의 추론 서버에 접속하는
주소입니다. 모델 서버를 Compose에 포함하지 않은 이유는 모델 파일·GPU·러너가
각 개인 환경에 따라 크게 달라서입니다.

SeaweedFS의 S3 API는 호스트에서 `http://localhost:8334`로 노출됩니다. 컨테이너
사이에서는 `http://seaweedfs:8333`을 사용하므로 기존 EVDW의 8333 포트와 충돌하지
않습니다.

FastAPI는 `http://localhost:8100`, MCP는 `http://localhost:8765/mcp`로 노출됩니다.

## 디렉터리

- `apps/web`: Next.js 대화 UI와 FastAPI BFF 프록시
- `services/api`: 대화 API, S3 JSON 스레드 저장, Gemma 클라이언트
- `services/mcp`: FastMCP와 안전한 DuckDB/Parquet 읽기 도구
- `packages/rag`: 로컬 벡터 인덱스의 인터페이스와 S3 백업 지점
- `storage`: SeaweedFS에 보관될 객체의 논리적 분류. 실제 데이터는 Git에 넣지 않음
- `infra/compose.yaml`: Web, API, MCP, SeaweedFS의 로컬 실행 구성

## MCP 확장

`services/mcp/app/tools/`에 모듈을 추가하고 `server.py`에서 import하면 도구가
등록됩니다. 기본 `query_parquet` 도구는 `storage/silver`, `storage/gold` 아래의
Parquet만 읽으며, SELECT/WITH 쿼리만 허용합니다.

LLM의 MCP tool-calling 연결은 사용하는 Gemma 러너의 tool-call 호환성에 따라
추가합니다. 지금 API는 도구가 없는 일반 대화를 안정적으로 제공하고, MCP는
Claude Desktop·Cursor·향후 에이전트에서 즉시 연결 가능한 독립 HTTP 서버입니다.
