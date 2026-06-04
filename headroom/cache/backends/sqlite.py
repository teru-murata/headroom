"""SQLite storage backend for the local CCR CompressionStore.

This backend is intended for local, single-host workflows that need CCR entries
to survive a process restart. It is not a hosted/team namespace or
authorization policy.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..compression_store import CompressionEntry


class SQLiteBackend:
    """SQLite-backed CompressionStore backend for local durability."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        busy_timeout_ms: int = 5000,
        wal: bool = True,
    ) -> None:
        self.db_path = self._normalize_db_path(db_path)
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._wal = wal
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    @staticmethod
    def _normalize_db_path(db_path: str | Path) -> str:
        value = str(db_path)
        if value.startswith("sqlite:///"):
            value = value.removeprefix("sqlite:///")
        if value == ":memory:":
            return value
        return str(Path(value).expanduser())

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.db_path != ":memory:":
                Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                self.db_path,
                timeout=self._busy_timeout_ms / 1000,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
            if self._wal and self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.execute("PRAGMA synchronous = NORMAL")
        return self._conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ccr_entries (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    last_accessed_at REAL,
                    access_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ccr_entries_expires_at ON ccr_entries(expires_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ccr_entries_created_at ON ccr_entries(created_at)"
            )
            conn.commit()

    def get(self, hash_key: str) -> CompressionEntry | None:
        """Retrieve an entry by key without applying TTL policy."""
        with self._lock:
            row = (
                self._get_conn()
                .execute(
                    "SELECT * FROM ccr_entries WHERE key = ?",
                    (hash_key,),
                )
                .fetchone()
            )
            if row is None:
                return None
            return self._row_to_entry(row)

    def set(self, hash_key: str, entry: CompressionEntry) -> None:
        """Store or replace an entry."""
        metadata = self._entry_metadata(entry)
        expires_at = self._expires_at(entry)
        with self._lock:
            self._get_conn().execute(
                """
                INSERT OR REPLACE INTO ccr_entries (
                    key,
                    value,
                    metadata_json,
                    created_at,
                    expires_at,
                    last_accessed_at,
                    access_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hash_key,
                    entry.original_content,
                    json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                    entry.created_at,
                    expires_at,
                    entry.last_accessed,
                    entry.retrieval_count,
                ),
            )
            self._get_conn().commit()

    def delete(self, hash_key: str) -> bool:
        """Delete an entry by key."""
        with self._lock:
            cursor = self._get_conn().execute(
                "DELETE FROM ccr_entries WHERE key = ?",
                (hash_key,),
            )
            self._get_conn().commit()
            return cursor.rowcount > 0

    def exists(self, hash_key: str) -> bool:
        """Return True if the key is present, without applying TTL policy."""
        with self._lock:
            row = (
                self._get_conn()
                .execute(
                    "SELECT 1 FROM ccr_entries WHERE key = ? LIMIT 1",
                    (hash_key,),
                )
                .fetchone()
            )
            return row is not None

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._get_conn().execute("DELETE FROM ccr_entries")
            self._get_conn().commit()

    def count(self) -> int:
        """Return the number of stored rows."""
        with self._lock:
            row = self._get_conn().execute("SELECT COUNT(*) FROM ccr_entries").fetchone()
            return int(row[0]) if row is not None else 0

    def keys(self) -> list[str]:
        """Return all stored keys."""
        with self._lock:
            rows = self._get_conn().execute("SELECT key FROM ccr_entries ORDER BY key").fetchall()
            return [str(row["key"]) for row in rows]

    def items(self) -> list[tuple[str, CompressionEntry]]:
        """Return all stored entries as ``(key, entry)`` pairs."""
        with self._lock:
            rows = self._get_conn().execute("SELECT * FROM ccr_entries ORDER BY key").fetchall()
            return [(str(row["key"]), self._row_to_entry(row)) for row in rows]

    def cleanup_expired(self, now: float) -> int:
        """Delete rows whose SQLite expiry timestamp has passed."""
        with self._lock:
            cursor = self._get_conn().execute(
                "DELETE FROM ccr_entries WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            self._get_conn().commit()
            return int(cursor.rowcount)

    def get_stats(self) -> dict[str, Any]:
        """Return backend-specific statistics."""
        with self._lock:
            conn = self._get_conn()
            entry_count = self.count()
            bytes_used_row = conn.execute(
                """
                SELECT COALESCE(SUM(
                    length(key) + length(value) + length(metadata_json)
                ), 0)
                FROM ccr_entries
                """
            ).fetchone()
            db_bytes = 0
            if self.db_path != ":memory:":
                db_file = Path(self.db_path)
                if db_file.exists():
                    db_bytes = db_file.stat().st_size
            return {
                "backend_type": "sqlite",
                "entry_count": entry_count,
                "bytes_used": int(bytes_used_row[0]) if bytes_used_row else 0,
                "db_path": self.db_path,
                "db_file_bytes": db_bytes,
            }

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @staticmethod
    def _entry_metadata(entry: CompressionEntry) -> dict[str, Any]:
        return {
            "compressed_content": entry.compressed_content,
            "original_tokens": entry.original_tokens,
            "compressed_tokens": entry.compressed_tokens,
            "original_item_count": entry.original_item_count,
            "compressed_item_count": entry.compressed_item_count,
            "tool_name": entry.tool_name,
            "tool_call_id": entry.tool_call_id,
            "query_context": entry.query_context,
            "ttl": entry.ttl,
            "tool_signature_hash": entry.tool_signature_hash,
            "compression_strategy": entry.compression_strategy,
            "search_queries": list(entry.search_queries),
        }

    @staticmethod
    def _expires_at(entry: CompressionEntry) -> float | None:
        ttl = entry.ttl
        if ttl is None:
            return None
        return float(entry.created_at) + float(ttl)

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> CompressionEntry:
        from ..compression_store import CompressionEntry

        metadata = json.loads(row["metadata_json"])
        return CompressionEntry(
            hash=str(row["key"]),
            original_content=str(row["value"]),
            compressed_content=str(metadata.get("compressed_content", "")),
            original_tokens=int(metadata.get("original_tokens", 0)),
            compressed_tokens=int(metadata.get("compressed_tokens", 0)),
            original_item_count=int(metadata.get("original_item_count", 0)),
            compressed_item_count=int(metadata.get("compressed_item_count", 0)),
            tool_name=metadata.get("tool_name"),
            tool_call_id=metadata.get("tool_call_id"),
            query_context=metadata.get("query_context"),
            created_at=float(row["created_at"]),
            ttl=int(metadata.get("ttl", 300)),
            tool_signature_hash=metadata.get("tool_signature_hash"),
            compression_strategy=metadata.get("compression_strategy"),
            retrieval_count=int(row["access_count"] or 0),
            search_queries=list(metadata.get("search_queries") or []),
            last_accessed=row["last_accessed_at"],
        )
