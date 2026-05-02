"""Content-addressed image cache with multi-version per URL and LRU eviction.

Layout on disk:
    <root>/blobs/<urlhash[:2]>/<urlhash>/<YYYYMMDDTHHMMSS>-<contenthash[:16]>.bin
    <root>/index.sqlite3

Same URL with different bytes produces multiple entries (avatar-evolution use case).
Same URL + same bytes is idempotent (last_used is bumped).
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class CacheEntry:
    url: str
    url_hash: str
    content_hash: str
    blob_path: Path
    size: int
    created_at: float
    last_used: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    url_hash     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    url          TEXT NOT NULL,
    blob_path    TEXT NOT NULL,
    size         INTEGER NOT NULL,
    created_at   REAL NOT NULL,
    last_used    REAL NOT NULL,
    PRIMARY KEY (url_hash, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_entries_url_hash ON entries (url_hash);
CREATE INDEX IF NOT EXISTS idx_entries_last_used ON entries (last_used);
"""


class Cache:
    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self.root = Path(root)
        self.max_bytes = int(max_bytes)
        self.blobs_dir = self.root / "blobs"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self.root / "index.sqlite3"
        self._conn = sqlite3.connect(self._db_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def put(self, url: str, content: bytes) -> CacheEntry:
        url_hash = _sha256_hex(url)
        content_hash = _sha256_hex(content)
        now = time.time()

        row = self._conn.execute(
            "SELECT blob_path, size, created_at FROM entries WHERE url_hash=? AND content_hash=?",
            (url_hash, content_hash),
        ).fetchone()
        if row is not None:
            blob_path = Path(row[0])
            self._conn.execute(
                "UPDATE entries SET last_used=? WHERE url_hash=? AND content_hash=?",
                (now, url_hash, content_hash),
            )
            return CacheEntry(
                url=url,
                url_hash=url_hash,
                content_hash=content_hash,
                blob_path=blob_path,
                size=row[1],
                created_at=row[2],
                last_used=now,
            )

        blob_dir = self.blobs_dir / url_hash[:2] / url_hash
        blob_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        blob_path = blob_dir / f"{ts}-{content_hash[:16]}.bin"
        if not blob_path.exists():
            blob_path.write_bytes(content)
        size = len(content)

        self._conn.execute(
            "INSERT INTO entries(url_hash, content_hash, url, blob_path, size, created_at, last_used)"
            " VALUES(?,?,?,?,?,?,?)",
            (url_hash, content_hash, url, str(blob_path), size, now, now),
        )

        self._evict_if_needed()
        return CacheEntry(
            url=url,
            url_hash=url_hash,
            content_hash=content_hash,
            blob_path=blob_path,
            size=size,
            created_at=now,
            last_used=now,
        )

    def get(self, url: str) -> list[CacheEntry]:
        url_hash = _sha256_hex(url)
        rows = self._conn.execute(
            "SELECT content_hash, blob_path, size, created_at, last_used"
            " FROM entries WHERE url_hash=? ORDER BY created_at DESC",
            (url_hash,),
        ).fetchall()
        if not rows:
            return []

        now = time.time()
        self._conn.execute(
            "UPDATE entries SET last_used=? WHERE url_hash=?", (now, url_hash)
        )
        return [
            CacheEntry(
                url=url,
                url_hash=url_hash,
                content_hash=ch,
                blob_path=Path(bp),
                size=sz,
                created_at=ca,
                last_used=now,
            )
            for (ch, bp, sz, ca, _lu) in rows
        ]

    def total_bytes(self) -> int:
        row = self._conn.execute("SELECT COALESCE(SUM(size), 0) FROM entries").fetchone()
        return int(row[0])

    def _evict_if_needed(self) -> None:
        while self.total_bytes() > self.max_bytes:
            row = self._conn.execute(
                "SELECT url_hash, content_hash, blob_path FROM entries"
                " ORDER BY last_used ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return
            url_hash, content_hash, blob_path = row
            try:
                Path(blob_path).unlink(missing_ok=True)
            except OSError:
                pass
            self._conn.execute(
                "DELETE FROM entries WHERE url_hash=? AND content_hash=?",
                (url_hash, content_hash),
            )
