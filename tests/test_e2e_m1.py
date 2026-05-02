"""End-to-end acceptance for M1 cache.

Spins up a real local HTTP server serving bytes we control, then drives a
minimal fetch+cache flow:

  1. First GET on /img returns v1 bytes -> cache miss, stored.
  2. Same URL re-requested -> cache hit, server NOT touched.
  3. Server flips to v2 bytes; client forces re-download -> two versions coexist.
  4. LRU shrink: max_bytes lowered, oldest version evicted on next put.

This is the Jack-visible M1 acceptance: 同一 URL 的多版本头像演变能在 cache 里如实落两份，
重复请求不打网络，磁盘配额到顶就丢老的。

M2 will introduce the proper Downloader abstraction; until then we use stdlib
urllib inline so the e2e proves cache semantics under real HTTP.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import urllib.request

import pytest

from lmfetch.cache import Cache


def _http_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read()


class _FlippingHandler(BaseHTTPRequestHandler):
    payload = {"bytes": b"v1-original-bytes"}
    hits = {"count": 0}

    def do_GET(self):  # noqa: N802
        self.hits["count"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(self.payload["bytes"])))
        self.end_headers()
        self.wfile.write(self.payload["bytes"])

    def log_message(self, *a, **kw):
        pass


@pytest.fixture
def http_server():
    _FlippingHandler.payload["bytes"] = b"v1-original-bytes"
    _FlippingHandler.hits["count"] = 0
    srv = HTTPServer(("127.0.0.1", 0), _FlippingHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, _FlippingHandler
    finally:
        srv.shutdown()


def _fetch_or_get(cache: Cache, url: str) -> tuple[bytes, str]:
    hits = cache.get(url)
    if hits:
        return hits[0].blob_path.read_bytes(), "cache"
    body = _http_get(url)
    cache.put(url, body)
    return body, "network"


def test_e2e_m1_cache(http_server, tmp_path: Path) -> None:
    srv, handler = http_server
    host, port = srv.server_address
    url = f"http://{host}:{port}/avatar.png"

    cache = Cache(tmp_path / "cache", max_bytes=10 * 1024 * 1024)

    body1, src1 = _fetch_or_get(cache, url)
    assert src1 == "network"
    assert body1 == b"v1-original-bytes"
    assert handler.hits["count"] == 1

    body2, src2 = _fetch_or_get(cache, url)
    assert src2 == "cache"
    assert body2 == b"v1-original-bytes"
    assert handler.hits["count"] == 1, "second request must NOT hit the network"

    handler.payload["bytes"] = b"v2-rebrand-bytes-longer"
    body_v2 = _http_get(url)
    cache.put(url, body_v2)
    assert handler.hits["count"] == 2

    versions = cache.get(url)
    assert len(versions) == 2
    contents = {v.blob_path.read_bytes() for v in versions}
    assert contents == {b"v1-original-bytes", b"v2-rebrand-bytes-longer"}

    blob_root = tmp_path / "cache" / "blobs"
    blobs_on_disk = list(blob_root.rglob("*.bin"))
    assert len(blobs_on_disk) == 2

    tight = Cache(tmp_path / "cache", max_bytes=len(b"v2-rebrand-bytes-longer") + 1)
    handler.payload["bytes"] = b"v3-tiny"
    body_v3 = _http_get(url)
    tight.put(url, body_v3)

    remaining = {e.blob_path.read_bytes() for e in tight.get(url)}
    assert b"v1-original-bytes" not in remaining, "oldest must be evicted under tight quota"
    assert tight.total_bytes() <= len(b"v2-rebrand-bytes-longer") + 1
