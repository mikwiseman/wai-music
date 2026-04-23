"""SQLite-backed cache and playlist history store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class SQLiteCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS api_cache (
                    url TEXT PRIMARY KEY,
                    ttl INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS playlists_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    backend TEXT NOT NULL,
                    playlist_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(playlists_history)").fetchall()
            }
            if "user_id" not in columns:
                connection.execute("ALTER TABLE playlists_history ADD COLUMN user_id TEXT")

    def get_json(self, url: str) -> Any | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json, ttl, fetched_at FROM api_cache WHERE url = ?",
                (url,),
            ).fetchone()
            if row is None:
                return None
            fetched_at = datetime.fromisoformat(str(row["fetched_at"]))
            expires_at = fetched_at + timedelta(seconds=int(row["ttl"]))
            if expires_at <= datetime.now(UTC):
                connection.execute("DELETE FROM api_cache WHERE url = ?", (url,))
                return None
            return json.loads(str(row["payload_json"]))

    def set_json(self, url: str, payload: Any, ttl_seconds: int) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO api_cache(url, ttl, payload_json, fetched_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    ttl = excluded.ttl,
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at
                """,
                (url, ttl_seconds, json.dumps(payload), now),
            )

    def delete(self, url: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM api_cache WHERE url = ?", (url,))

    def record_playlist(
        self,
        *,
        user_id: str | None = None,
        backend: str,
        playlist_id: str,
        slug: str,
        created_at: datetime | None = None,
    ) -> None:
        timestamp = (created_at or datetime.now(UTC)).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO playlists_history(user_id, backend, playlist_id, slug, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (user_id, backend, playlist_id, slug, timestamp),
            )

    def list_playlists(self, *, user_id: str | None = None) -> list[dict[str, str]]:
        with self._connect() as connection:
            if user_id is None:
                rows = connection.execute(
                    """
                    SELECT id, user_id, backend, playlist_id, slug, created_at
                    FROM playlists_history
                    ORDER BY id ASC
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, user_id, backend, playlist_id, slug, created_at
                    FROM playlists_history
                    WHERE user_id = ?
                    ORDER BY id ASC
                    """,
                    (user_id,),
                ).fetchall()
        return [dict(row) for row in rows]
