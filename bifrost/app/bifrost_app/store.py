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
"""


class Store:
    """Thread-safe wrapper around a small SQLite database."""

    def __init__(self, path: str, retention_days: int = 90) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)
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

    def prune(self) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat()
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM decisions WHERE ts < ?", (cutoff,))
        return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()
