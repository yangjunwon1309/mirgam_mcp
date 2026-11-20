# Local SSD storage rules

| Logical area | Contents | Read/write owner |
| --- | --- | --- |
| `raw/images/` | Camera originals | camera ingestion service |
| `raw/` | Other originals and unmodified logs | API / optional gateway |
| `silver/` | Normalized Parquet | ingestion jobs |
| `gold/` | Analysis-ready Parquet | transformation jobs |
| `rag/` | Documents, chunks, index backups | RAG worker |
| `state/mirgam.db` | SQLite: local auth sessions, chat, sensor, image metadata, tool audits | API |
| `state/` | Other checkpoints and processing manifests | relevant worker |

The local SSD is the durable source of truth. The API mounts `storage/` read/write for
SQLite and future camera ingestion. MCP mounts the general storage tree read-only for
DuckDB; only `storage/state/` is separately writable so SQLite WAL readers can open its
`-wal` and `-shm` companions. MCP code still opens the database in `mode=ro` with
`PRAGMA query_only`. Never place raw image bytes inside SQLite: store the relative file
path and metadata in `camera_assets` instead.

## SQLite farm data layers

- `farm_zones` → `sensor_devices` → `sensor_readings`: immutable-ish raw events, one
  row per measurement timestamp.
- `sensor_daily_rollups`: re-computable local-day aggregates; never overwrite raw data.
- `farm_zones` → `camera_devices` → `camera_assets`: image file location and capture
  metadata, while the bytes remain under `raw/images/`.
- `vision_runs` → `vision_observations`: a model's per-image output.
- `vision_daily_rollups`: re-computable daily canopy/count/confidence/alert summaries.

Raw and derived records carry a `source` field. The development seed uses `demo-seed`,
so it can be deleted and recreated without touching data from real farm devices.
