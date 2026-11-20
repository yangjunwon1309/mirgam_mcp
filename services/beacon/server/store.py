"""Thread-safe SQLite persistence for the beacon service."""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes(
  id TEXT PRIMARY KEY, label TEXT, state TEXT NOT NULL,
  token TEXT, token_sent INTEGER DEFAULT 0,
  interval_s INTEGER DEFAULT 300, watch_until REAL, session_req_s INTEGER DEFAULT 0,
  first_seen REAL, last_seen REAL, next_given INTEGER,
  last_ip TEXT, last_rssi INTEGER, last_vbat_mv INTEGER, last_seq INTEGER, fw TEXT);
CREATE TABLE IF NOT EXISTS commands(
  id INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT NOT NULL, type TEXT NOT NULL,
  params TEXT, state TEXT NOT NULL, reason TEXT,
  created_at REAL, dispatched_at REAL, attempts INTEGER DEFAULT 0,
  done_at REAL, expires_at REAL);
CREATE TABLE IF NOT EXISTS readings(
  id INTEGER PRIMARY KEY, node_id TEXT, cmd_id INTEGER UNIQUE, received_at REAL, body TEXT);
CREATE TABLE IF NOT EXISTS images(
  id INTEGER PRIMARY KEY, node_id TEXT, cmd_id INTEGER UNIQUE, received_at REAL,
  path TEXT, bytes INTEGER, width INTEGER, height INTEGER, warm_ms INTEGER);
CREATE TABLE IF NOT EXISTS checkins(
  id INTEGER PRIMARY KEY, node_id TEXT, received_at REAL, seq INTEGER, boot TEXT,
  vbat_mv INTEGER, rssi INTEGER, wifi_ms INTEGER, fast INTEGER,
  prev_awake_ms INTEGER, prev_result TEXT, next_given INTEGER);
CREATE INDEX IF NOT EXISTS commands_node_state ON commands(node_id,state,id);
CREATE INDEX IF NOT EXISTS commands_expiry ON commands(state,expires_at);
CREATE INDEX IF NOT EXISTS checkins_node_time ON checkins(node_id,received_at);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            str(self.db_path), timeout=10, isolation_level=None, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript(SCHEMA)

    def close(self) -> None:
        with self.lock:
            self.db.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def ensure_node(self, node_id: str, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with self._write() as db:
            db.execute(
                "INSERT OR IGNORE INTO nodes(id,state,first_seen,interval_s) VALUES(?,?,?,?)",
                (node_id, "DISCOVERED", now, 300),
            )
            return self._dict(db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()) or {}

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self._dict(self.db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone())

    def list_nodes(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM nodes ORDER BY id").fetchall()
            return [dict(row) for row in rows]

    def register_checkin(
        self,
        node_id: str,
        body: dict[str, Any],
        ip: str,
        supplied_token: str,
        now: float,
    ) -> tuple[str, dict[str, Any] | None, str | None]:
        """Authenticate/update a check-in and atomically consume a one-shot token."""
        with self._write() as db:
            row = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO nodes(id,state,first_seen,interval_s) VALUES(?,?,?,?)",
                    (node_id, "DISCOVERED", now, 300),
                )
                if supplied_token:
                    return "unauthorized", None, None
                row = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()

            stored_token = row["token"]
            token_sent = bool(row["token_sent"])
            state = row["state"]
            if stored_token and token_sent:
                if supplied_token == stored_token:
                    pass
                elif supplied_token:
                    return "unauthorized", None, None
                else:
                    # A tokenless retry after a lost/stale token returns the node to
                    # DISCOVERED; an administrator must attach it again.
                    db.execute(
                        "UPDATE nodes SET token=NULL,token_sent=0,state='DISCOVERED',"
                        "session_req_s=0,watch_until=NULL WHERE id=?",
                        (node_id,),
                    )
                    db.execute(
                        "UPDATE commands SET state='expired',reason='token_reset',done_at=? "
                        "WHERE node_id=? AND state IN ('queued','dispatched')",
                        (now, node_id),
                    )
                    state = "DISCOVERED"
            elif stored_token and not token_sent:
                if supplied_token and supplied_token != stored_token:
                    return "unauthorized", None, None
            elif supplied_token:
                return "unauthorized", None, None

            token_row = db.execute("SELECT token,token_sent,state FROM nodes WHERE id=?", (node_id,)).fetchone()
            issue_token = None
            if token_row["state"] == "ATTACHED" and token_row["token"] and not token_row["token_sent"]:
                issue_token = str(token_row["token"])
                db.execute("UPDATE nodes SET token_sent=1 WHERE id=?", (node_id,))

            db.execute(
                "UPDATE nodes SET last_seen=?,last_ip=?,last_rssi=?,last_vbat_mv=?,last_seq=?,fw=? WHERE id=?",
                (
                    now, ip, body.get("rssi"), body.get("vbat_mv"), body.get("seq"),
                    body.get("fw"), node_id,
                ),
            )
            updated = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
            return "ok", dict(updated), issue_token

    def record_checkin(self, node_id: str, body: dict[str, Any], next_given: int, now: float) -> None:
        timing = body.get("t") or {}
        with self._write() as db:
            db.execute("UPDATE nodes SET next_given=? WHERE id=?", (next_given, node_id))
            db.execute(
                "INSERT INTO checkins(node_id,received_at,seq,boot,vbat_mv,rssi,wifi_ms,fast,"
                "prev_awake_ms,prev_result,next_given) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    node_id, now, body.get("seq"), body.get("boot"), body.get("vbat_mv"),
                    body.get("rssi"), timing.get("wifi_ms"), timing.get("fast"),
                    timing.get("prev_awake_ms"), timing.get("prev_result"), next_given,
                ),
            )

    def consume_session_request(self, node_id: str) -> int:
        with self._write() as db:
            row = db.execute("SELECT session_req_s FROM nodes WHERE id=?", (node_id,)).fetchone()
            value = int(row[0] or 0) if row else 0
            if value:
                db.execute("UPDATE nodes SET session_req_s=0 WHERE id=?", (node_id,))
            return value

    def attach(self, node_id: str, label: str | None, interval_s: int) -> dict[str, Any] | None:
        with self._write() as db:
            row = db.execute("SELECT id FROM nodes WHERE id=?", (node_id,)).fetchone()
            if row is None:
                return None
            token = secrets.token_hex(16)
            db.execute(
                "UPDATE nodes SET state='ATTACHED',label=COALESCE(?,label),interval_s=?,"
                "token=?,token_sent=0,watch_until=NULL,session_req_s=0 WHERE id=?",
                (label, interval_s, token, node_id),
            )
            return self._dict(db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone())

    def detach(self, node_id: str, now: float) -> bool:
        with self._write() as db:
            if db.execute("SELECT 1 FROM nodes WHERE id=?", (node_id,)).fetchone() is None:
                return False
            db.execute(
                "UPDATE nodes SET state='DETACHED',token=NULL,token_sent=0,watch_until=NULL,session_req_s=0 WHERE id=?",
                (node_id,),
            )
            db.execute(
                "UPDATE commands SET state='expired',reason='detached',done_at=? "
                "WHERE node_id=? AND state IN ('queued','dispatched')",
                (now, node_id),
            )
            return True

    def set_interval(self, node_id: str, interval_s: int) -> bool:
        with self._write() as db:
            cur = db.execute(
                "UPDATE nodes SET interval_s=? WHERE id=? AND state='ATTACHED'",
                (interval_s, node_id),
            )
            return cur.rowcount == 1

    def set_watch(self, node_id: str, watch_until: float) -> bool:
        with self._write() as db:
            cur = db.execute(
                "UPDATE nodes SET watch_until=? WHERE id=? AND state='ATTACHED'",
                (watch_until, node_id),
            )
            return cur.rowcount == 1

    def set_session(self, node_id: str, hold_s: int) -> bool:
        with self._write() as db:
            cur = db.execute(
                "UPDATE nodes SET session_req_s=? WHERE id=? AND state='ATTACHED'",
                (hold_s, node_id),
            )
            return cur.rowcount == 1

    def expire_node_commands(self, node_id: str, now: float, reason: str = "detached") -> None:
        with self._write() as db:
            db.execute(
                "UPDATE commands SET state='expired',reason=?,done_at=? "
                "WHERE node_id=? AND state IN ('queued','dispatched')",
                (reason, now, node_id),
            )

    def create_command(
        self, node_id: str, command_type: str, params: dict[str, Any], now: float
    ) -> int | None:
        with self._write() as db:
            node = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
            if node is None or node["state"] != "ATTACHED":
                return None
            next_given = int(node["next_given"] or node["interval_s"] or 300)
            expires_at = now + max(2 * next_given, 900)
            cur = db.execute(
                "INSERT INTO commands(node_id,type,params,state,created_at,attempts,expires_at) "
                "VALUES(?,?,?,'queued',?,0,?)",
                (node_id, command_type, json.dumps(params, separators=(",", ":")), now, expires_at),
            )
            return int(cur.lastrowid)

    def dispatch_commands(self, node_id: str, now: float, limit: int = 4) -> list[dict[str, Any]]:
        with self._write() as db:
            db.execute(
                "UPDATE commands SET state='expired',reason='expired',done_at=? "
                "WHERE node_id=? AND state IN ('queued','dispatched') AND expires_at<=?",
                (now, node_id, now),
            )
            db.execute(
                "UPDATE commands SET state='failed',reason='no_result',done_at=? "
                "WHERE node_id=? AND state='dispatched' AND attempts>=3 AND dispatched_at<=?",
                (now, node_id, now - 120),
            )
            node = db.execute("SELECT state FROM nodes WHERE id=?", (node_id,)).fetchone()
            if node is None or node["state"] != "ATTACHED":
                return []
            rows = db.execute(
                "SELECT * FROM commands WHERE node_id=? AND expires_at>? AND (state='queued' OR "
                "(state='dispatched' AND dispatched_at<=? AND attempts<3)) ORDER BY id LIMIT ?",
                (node_id, now, now - 120, limit),
            ).fetchall()
            out = []
            for row in rows:
                db.execute(
                    "UPDATE commands SET state='dispatched',dispatched_at=?,attempts=attempts+1 WHERE id=?",
                    (now, row["id"]),
                )
                updated = db.execute("SELECT * FROM commands WHERE id=?", (row["id"],)).fetchone()
                item = dict(updated)
                try:
                    item["params"] = json.loads(item["params"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    item["params"] = {}
                out.append(item)
            return out

    def fail_queued_images_low_battery(self, node_id: str, now: float) -> None:
        with self._write() as db:
            db.execute(
                "UPDATE commands SET state='failed',reason='low_battery',done_at=? "
                "WHERE node_id=? AND type='image' AND state='queued'",
                (now, node_id),
            )

    def get_command(self, cmd_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM commands WHERE id=?", (cmd_id,)).fetchone()
            if row is None:
                return None
            item = dict(row)
            try:
                item["params"] = json.loads(item["params"] or "{}")
            except (TypeError, json.JSONDecodeError):
                item["params"] = {}
            return item

    def get_command_result(self, cmd_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT body FROM readings WHERE cmd_id=?", (cmd_id,)).fetchone()
            if row is not None:
                try:
                    return {"kind": "reading", "body": json.loads(row["body"])}
                except json.JSONDecodeError:
                    return {"kind": "reading", "body": row["body"]}
            row = self.db.execute(
                "SELECT path,bytes,width,height,warm_ms,received_at FROM images WHERE cmd_id=?",
                (cmd_id,),
            ).fetchone()
            return {"kind": "image", **dict(row)} if row is not None else None

    def has_result(self, cmd_id: int) -> bool:
        with self.lock:
            return self.db.execute(
                "SELECT 1 FROM readings WHERE cmd_id=? UNION SELECT 1 FROM images WHERE cmd_id=?",
                (cmd_id, cmd_id),
            ).fetchone() is not None

    def save_reading(
        self, node_id: str, cmd_id: int, received_at: float, body: dict[str, Any]
    ) -> str:
        with self._write() as db:
            existing = db.execute(
                "SELECT node_id FROM readings WHERE cmd_id=? UNION SELECT node_id FROM images WHERE cmd_id=?",
                (cmd_id, cmd_id),
            ).fetchone()
            if existing:
                return "dup" if existing["node_id"] == node_id else "not_found"
            command = db.execute("SELECT * FROM commands WHERE id=?", (cmd_id,)).fetchone()
            if command is None or command["node_id"] != node_id:
                return "not_found"
            encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            db.execute(
                "INSERT INTO readings(node_id,cmd_id,received_at,body) VALUES(?,?,?,?)",
                (node_id, cmd_id, received_at, encoded),
            )
            ok = bool(body.get("ok"))
            reason = None if ok else str(body.get("err", "result_failed"))[:120]
            db.execute(
                "UPDATE commands SET state=?,reason=?,done_at=? WHERE id=?",
                ("done" if ok else "failed", reason, received_at, cmd_id),
            )
            if command["type"] == "hibernate" and ok:
                db.execute(
                    "UPDATE nodes SET state='HIBERNATING',token=NULL,token_sent=0 WHERE id=?",
                    (node_id,),
                )
                db.execute(
                    "UPDATE commands SET state='expired',reason='hibernating',done_at=? "
                    "WHERE node_id=? AND id<>? AND state IN ('queued','dispatched')",
                    (received_at, node_id, cmd_id),
                )
            return "inserted"

    def save_image(
        self,
        node_id: str,
        cmd_id: int,
        received_at: float,
        path: str,
        size: int,
        width: int,
        height: int,
        warm_ms: int | None,
    ) -> str:
        with self._write() as db:
            existing = db.execute(
                "SELECT node_id FROM readings WHERE cmd_id=? UNION SELECT node_id FROM images WHERE cmd_id=?",
                (cmd_id, cmd_id),
            ).fetchone()
            if existing:
                return "dup" if existing["node_id"] == node_id else "not_found"
            command = db.execute("SELECT * FROM commands WHERE id=?", (cmd_id,)).fetchone()
            if command is None or command["node_id"] != node_id:
                return "not_found"
            db.execute(
                "INSERT INTO images(node_id,cmd_id,received_at,path,bytes,width,height,warm_ms) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (node_id, cmd_id, received_at, path, size, width, height, warm_ms),
            )
            db.execute(
                "UPDATE commands SET state='done',reason=NULL,done_at=? WHERE id=?",
                (received_at, cmd_id),
            )
            return "inserted"

    def energy_rows(self, node_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM checkins WHERE node_id=? ORDER BY received_at DESC LIMIT ?",
                (node_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def daily_command_counts(self, node_id: str, since: float) -> dict[str, int]:
        with self.lock:
            rows = self.db.execute(
                "SELECT type,COUNT(*) AS n FROM commands WHERE node_id=? AND created_at>=? "
                "GROUP BY type",
                (node_id, since),
            ).fetchall()
            return {str(row["type"]): int(row["n"]) for row in rows}
