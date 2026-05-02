"""TDD for lmfetch.downloader.

API under test:
  class FetchResult: bytes_: bytes, content_type: str | None, status: int
  class FetchError(Exception): ...

  Downloader(Protocol).fetch(url: str) -> FetchResult

  Built-in implementations:
    PlainDownloader()                     # stdlib urllib, no extras
    ProxiedDownloader(proxy_url)          # http(s)/socks proxy
    BrowserSpoofDownloader(ua=..., headers=...)

  build_router(rules: list[DomainRule]) -> Downloader
    DomainRule(pattern: str, downloader: Downloader)
    pattern is fnmatch-style on URL host (e.g. "*.googleusercontent.com")

These tests use only PlainDownloader against a local HTTPServer so they're
hermetic. Real proxy / real GFW domain coverage lands in test_e2e_m2.
"""
from __future__ import annotations

import fnmatch
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


def _start_server(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


@pytest.fixture
def echo_server():
    captured = {"headers": None}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            captured["headers"] = dict(self.headers)
            body = b"hello-world"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a, **kw):
            pass

    srv = _start_server(H)
    try:
        yield srv, captured
    finally:
        srv.shutdown()


def test_plain_downloader_fetches_bytes(echo_server) -> None:
    from lmfetch.downloader import PlainDownloader

    srv, _ = echo_server
    host, port = srv.server_address
    url = f"http://{host}:{port}/img.png"

    res = PlainDownloader().fetch(url)
    assert res.bytes_ == b"hello-world"
    assert res.status == 200
    assert res.content_type == "image/png"


def test_plain_downloader_raises_on_404() -> None:
    from lmfetch.downloader import FetchError, PlainDownloader

    class H404(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a, **kw):
            pass

    srv = _start_server(H404)
    try:
        host, port = srv.server_address
        with pytest.raises(FetchError):
            PlainDownloader().fetch(f"http://{host}:{port}/missing.png")
    finally:
        srv.shutdown()


def test_browser_spoof_sends_custom_ua_and_headers(echo_server) -> None:
    from lmfetch.downloader import BrowserSpoofDownloader

    srv, captured = echo_server
    host, port = srv.server_address
    url = f"http://{host}:{port}/img.png"

    dl = BrowserSpoofDownloader(
        user_agent="Mozilla/5.0 (lmfetch-spoof)",
        extra_headers={"Referer": "https://example.com/", "Accept-Language": "en-US"},
    )
    dl.fetch(url)

    h = {k.lower(): v for k, v in captured["headers"].items()}
    assert h.get("user-agent") == "Mozilla/5.0 (lmfetch-spoof)"
    assert h.get("referer") == "https://example.com/"
    assert h.get("accept-language") == "en-US"


def test_router_dispatches_by_host_glob(echo_server) -> None:
    from lmfetch.downloader import BrowserSpoofDownloader, DomainRule, PlainDownloader, build_router

    srv, captured = echo_server
    host, port = srv.server_address

    plain = PlainDownloader()
    spoof = BrowserSpoofDownloader(user_agent="UA-from-rule")

    router = build_router([
        DomainRule(pattern="127.0.0.1", downloader=spoof),
        DomainRule(pattern="*", downloader=plain),
    ])
    router.fetch(f"http://{host}:{port}/img.png")
    h = {k.lower(): v for k, v in captured["headers"].items()}
    assert h.get("user-agent") == "UA-from-rule"


def test_router_falls_back_to_last_rule() -> None:
    from lmfetch.downloader import DomainRule, PlainDownloader, build_router

    plain = PlainDownloader()
    flagged = {"called": False}

    class Marker(PlainDownloader):
        def fetch(self, url):
            flagged["called"] = True
            return super().fetch(url)

    router = build_router([
        DomainRule(pattern="other.example.com", downloader=Marker()),
        DomainRule(pattern="*", downloader=plain),
    ])

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a, **kw): pass
    srv = _start_server(H)
    try:
        host, port = srv.server_address
        router.fetch(f"http://{host}:{port}/")
    finally:
        srv.shutdown()
    assert flagged["called"] is False
