# Storage rules

| Logical area | Contents | Read/write owner |
| --- | --- | --- |
| `raw/` | Upload originals and unmodified logs | API / optional gateway |
| `silver/` | Normalized Parquet | ingestion jobs |
| `gold/` | Analysis-ready Parquet | transformation jobs |
| `rag/` | Documents, chunks, index backups | RAG worker |
| `state/` | Checkpoints and processing manifests | relevant worker |

SeaweedFS is the durable source of truth. The local files mounted into the MCP service
are a working mirror for DuckDB; synchronize any files that should be queryable.

