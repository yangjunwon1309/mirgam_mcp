# Local RAG index boundary

이 디렉터리는 API와 분리된 RAG 구현 경계입니다. 초기에는 `hnswlib` 또는 FAISS
인덱스를 API 호스트의 로컬 디스크에 만들고, 아래 두 파일을 SeaweedFS의
`rag/index/` 접두사에 백업합니다.

- `index.bin`: 벡터 인덱스 스냅샷
- `manifest.json`: 임베딩 모델명, 차원, 청크 ID와 원본 S3 object key

원본 문서는 S3 `rag/raw/`, 청크는 `rag/chunks/*.jsonl`에 둡니다. 인덱스를 여러
프로세스에서 동시에 갱신해야 하거나 고가용성이 필요할 때만 별도 벡터 DB를 도입합니다.

