"""Local storage (SQLite in /data). Nothing leaves the Home Assistant host."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

from .categories import STATUSES, is_valid_category, is_valid_role

SCHEMA = """
CREATE TABLE IF NOT EXISTS entity_settings (
    entity_id TEXT PRIMARY KEY,
    status    TEXT NOT NULL,
    category  TEXT,
    role      TEXT,
    updated   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    ts         TEXT NOT NULL,
    state      TEXT NOT NULL,
    confidence INTEGER NOT NULL,
    reasons    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE TABLE IF NOT EXISTS events (
    ts        TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL,
    role      TEXT NOT NULL,
    state     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS trust (
    entity_id TEXT PRIMARY KEY,
    agree     INTEGER NOT NULL DEFAULT 0,
    disagree  INTEGER NOT NULL DEFAULT 0,
    updated   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patterns (
    id        TEXT PRIMARY KEY,
    data      TEXT NOT NULL,
    status    TEXT NOT NULL,
    baseline  REAL,
    seen      TEXT NOT NULL,
    updated   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar_stats (
    calendar_id TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    updated     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS objects (
    kind    TEXT NOT NULL,
    id      TEXT NOT NULL,
    data    TEXT NOT NULL,
    updated TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS map_versions (
    kind    TEXT NOT NULL,
    floor   TEXT NOT NULL,
    version INTEGER NOT NULL,
    data    TEXT NOT NULL,
    created TEXT NOT NULL,
    source  TEXT NOT NULL,
    label   TEXT,
    summary TEXT,
    pinned  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, floor, version)
);
CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    """Thread-safe wrapper around a small SQLite database."""

    def __init__(self, path: str, retention_days: int = 90) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(events)").fetchall()}
        if "kind" not in cols:  # 0.4: edge kind (on/off/home/away/gap/change)
            self._db.execute("ALTER TABLE events ADD COLUMN kind TEXT NOT NULL DEFAULT ''")
            self._db.commit()
        self.retention_days = retention_days

    # --- user overrides --------------------------------------------------------
    def get_overrides(self) -> dict[str, dict[str, str | None]]:
        with self._lock:
            rows = self._db.execute("SELECT entity_id, status, category, role FROM entity_settings").fetchall()
        return {r[0]: {"status": r[1], "category": r[2], "role": r[3]} for r in rows}

    def set_override(self, entity_id: str, status: str, category: str | None, role: str | None) -> None:
        if status not in STATUSES:
            raise ValueError("invalid status")
        if not is_valid_category(category) or not is_valid_role(role):
            raise ValueError("invalid category or role")
        now = datetime.now(UTC).isoformat()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO entity_settings(entity_id, status, category, role, updated) VALUES (?,?,?,?,?) "
                "ON CONFLICT(entity_id) DO UPDATE SET status=excluded.status, category=excluded.category, "
                "role=excluded.role, updated=excluded.updated",
                (entity_id, status, category, role, now),
            )

    # --- decision history ----------------------------------------------------
    def add_decision(self, ts: datetime, state: str, confidence: int, reasons: list[str]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO decisions(ts, state, confidence, reasons) VALUES (?,?,?,?)",
                (ts.isoformat(), state, int(confidence), json.dumps(reasons, ensure_ascii=False)),
            )

    def history(self, hours: int = 24) -> list[dict]:
        since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        with self._lock:
            rows = self._db.execute("SELECT ts, state, confidence FROM decisions WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
        return [{"ts": r[0], "state": r[1], "confidence": r[2]} for r in rows]

    def decisions_since(self, since: datetime) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT ts, state, confidence FROM decisions WHERE ts >= ? ORDER BY ts", (since.isoformat(),)).fetchall()
        return [{"ts": r[0], "state": r[1], "confidence": r[2]} for r in rows]

    # --- generic objects (0.4: people, questions, deviations, labels, learned blocks) ---
    def put_obj(self, kind: str, oid: str, data: dict) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO objects(kind, id, data, updated) VALUES (?,?,?,?) ON CONFLICT(kind, id) DO UPDATE SET data=excluded.data, updated=excluded.updated",
                (kind, oid, json.dumps(data, ensure_ascii=False), now),
            )

    def get_obj(self, kind: str, oid: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM objects WHERE kind=? AND id=?", (kind, oid)).fetchone()
        return json.loads(row[0]) if row else None

    def list_objs(self, kind: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM objects WHERE kind=? ORDER BY id", (kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    # --- versions of the house configuration (0.18) ------------------------------------------------
    def add_version(self, kind: str, floor: str, data: dict, source: str, summary: dict | None = None, keep: int = 50) -> int:
        """Store a new version; keep the newest ``keep`` unpinned ones (pinned versions are never removed)."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._db:
            row = self._db.execute("SELECT COALESCE(MAX(version), 0) FROM map_versions WHERE kind=? AND floor=?", (kind, floor)).fetchone()
            v = int(row[0]) + 1
            self._db.execute(
                "INSERT INTO map_versions(kind, floor, version, data, created, source, summary) VALUES (?,?,?,?,?,?,?)",
                (kind, floor, v, json.dumps(data, ensure_ascii=False), now, source, json.dumps(summary or {})),
            )
            self._db.execute(
                "DELETE FROM map_versions WHERE kind=? AND floor=? AND pinned=0 AND version NOT IN "
                "(SELECT version FROM map_versions WHERE kind=? AND floor=? AND pinned=0 ORDER BY version DESC LIMIT ?)",
                (kind, floor, kind, floor, keep),
            )
        return v

    def list_versions(self, kind: str, floor: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT version, created, source, label, summary, pinned FROM map_versions WHERE kind=? AND floor=? ORDER BY version DESC", (kind, floor)).fetchall()
        return [{"version": r[0], "created": r[1], "source": r[2], "label": r[3], "summary": json.loads(r[4] or "{}"), "pinned": bool(r[5])} for r in rows]

    def get_version(self, kind: str, floor: str, version: int) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM map_versions WHERE kind=? AND floor=? AND version=?", (kind, floor, version)).fetchone()
        return json.loads(row[0]) if row else None

    def pin_version(self, kind: str, floor: str, version: int, pinned: bool, label: str | None) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("UPDATE map_versions SET pinned=?, label=? WHERE kind=? AND floor=? AND version=?", (int(pinned), label, kind, floor, version))
        return cur.rowcount > 0

    def del_obj(self, kind: str, oid: str) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM objects WHERE kind=? AND id=?", (kind, oid))
        return cur.rowcount > 0

    def del_kind(self, kind: str) -> int:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM objects WHERE kind=?", (kind,))
        return cur.rowcount

    # --- signal events (state changes of used signals) ----------------------
    def add_event(self, ts: datetime, entity_id: str, name: str, category: str, role: str, state: str, kind: str = "") -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO events(ts, entity_id, name, category, role, state, kind) VALUES (?,?,?,?,?,?,?)",
                (ts.astimezone(UTC).isoformat(), entity_id, name[:120], category, role, (state or "")[:64], kind[:12]),
            )

    def events_since(self, since: datetime, limit: int = 2000) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, entity_id, name, category, role, state, kind FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                (since.astimezone(UTC).isoformat(), int(limit)),
            ).fetchall()
        return [{"ts": r[0], "entity_id": r[1], "name": r[2], "category": r[3], "role": r[4], "state": r[5], "kind": r[6]} for r in rows]

    def count_events_since(self, since: datetime) -> int:
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) FROM events WHERE ts >= ?", (since.astimezone(UTC).isoformat(),)).fetchone()
        return int(row[0]) if row else 0

    def distinct_states(self, entity_ids: list[str], since: datetime, limit: int = 30, kind: str | None = None) -> list[str]:
        """Distinct recent values of some entities, newest first (e.g. users reported by an access system)."""
        if not entity_ids:
            return []
        marks = ",".join("?" * len(entity_ids))
        with self._lock:
            rows = self._db.execute(
                f"SELECT state, MAX(ts) AS t FROM events WHERE entity_id IN ({marks}) AND ts >= ? AND (? IS NULL OR kind = ?) GROUP BY state ORDER BY t DESC LIMIT ?",  # noqa: S608  # nosec B608 – only placeholders
                (*entity_ids, since.astimezone(UTC).isoformat(), kind, kind, int(limit)),
            ).fetchall()
        return [r[0] for r in rows if r[0] and r[0].lower() not in ("unknown", "unavailable", "none", "")]

    # --- learned trust per signal -------------------------------------------
    def add_trust(self, entity_id: str, agree: int, disagree: int) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO trust(entity_id, agree, disagree, updated) VALUES (?,?,?,?) "
                "ON CONFLICT(entity_id) DO UPDATE SET agree=agree+excluded.agree, disagree=disagree+excluded.disagree, updated=excluded.updated",
                (entity_id, int(agree), int(disagree), now),
            )

    def get_trust(self) -> dict[str, tuple[int, int]]:
        with self._lock:
            rows = self._db.execute("SELECT entity_id, agree, disagree FROM trust").fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    # --- patterns ------------------------------------------------------------
    def get_patterns(self) -> dict[str, dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, data, status, baseline, seen, updated FROM patterns").fetchall()
        return {r[0]: {"data": json.loads(r[1]), "status": r[2], "baseline": r[3], "seen": r[4], "updated": r[5]} for r in rows}

    def upsert_pattern(self, pid: str, data: dict, status: str, baseline: float | None, seen: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO patterns(id, data, status, baseline, seen, updated) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data, status=excluded.status, baseline=excluded.baseline, seen=excluded.seen, updated=excluded.updated",
                (pid, json.dumps(data, ensure_ascii=False), status, baseline, seen, now),
            )

    # --- calendar statistics (keywords only, never full titles) ---------------
    def set_calendar_stats(self, calendar_id: str, data: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO calendar_stats(calendar_id, data, updated) VALUES (?,?,?) ON CONFLICT(calendar_id) DO UPDATE SET data=excluded.data, updated=excluded.updated",
                (calendar_id, json.dumps(data, ensure_ascii=False), datetime.now(UTC).isoformat()),
            )

    def get_calendar_stats(self) -> dict[str, dict]:
        with self._lock:
            rows = self._db.execute("SELECT calendar_id, data, updated FROM calendar_stats").fetchall()
        return {r[0]: {**json.loads(r[1]), "updated": r[2]} for r in rows}

    # --- small key/value state (guest mode, learning bookkeeping) ------------
    def get_value(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_value(self, key: str, value: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO app_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def prune(self) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat()
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM decisions WHERE ts < ?", (cutoff,))
            cur2 = self._db.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        return cur.rowcount + cur2.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()
