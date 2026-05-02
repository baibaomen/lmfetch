"""TDD for lmfetch.cache.

API under test:
  Cache(root: Path, max_bytes: int)
    .put(url: str, content: bytes) -> CacheEntry
    .get(url: str) -> list[CacheEntry]   # newest first; bumps last_used
    .total_bytes() -> int

Filename layout:
  <root>/<urlhash[:2]>/<urlhash>/<YYYYMMDDTHHMMSS>-<contenthash[:16]>.bin

Invariants:
  - Same URL with different content produces TWO entries (multi-version).
  - Same URL with same content is idempotent (one entry, last_used bumped).
  - LRU eviction kicks in on put when total > max_bytes; oldest last_used dropped first.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


def test_put_then_get_returns_same_content(cache_dir: Path) -> None:
    from lmfetch.cache import Cache

    cache = Cache(cache_dir, max_bytes=10 * 1024 * 1024)
    entry = cache.put("https://example.com/a.png", b"hello")

    assert entry.size == 5
    assert entry.blob_path.exists()
    assert entry.blob_path.read_bytes() == b"hello"

    results = cache.get("https://example.com/a.png")
    assert len(results) == 1
    assert results[0].blob_path.read_bytes() == b"hello"


def test_same_url_different_content_keeps_both_versions(cache_dir: Path) -> None:
    from lmfetch.cache import Cache

    cache = Cache(cache_dir, max_bytes=10 * 1024 * 1024)
    cache.put("https://example.com/avatar.png", b"v1-bytes")
    cache.put("https://example.com/avatar.png", b"v2-different")

    results = cache.get("https://example.com/avatar.png")
    assert len(results) == 2
    contents = {r.blob_path.read_bytes() for r in results}
    assert contents == {b"v1-bytes", b"v2-different"}


def test_same_url_same_content_is_idempotent(cache_dir: Path) -> None:
    from lmfetch.cache import Cache

    cache = Cache(cache_dir, max_bytes=10 * 1024 * 1024)
    e1 = cache.put("https://example.com/a.png", b"same")
    e2 = cache.put("https://example.com/a.png", b"same")

    assert e1.blob_path == e2.blob_path
    assert len(cache.get("https://example.com/a.png")) == 1


def test_get_returns_newest_first(cache_dir: Path) -> None:
    from lmfetch.cache import Cache

    cache = Cache(cache_dir, max_bytes=10 * 1024 * 1024)
    cache.put("https://example.com/a.png", b"older")
    cache.put("https://example.com/a.png", b"newer")

    results = cache.get("https://example.com/a.png")
    assert results[0].blob_path.read_bytes() == b"newer"
    assert results[1].blob_path.read_bytes() == b"older"


def test_get_unknown_url_returns_empty(cache_dir: Path) -> None:
    from lmfetch.cache import Cache

    cache = Cache(cache_dir, max_bytes=10 * 1024 * 1024)
    assert cache.get("https://example.com/nope.png") == []


def test_lru_eviction_drops_oldest(cache_dir: Path) -> None:
    from lmfetch.cache import Cache

    cache = Cache(cache_dir, max_bytes=20)
    cache.put("https://a/", b"AAAAAAAAAA")  # 10 bytes
    cache.put("https://b/", b"BBBBBBBBBB")  # 10 bytes -> total 20
    # touch A so B is now oldest by last_used
    cache.get("https://a/")
    cache.put("https://c/", b"CCCCCCCCCC")  # 10 bytes -> evict B

    assert cache.get("https://a/") != []
    assert cache.get("https://b/") == []
    assert cache.get("https://c/") != []
    assert cache.total_bytes() <= 20


def test_persists_across_instances(cache_dir: Path) -> None:
    from lmfetch.cache import Cache

    c1 = Cache(cache_dir, max_bytes=10 * 1024 * 1024)
    c1.put("https://example.com/p.png", b"persisted")

    c2 = Cache(cache_dir, max_bytes=10 * 1024 * 1024)
    results = c2.get("https://example.com/p.png")
    assert len(results) == 1
    assert results[0].blob_path.read_bytes() == b"persisted"
