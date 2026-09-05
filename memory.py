"""
memory.py
---------
Persistent local memory for AI Storage Analyzer.

Everything is stored in a local SQLite database. Nothing here ever leaves
the machine. This module is responsible for:

  * Remembering every file/folder/bundle that has been scanned before
    (so re-scans are faster and recommendations can improve over time).
  * Remembering what the user decided to do with an item (deleted / kept
    / ignored) so future recommendations can learn from real behaviour.
  * Helping recognise a file that has moved or been duplicated elsewhere
    on disk, by matching name + extension + size (and fingerprint when
    available) instead of only the exact path.

The schema is intentionally simple (three tables) so it stays easy to
reason about.
"""

import sqlite3
import threading
import time
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    name TEXT,
    extension TEXT,
    node_type TEXT,            -- 'file' | 'bundle' | 'folder'
    category TEXT,
    size INTEGER,
    created REAL,
    modified REAL,
    accessed REAL,
    fingerprint TEXT,
    importance INTEGER,
    junk_probability INTEGER,
    status TEXT,
    reason TEXT,
    last_scanned REAL,
    still_exists INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_items_fingerprint ON items(fingerprint);
CREATE INDEX IF NOT EXISTS idx_items_name_ext_size ON items(name, extension, size);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT,
    name TEXT,
    extension TEXT,
    category TEXT,
    fingerprint TEXT,
    decision TEXT,              -- 'deleted' | 'kept' | 'ignored'
    timestamp REAL
);

CREATE INDEX IF NOT EXISTS idx_decisions_cat_ext ON decisions(category, extension);
CREATE INDEX IF NOT EXISTS idx_decisions_fingerprint ON decisions(fingerprint);

CREATE TABLE IF NOT EXISTS duplicate_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT,
    path TEXT,
    size INTEGER,
    scan_time REAL
);
"""


class Memory:
    """Thin wrapper around a local SQLite database.

    A single connection is reused, guarded by a lock, because the app is
    single-process but does its scanning on a background thread.
    """

    def __init__(self, db_path="database/storage_memory.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------
    # Items (the "what did we see and what did we conclude" table)
    # ------------------------------------------------------------------

    def upsert_item(self, record: dict):
        """Insert or update the stored record for a path."""
        record = dict(record)
        record["last_scanned"] = time.time()
        fields = [
            "path", "name", "extension", "node_type", "category", "size",
            "created", "modified", "accessed", "fingerprint", "importance",
            "junk_probability", "status", "reason", "last_scanned",
        ]
        values = [record.get(f) for f in fields]
        placeholders = ",".join("?" * len(fields))
        update_clause = ",".join(f"{f}=excluded.{f}" for f in fields if f != "path")
        sql = (
            f"INSERT INTO items ({','.join(fields)}) VALUES ({placeholders}) "
            f"ON CONFLICT(path) DO UPDATE SET {update_clause}, still_exists=1"
        )
        with self._lock:
            self._conn.execute(sql, values)
            self._conn.commit()

    def get_item_by_path(self, path: str):
        with self._lock:
            cur = self._conn.execute("SELECT * FROM items WHERE path = ?", (path,))
            row = cur.fetchone()
        return dict(row) if row else None

    def find_similar_elsewhere(self, path: str, name: str, extension: str,
                                size: int, fingerprint: str = None):
        """Find a previously-seen item with the same identity but a
        different path -- i.e. the same file/app that has moved, been
        re-downloaded, or re-installed somewhere else.
        """
        with self._lock:
            if fingerprint:
                cur = self._conn.execute(
                    "SELECT * FROM items WHERE fingerprint = ? AND path != ? "
                    "ORDER BY last_scanned DESC LIMIT 1",
                    (fingerprint, path),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
            cur = self._conn.execute(
                "SELECT * FROM items WHERE name = ? AND extension = ? AND size = ? "
                "AND path != ? ORDER BY last_scanned DESC LIMIT 1",
                (name, extension, size, path),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def mark_all_missing(self, root_prefix: str):
        """Before a fresh scan of `root_prefix`, mark everything under it
        as possibly-missing; anything re-seen during the scan will be
        flipped back to still_exists=1 by upsert_item.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE items SET still_exists=0 WHERE path LIKE ?",
                (root_prefix.rstrip("\\/") + "%",),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Decisions (what the user actually chose to do)
    # ------------------------------------------------------------------

    def record_decision(self, path, name, extension, category, fingerprint, decision):
        with self._lock:
            self._conn.execute(
                "INSERT INTO decisions (path, name, extension, category, fingerprint, "
                "decision, timestamp) VALUES (?,?,?,?,?,?,?)",
                (path, name, extension, category, fingerprint, decision, time.time()),
            )
            self._conn.commit()

    def get_last_decision_for_identity(self, name, extension, fingerprint=None):
        with self._lock:
            if fingerprint:
                cur = self._conn.execute(
                    "SELECT * FROM decisions WHERE fingerprint = ? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (fingerprint,),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
            cur = self._conn.execute(
                "SELECT * FROM decisions WHERE name = ? AND extension = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (name, extension),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def get_decision_bias(self, category, extension):
        """Return how the user has historically treated this category /
        extension, e.g. {'deleted': 8, 'kept': 1, 'ignored': 0}.
        Used as a soft signal, never as an automatic rule.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT decision, COUNT(*) as n FROM decisions "
                "WHERE category = ? OR extension = ? GROUP BY decision",
                (category, extension),
            )
            rows = cur.fetchall()
        bias = {"deleted": 0, "kept": 0, "ignored": 0}
        for row in rows:
            if row["decision"] in bias:
                bias[row["decision"]] = row["n"]
        return bias

    # ------------------------------------------------------------------
    # Duplicate bookkeeping (cache of fingerprints across scans)
    # ------------------------------------------------------------------

    def record_duplicate_candidate(self, fingerprint, path, size):
        with self._lock:
            self._conn.execute(
                "INSERT INTO duplicate_groups (fingerprint, path, size, scan_time) "
                "VALUES (?,?,?,?)",
                (fingerprint, path, size, time.time()),
            )
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()
