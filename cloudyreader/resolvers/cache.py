"""sqlite cache for entity resolutions: hits live 30 days, misses 1 day, failures never."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from cloudyreader.models import Resolution

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resolutions (
    key        TEXT PRIMARY KEY,
    status     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    canonical  TEXT,
    ids        TEXT NOT NULL,
    source     TEXT NOT NULL,
    query      TEXT NOT NULL,
    expires_at REAL NOT NULL
)
"""
_COLUMNS = "status, kind, canonical, ids, source, query"


def _normalize(key: str) -> str:
    return key.strip().casefold()


def _decode(row: tuple) -> Resolution | None:
    status, kind, canonical, ids, source, query = row
    try:
        decoded = json.loads(ids)
    except ValueError:
        return None
    if not isinstance(decoded, dict):
        return None
    return Resolution(query, kind, canonical, decoded, source, status)


class ResolutionCache:
    """Thread-safe: one connection behind a lock. Any sqlite failure degrades to a cache miss.

    Only `ok` and `not_found` are stored. `timeout`, `offline` and `error` describe the moment, not
    the name, so `put` drops them and the next call looks the name up again.
    """

    def __init__(
        self,
        path: Path,
        *,
        hit_ttl_s: float = 2_592_000,
        miss_ttl_s: float = 86_400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl = {"ok": hit_ttl_s, "not_found": miss_ttl_s}
        self._clock = clock
        self._lock = threading.Lock()
        self._conn = self._open(Path(path))

    def _open(self, path: Path) -> sqlite3.Connection | None:
        conn = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Autocommit: each statement is its own transaction, so the lock is the only guard.
            conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(_SCHEMA)
            conn.execute("DELETE FROM resolutions WHERE expires_at <= ?", (self._clock(),))
            return conn
        except (OSError, sqlite3.Error) as exc:
            log.warning(
                "resolution cache disabled, every lookup goes to the source (%s): %s", path, exc
            )
            if conn is not None:
                conn.close()
            return None

    def get(self, key: str) -> Resolution | None:
        norm, now = _normalize(key), self._clock()
        with self._lock:
            if self._conn is None:
                return None
            try:
                row = self._conn.execute(
                    f"SELECT {_COLUMNS}, expires_at FROM resolutions WHERE key = ?", (norm,)
                ).fetchone()
                if row is None:
                    return None
                found = None if row[-1] <= now else _decode(row[:-1])
                if found is None:
                    self._conn.execute("DELETE FROM resolutions WHERE key = ?", (norm,))
                return found
            except sqlite3.Error as exc:
                log.warning("resolution cache read failed, treating as a miss: %s", exc)
                return None

    def put(self, key: str, resolution: Resolution) -> None:
        ttl = self._ttl.get(resolution.status)
        if ttl is None:
            return
        values = (
            _normalize(key),
            resolution.status,
            resolution.kind,
            resolution.canonical,
            json.dumps(dict(resolution.ids), sort_keys=True, ensure_ascii=False),
            resolution.source,
            resolution.query,
            self._clock() + ttl,
        )
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.execute(
                    f"INSERT OR REPLACE INTO resolutions (key, {_COLUMNS}, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
            except sqlite3.Error as exc:
                log.warning("resolution cache write failed, entry not stored: %s", exc)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
