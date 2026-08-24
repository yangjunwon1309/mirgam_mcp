"""A deliberately small, read-only DuckDB tool surface."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from ..mcp_app import mcp

ROOT = Path(os.getenv("PARQUET_ROOT", "/workspace/storage")).resolve()
ALLOWED_AREAS = ("silver", "gold")


def _sql_is_read_only(sql: str) -> bool:
    compact = sql.strip().lower()
    if not compact.startswith(("select", "with")):
        return False
    blocked = ("attach", "copy", "create", "delete", "drop", "insert", "install", "load", "update")
    return not any(token in compact for token in blocked)


@mcp.tool()
def list_parquet_files(area: str = "gold") -> list[str]:
    """List available Parquet data files from the silver or gold logical storage area."""
    if area not in ALLOWED_AREAS:
        raise ValueError("area must be 'silver' or 'gold'")
    directory = (ROOT / area).resolve()
    if ROOT not in directory.parents:
        raise ValueError("invalid storage area")
    return sorted(str(path.relative_to(ROOT)) for path in directory.rglob("*.parquet"))


@mcp.tool()
def query_parquet(sql: str) -> dict[str, object]:
    """Run a SELECT/WITH DuckDB query over approved local Parquet paths.

    Use paths rooted at /workspace/storage/silver or /workspace/storage/gold, for example:
    SELECT * FROM read_parquet('/workspace/storage/gold/events.parquet') LIMIT 20
    """
    if not _sql_is_read_only(sql):
        raise ValueError("Only SELECT or WITH read-only SQL is allowed")
    if "/workspace/storage/" not in sql:
        raise ValueError("Queries must reference a Parquet file below /workspace/storage")
    if any(f"/workspace/storage/{area}" in sql for area in ALLOWED_AREAS) is False:
        raise ValueError("Only silver and gold Parquet areas are readable")

    with duckdb.connect(":memory:", read_only=False) as connection:
        result = connection.execute(sql)
        columns = [column[0] for column in result.description]
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchmany(1_000)]
    return {"columns": columns, "rows": rows, "truncated": len(rows) == 1_000}

