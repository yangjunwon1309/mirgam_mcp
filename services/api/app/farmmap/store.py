from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FarmMapStore:
    """Geographic metadata stored alongside the app's existing local SQLite data."""

    def __init__(self, database_path: str | Path, data_root: str | Path | None = None) -> None:
        self.database_path = Path(database_path)
        # The database and imagery share DATA_ROOT in Docker. Deriving it from
        # the default ``.../state/mirgam.db`` path also keeps direct callers
        # compatible while allowing persisted image paths to be relocatable.
        self.data_root = Path(data_root) if data_root is not None else self.database_path.parent.parent

    def _resolve_imagery_path(self, boundary_id: str, value: object) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        path = Path(value)
        candidates = [path] if path.is_absolute() else [self.data_root / path]
        # Older builds persisted the container mount path. If DATA_ROOT changes,
        # remap the suffix beginning at ``imagery`` into the current data root.
        if path.is_absolute() and "imagery" in path.parts:
            imagery_index = path.parts.index("imagery")
            candidates.append(self.data_root.joinpath(*path.parts[imagery_index:]))
        # Last-resort recovery for legacy absolute paths with an unexpected root.
        candidates.append(self.data_root / "imagery" / boundary_id / path.name)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS geo_farms (
                    id TEXT PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    address_input TEXT,
                    pnu TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS geo_farms_account_idx ON geo_farms(account_id, created_at);
                CREATE TABLE IF NOT EXISTS geo_boundaries (
                    id TEXT PRIMARY KEY,
                    farm_id TEXT NOT NULL REFERENCES geo_farms(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    geojson TEXT NOT NULL,
                    area_m2 REAL NOT NULL,
                    perimeter_m REAL NOT NULL,
                    edges_json TEXT NOT NULL,
                    imagery_zoom INTEGER,
                    imagery_path TEXT,
                    imagery_transform_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(farm_id, version)
                );
                CREATE INDEX IF NOT EXISTS geo_boundaries_farm_idx ON geo_boundaries(farm_id, version DESC);
                CREATE TABLE IF NOT EXISTS geo_routes (
                    id TEXT PRIMARY KEY,
                    farm_id TEXT NOT NULL REFERENCES geo_farms(id) ON DELETE CASCADE,
                    boundary_id TEXT NOT NULL REFERENCES geo_boundaries(id),
                    label TEXT,
                    geojson TEXT NOT NULL,
                    length_m REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS geo_routes_farm_idx ON geo_routes(farm_id, created_at);
                CREATE TABLE IF NOT EXISTS geo_tile_cache (
                    layer TEXT NOT NULL,
                    z INTEGER NOT NULL,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    status INTEGER NOT NULL,
                    PRIMARY KEY(layer, z, x, y)
                );
                CREATE TABLE IF NOT EXISTS geo_boundary_tiles (
                    boundary_id TEXT NOT NULL REFERENCES geo_boundaries(id) ON DELETE CASCADE,
                    z INTEGER NOT NULL,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    PRIMARY KEY(boundary_id, z, x, y)
                );
                CREATE TABLE IF NOT EXISTS geo_geocode_usage (
                    local_date TEXT PRIMARY KEY,
                    request_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS geo_jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    result_ref TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS geo_jobs_queue_idx ON geo_jobs(status, created_at);
                """
            )

    def list_farms(self, account_id: int) -> list[dict[str, object]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM geo_farms WHERE account_id=? ORDER BY created_at DESC", (account_id,)
            ).fetchall()
            return [self._farm_dict(db, dict(row)) for row in rows]

    def create_farm(self, account_id: int, name: str, address: str | None, pnu: str | None) -> dict[str, object]:
        farm_id = str(uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO geo_farms(id,account_id,name,address_input,pnu,created_at) VALUES(?,?,?,?,?,?)",
                (farm_id, account_id, name.strip(), address.strip() if address else None, pnu, _now()),
            )
            return self._farm_dict(db, dict(db.execute("SELECT * FROM geo_farms WHERE id=?", (farm_id,)).fetchone()))

    def get_farm(self, account_id: int, farm_id: str) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM geo_farms WHERE id=? AND account_id=?", (farm_id, account_id)).fetchone()
            return self._farm_dict(db, dict(row)) if row else None

    def update_farm(self, account_id: int, farm_id: str, changes: dict[str, object]) -> dict[str, object] | None:
        columns = {"name", "address_input", "pnu"}
        updates = [(key, value) for key, value in changes.items() if key in columns]
        if not updates:
            return self.get_farm(account_id, farm_id)
        assignments = ",".join(f"{key}=?" for key, _ in updates)
        values = [value.strip() if key in {"name", "address_input"} and isinstance(value, str) else value
                  for key, value in updates]
        with self._connect() as db:
            result = db.execute(
                f"UPDATE geo_farms SET {assignments} WHERE id=? AND account_id=?",
                (*values, farm_id, account_id),
            )
            if not result.rowcount:
                return None
            row = db.execute("SELECT * FROM geo_farms WHERE id=?", (farm_id,)).fetchone()
            return self._farm_dict(db, dict(row))

    def _farm_dict(self, db: sqlite3.Connection, farm: dict[str, object]) -> dict[str, object]:
        boundary = db.execute(
            "SELECT * FROM geo_boundaries WHERE farm_id=? ORDER BY version DESC LIMIT 1", (farm["id"],)
        ).fetchone()
        routes = db.execute(
            "SELECT * FROM geo_routes WHERE farm_id=? ORDER BY created_at", (farm["id"],)
        ).fetchall()
        return {
            **farm,
            "latest_boundary": self._boundary_with_imagery(db, dict(boundary)) if boundary else None,
            "routes": [self._route_dict(dict(row)) for row in routes],
        }

    def list_boundaries(self, account_id: int, farm_id: str) -> list[dict[str, object]] | None:
        with self._connect() as db:
            if not self._owns_farm(db, account_id, farm_id):
                return None
            rows = db.execute(
                "SELECT * FROM geo_boundaries WHERE farm_id=? ORDER BY version DESC", (farm_id,)
            ).fetchall()
            return [self._boundary_with_imagery(db, dict(row)) for row in rows]

    def create_boundary(
        self, account_id: int, farm_id: str, geometry: dict[str, object], area_m2: float,
        perimeter_m: float, edges: list[dict[str, object]], imagery_zoom: int | None,
    ) -> dict[str, object] | None:
        boundary_id = str(uuid4())
        with self._connect() as db:
            if not self._owns_farm(db, account_id, farm_id):
                return None
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM geo_boundaries WHERE farm_id=?", (farm_id,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO geo_boundaries(id,farm_id,version,geojson,area_m2,perimeter_m,edges_json,imagery_zoom,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (boundary_id, farm_id, version, json.dumps(geometry, ensure_ascii=False), area_m2,
                 perimeter_m, json.dumps(edges, ensure_ascii=False), imagery_zoom, _now()),
            )
            job_id = str(uuid4())
            db.execute(
                "INSERT INTO geo_jobs(id,kind,params_json,status,progress,result_ref,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (job_id, "imagery_crop", json.dumps({"boundary_id": boundary_id}), "queued", 0,
                 boundary_id, _now(), _now()),
            )
            row = db.execute("SELECT * FROM geo_boundaries WHERE id=?", (boundary_id,)).fetchone()
            result = self._boundary_with_imagery(db, dict(row))
            result["imagery"]["job_id"] = job_id
            return result

    def queue_boundary_tiles(self, account_id: int, boundary_id: str, force: bool = False) -> dict[str, object] | None:
        """Queue or reuse a tile-pyramid job for an existing owned boundary."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT b.* FROM geo_boundaries b JOIN geo_farms f ON f.id=b.farm_id "
                "WHERE b.id=? AND f.account_id=?",
                (boundary_id, account_id),
            ).fetchone()
            if not row:
                return None
            active = db.execute(
                "SELECT id,status FROM geo_jobs WHERE kind='imagery_crop' AND result_ref=? "
                "AND status IN ('queued','running') ORDER BY rowid DESC LIMIT 1",
                (boundary_id,),
            ).fetchone()
            if active:
                result = self._boundary_with_imagery(db, dict(row))
                result["imagery"]["job_id"] = active["id"]
                result["imagery"]["status"] = active["status"]
                return result
            transform_json = row["imagery_transform_json"]
            existing_transform = json.loads(str(transform_json)) if transform_json else None
            if not force and self._has_screen_tile_pyramid(existing_transform):
                return self._boundary_with_imagery(db, dict(row))
            job_id = str(uuid4())
            now = _now()
            db.execute(
                "INSERT INTO geo_jobs(id,kind,params_json,status,progress,result_ref,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (job_id, "imagery_crop", json.dumps({"boundary_id": boundary_id}), "queued", 0,
                 boundary_id, now, now),
            )
            result = self._boundary_with_imagery(db, dict(row))
            result["imagery"].update({"status": "queued", "job_id": job_id, "progress": 0.0, "error": None})
            return result

    def create_route(
        self, account_id: int, farm_id: str, boundary_id: str, label: str | None,
        geometry: dict[str, object], length_m: float,
    ) -> dict[str, object] | None:
        route_id = str(uuid4())
        with self._connect() as db:
            boundary = db.execute(
                "SELECT b.id FROM geo_boundaries b JOIN geo_farms f ON f.id=b.farm_id "
                "WHERE b.id=? AND b.farm_id=? AND f.account_id=?",
                (boundary_id, farm_id, account_id),
            ).fetchone()
            if not boundary:
                return None
            db.execute(
                "INSERT INTO geo_routes(id,farm_id,boundary_id,label,geojson,length_m,created_at) VALUES(?,?,?,?,?,?,?)",
                (route_id, farm_id, boundary_id, label.strip() if label else None,
                 json.dumps(geometry, ensure_ascii=False), length_m, _now()),
            )
            return self._route_dict(dict(db.execute("SELECT * FROM geo_routes WHERE id=?", (route_id,)).fetchone()))

    def delete_route(self, account_id: int, route_id: str) -> bool:
        with self._connect() as db:
            result = db.execute(
                "DELETE FROM geo_routes WHERE id=? AND farm_id IN "
                "(SELECT id FROM geo_farms WHERE account_id=?)", (route_id, account_id)
            )
            return result.rowcount > 0

    def get_tile(self, layer: str, z: int, x: int, y: int) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM geo_tile_cache WHERE layer=? AND z=? AND x=? AND y=?", (layer, z, x, y)
            ).fetchone()
            return dict(row) if row else None

    def put_tile(self, layer: str, z: int, x: int, y: int, path: str, status: int) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO geo_tile_cache(layer,z,x,y,path,fetched_at,status) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(layer,z,x,y) DO UPDATE SET path=excluded.path,fetched_at=excluded.fetched_at,status=excluded.status",
                (layer, z, x, y, path, _now(), status),
            )

    def record_geocode_call(self) -> int:
        local_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        with self._connect() as db:
            db.execute(
                "INSERT INTO geo_geocode_usage(local_date,request_count) VALUES(?,1) "
                "ON CONFLICT(local_date) DO UPDATE SET request_count=request_count+1", (local_date,)
            )
            row = db.execute("SELECT request_count FROM geo_geocode_usage WHERE local_date=?", (local_date,)).fetchone()
            return int(row[0])

    def claim_next_job(self) -> dict[str, object] | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM geo_jobs WHERE status='queued' AND kind='imagery_crop' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            db.execute("UPDATE geo_jobs SET status='running',progress=0.05,updated_at=? WHERE id=?", (_now(), row["id"]))
            job = dict(row)
            job["status"] = "running"
            return job

    def requeue_interrupted_jobs(self) -> None:
        with self._connect() as db:
            db.execute("UPDATE geo_jobs SET status='queued',updated_at=? WHERE kind='imagery_crop' AND status='running'", (_now(),))

    def queue_legacy_boundary_pyramids(self) -> int:
        """Rebuild old small crop extents into the screen-sized lazy tile format."""
        queued = 0
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id,imagery_transform_json FROM geo_boundaries "
                "WHERE imagery_transform_json IS NOT NULL OR imagery_path IS NOT NULL"
            ).fetchall()
            for row in rows:
                transform = json.loads(str(row["imagery_transform_json"])) if row["imagery_transform_json"] else None
                if self._has_screen_tile_pyramid(transform):
                    continue
                active = db.execute(
                    "SELECT 1 FROM geo_jobs WHERE kind='imagery_crop' AND result_ref=? "
                    "AND status IN ('queued','running') LIMIT 1", (row["id"],)
                ).fetchone()
                if active:
                    continue
                now = _now()
                db.execute(
                    "INSERT INTO geo_jobs(id,kind,params_json,status,progress,result_ref,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (str(uuid4()), "imagery_crop", json.dumps({"boundary_id": row["id"]}),
                     "queued", 0, row["id"], now, now),
                )
                queued += 1
        return queued

    def boundary_for_crop(self, boundary_id: str) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM geo_boundaries WHERE id=?", (boundary_id,)).fetchone()
            if not row:
                return None
            boundary = dict(row)
            boundary["geojson"] = json.loads(str(boundary["geojson"]))
            return boundary

    def update_job_progress(self, job_id: str, progress: float) -> None:
        with self._connect() as db:
            db.execute("UPDATE geo_jobs SET progress=?,updated_at=? WHERE id=? AND status='running'", (max(0, min(progress, 1)), _now(), job_id))

    def complete_crop(
        self, job_id: str, boundary_id: str, raw_path: str | None,
        transform: dict[str, object], tiles: list[tuple[int, int, int]],
    ) -> None:
        with self._connect() as db:
            db.executemany(
                "INSERT OR IGNORE INTO geo_boundary_tiles(boundary_id,z,x,y) VALUES(?,?,?,?)",
                [(boundary_id, z, x, y) for z, x, y in tiles],
            )
            db.execute("UPDATE geo_boundaries SET imagery_path=?,imagery_transform_json=? WHERE id=?",
                       (raw_path, json.dumps(transform), boundary_id))
            db.execute("UPDATE geo_jobs SET status='done',progress=1,error=NULL,updated_at=? WHERE id=?", (_now(), job_id))

    def boundary_tile(self, account_id: int, boundary_id: str, z: int, x: int, y: int) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT c.path FROM geo_boundary_tiles bt "
                "JOIN geo_boundaries b ON b.id=bt.boundary_id "
                "JOIN geo_farms f ON f.id=b.farm_id "
                "JOIN geo_tile_cache c ON c.layer='Satellite' AND c.z=bt.z AND c.x=bt.x AND c.y=bt.y "
                "WHERE bt.boundary_id=? AND bt.z=? AND bt.x=? AND bt.y=? AND f.account_id=? AND c.status=200",
                (boundary_id, z, x, y, account_id),
            ).fetchone()
            return str(row["path"]) if row else None

    def fail_job(self, job_id: str, message: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE geo_jobs SET status='failed',error=?,updated_at=? WHERE id=?", (message[:500], _now(), job_id))

    def get_job(self, account_id: int, job_id: str) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT j.* FROM geo_jobs j JOIN geo_boundaries b ON b.id=j.result_ref "
                "JOIN geo_farms f ON f.id=b.farm_id WHERE j.id=? AND f.account_id=?", (job_id, account_id)
            ).fetchone()
            if not row:
                return None
            job = dict(row)
            job["params"] = json.loads(str(job.pop("params_json")))
            return job

    def boundary_imagery(self, account_id: int, boundary_id: str) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT b.* FROM geo_boundaries b JOIN geo_farms f ON f.id=b.farm_id "
                "WHERE b.id=? AND f.account_id=?", (boundary_id, account_id)
            ).fetchone()
            return self._boundary_with_imagery(db, dict(row)) if row else None

    def boundary_zoom_image(self, account_id: int, boundary_id: str, zoom: int) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT b.imagery_transform_json FROM geo_boundaries b "
                "JOIN geo_farms f ON f.id=b.farm_id WHERE b.id=? AND f.account_id=?",
                (boundary_id, account_id),
            ).fetchone()
            if not row or not row["imagery_transform_json"]:
                return None
            transform = json.loads(str(row["imagery_transform_json"]))
            pyramid = transform.get("tile_pyramid") if isinstance(transform, dict) else None
            levels = pyramid.get("zooms") if isinstance(pyramid, dict) else None
            level = levels.get(str(zoom)) if isinstance(levels, dict) else None
            image_path = level.get("image_path") if isinstance(level, dict) else None
            resolved = self._resolve_imagery_path(boundary_id, image_path)
            return str(resolved) if resolved else None

    @staticmethod
    def _owns_farm(db: sqlite3.Connection, account_id: int, farm_id: str) -> bool:
        return db.execute("SELECT 1 FROM geo_farms WHERE id=? AND account_id=?", (farm_id, account_id)).fetchone() is not None

    @staticmethod
    def _boundary_dict(row: dict[str, object]) -> dict[str, object]:
        row["geojson"] = json.loads(str(row["geojson"]))
        row["edges"] = json.loads(str(row.pop("edges_json")))
        return row

    def _has_screen_tile_pyramid(self, transform: object) -> bool:
        pyramid = transform.get("tile_pyramid") if isinstance(transform, dict) else None
        if (not isinstance(pyramid, dict) or pyramid.get("coverage_aligned") is not True
                or pyramid.get("coverage_mode") != "cached_slippy_tiles_v2"):
            return False
        try:
            min_zoom, max_zoom = int(pyramid["min_zoom"]), int(pyramid["max_zoom"])
        except (KeyError, TypeError, ValueError):
            return False
        levels = pyramid.get("zooms")
        return isinstance(levels, dict) and all(
            isinstance(levels.get(str(zoom)), dict)
            and all(isinstance(levels[str(zoom)].get(key), (int, float)) for key in
                    ("pixel_left", "pixel_top", "pixel_right", "pixel_bottom", "width", "height"))
            and levels[str(zoom)]["width"] > 0 and levels[str(zoom)]["height"] > 0
            for zoom in range(min_zoom, max_zoom + 1)
        )

    def _boundary_with_imagery(self, db: sqlite3.Connection, row: dict[str, object]) -> dict[str, object]:
        job = db.execute(
            "SELECT id,status,progress,error FROM geo_jobs WHERE kind='imagery_crop' AND result_ref=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        raw_path = row.pop("imagery_path", None)
        transform_json = row.pop("imagery_transform_json", None)
        result = self._boundary_dict(row)
        transform = json.loads(str(transform_json)) if transform_json else None
        public_transform = json.loads(json.dumps(transform)) if isinstance(transform, dict) else transform
        public_pyramid = public_transform.get("tile_pyramid") if isinstance(public_transform, dict) else None
        public_levels = public_pyramid.get("zooms") if isinstance(public_pyramid, dict) else None
        if isinstance(public_levels, dict):
            for level in public_levels.values():
                if isinstance(level, dict):
                    stored_path = level.pop("image_path", None)
                    if stored_path is not None:
                        level["image_available"] = self._resolve_imagery_path(str(row["id"]), stored_path) is not None
        raw_image = self._resolve_imagery_path(str(row["id"]), raw_path)
        result["imagery"] = {
            "status": job["status"] if job else ("done" if raw_image else "not_requested"),
            "job_id": job["id"] if job else None,
            "progress": job["progress"] if job else (1.0 if raw_image else 0.0),
            "error": job["error"] if job else None,
            "available": raw_image is not None,
            # The viewer requires a screen-sized Z13 ground extent with matching
            # lazy-tile coverage at every configured zoom.
            "tiles_available": self._has_screen_tile_pyramid(transform),
            "transform": public_transform,
        }
        return result

    @staticmethod
    def _route_dict(row: dict[str, object]) -> dict[str, object]:
        row["geojson"] = json.loads(str(row["geojson"]))
        return row
