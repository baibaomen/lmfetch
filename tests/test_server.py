"""TDD for lmfetch.server — FastAPI passthrough that rewrites image_url to data:base64.

Behaviors under test (unit-level, against fake upstream):

  - Passes through non-vision /v1/chat/completions unchanged.
  - For each `{"type":"image_url","image_url":{"url":"http..."}}` part in messages,
    fetches via Downloader, caches via Cache, and replaces the part with
    `{"type":"image_url","image_url":{"url":"data:<ct>;base64,<...>"}}` before forwarding.
  - Already-data: URLs are passed through (not re-fetched, not re-encoded).
  - Cache hit on second call to same URL — Downloader is invoked exactly once across two requests.

A separate test module (test_e2e_m3.py) drives this against the real qwen3.6 upstream.
"""
from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


def _start(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def fake_upstream():
    """Fake llama.cpp-style upstream. Echoes back the request body as 'content'."""
    last = {"body": None}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            last["body"] = json.loads(raw)
            resp = {
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "OK"}}],
                "model": "fake-upstream",
            }
            data = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, *a, **kw): pass

    srv = _start(H)
    try:
        yield srv, last
    finally:
        srv.shutdown()


@pytest.fixture
def origin_image():
    """A tiny but byte-stable image origin."""
    img_bytes = b"\x89PNG\r\n\x1a\n" + b"FAKEIMAGE" * 4
    hits = {"count": 0}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits["count"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(img_bytes)))
            self.end_headers()
            self.wfile.write(img_bytes)
        def log_message(self, *a, **kw): pass

    srv = _start(H)
    try:
        yield srv, img_bytes, hits
    finally:
        srv.shutdown()


def _make_app(tmp_path: Path, upstream_addr) -> tuple:
    from lmfetch.server import build_app
    from lmfetch.cache import Cache
    from lmfetch.downloader import PlainDownloader

    cache = Cache(tmp_path / "cache", max_bytes=10 * 1024 * 1024)
    downloader = PlainDownloader(timeout=5)
    host, port = upstream_addr
    app = build_app(
        cache=cache,
        downloader=downloader,
        upstream_url=f"http://{host}:{port}",
    )
    return app, cache, downloader


def _post(app, payload):
    from fastapi.testclient import TestClient
    client = TestClient(app)
    r = client.post("/v1/chat/completions", json=payload)
    return r


def test_passthrough_non_vision_request(fake_upstream, tmp_path: Path) -> None:
    srv, last = fake_upstream
    app, *_ = _make_app(tmp_path, srv.server_address)

    payload = {
        "model": "x",
        "messages": [{"role": "user", "content": "ping"}],
    }
    r = _post(app, payload)
    assert r.status_code == 200
    assert last["body"] == payload


def test_image_url_rewritten_to_data_base64(fake_upstream, origin_image, tmp_path: Path) -> None:
    up_srv, last = fake_upstream
    img_srv, img_bytes, hits = origin_image
    app, *_ = _make_app(tmp_path, up_srv.server_address)

    img_url = f"http://127.0.0.1:{img_srv.server_address[1]}/a.png"
    payload = {
        "model": "x",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {"type": "image_url", "image_url": {"url": img_url}},
            ],
        }],
    }
    r = _post(app, payload)
    assert r.status_code == 200
    forwarded = last["body"]["messages"][0]["content"]
    assert forwarded[0] == {"type": "text", "text": "describe"}
    out_url = forwarded[1]["image_url"]["url"]
    assert out_url.startswith("data:image/png;base64,")
    decoded = base64.b64decode(out_url.split(",", 1)[1])
    assert decoded == img_bytes
    assert hits["count"] == 1


def test_data_url_passes_through(fake_upstream, tmp_path: Path) -> None:
    srv, last = fake_upstream
    app, *_ = _make_app(tmp_path, srv.server_address)

    data_url = "data:image/png;base64," + base64.b64encode(b"already-encoded").decode()
    payload = {
        "model": "x",
        "messages": [{
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": data_url}}],
        }],
    }
    r = _post(app, payload)
    assert r.status_code == 200
    assert last["body"]["messages"][0]["content"][0]["image_url"]["url"] == data_url


def test_fetch_error_falls_back_to_placeholder(fake_upstream, tmp_path: Path) -> None:
    """When the downloader can't reach the URL, the request still goes through —
    the model receives the bundled 'Image Not Available' placeholder PNG."""
    from lmfetch.server import build_app
    from lmfetch.cache import Cache
    from lmfetch.downloader import FetchError
    from lmfetch.placeholder import PLACEHOLDER_PATH

    srv, last = fake_upstream

    class AlwaysFails:
        def fetch(self, url):
            raise FetchError(f"simulated unreachable: {url}")

    cache = Cache(tmp_path / "cache", max_bytes=10 * 1024 * 1024)
    host, port = srv.server_address
    app = build_app(cache=cache, downloader=AlwaysFails(), upstream_url=f"http://{host}:{port}")

    payload = {
        "model": "x",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {"type": "image_url", "image_url": {"url": "http://unreachable.invalid/x.png"}},
            ],
        }],
    }
    r = _post(app, payload)
    assert r.status_code == 200
    forwarded = last["body"]["messages"][0]["content"]
    out_url = forwarded[1]["image_url"]["url"]
    assert out_url.startswith("data:image/png;base64,")
    decoded = base64.b64decode(out_url.split(",", 1)[1])
    assert decoded == PLACEHOLDER_PATH.read_bytes(), "must forward the bundled placeholder bytes"


def test_cache_hit_avoids_second_download(fake_upstream, origin_image, tmp_path: Path) -> None:
    up_srv, _last = fake_upstream
    img_srv, _img_bytes, hits = origin_image
    app, *_ = _make_app(tmp_path, up_srv.server_address)

    img_url = f"http://127.0.0.1:{img_srv.server_address[1]}/a.png"
    payload = {
        "model": "x",
        "messages": [{
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": img_url}}],
        }],
    }
    _post(app, payload)
    _post(app, payload)
    assert hits["count"] == 1, "second request must hit cache, not the origin"
