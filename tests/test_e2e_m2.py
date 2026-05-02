"""End-to-end acceptance for M2 downloader.

Three legs, each against real network plumbing (no mocks):

  1. PlainDownloader hits a real public image URL (httpbin.org/image/png)
     and yields valid PNG bytes.

  2. BrowserSpoofDownloader's UA + Referer round-trip through httpbin.org/headers,
     proving custom headers reach the upstream server.

  3. ProxiedDownloader actually traverses a local forward-proxy we run in-test:
     proxy logs the request -> we assert the log entry matches.

Network egress is needed for legs 1 and 2. If the dev box has no internet they
will be skipped (we ping httpbin first).

This is M2's acceptance: a Jack-visible proof that switching downloaders
actually changes how the bytes are obtained.
"""
from __future__ import annotations

import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import json
import pytest

from lmfetch.downloader import (
    BrowserSpoofDownloader,
    DomainRule,
    PlainDownloader,
    ProxiedDownloader,
    build_router,
)


def _internet_reachable(host: str = "httpbin.org", timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _internet_reachable(), reason="no internet")


def test_e2e_plain_downloads_real_png() -> None:
    res = PlainDownloader(timeout=15).fetch("https://httpbin.org/image/png")
    assert res.status == 200
    assert res.content_type and res.content_type.startswith("image/png")
    assert res.bytes_[:8] == b"\x89PNG\r\n\x1a\n", "must be a valid PNG signature"


def test_e2e_browser_spoof_headers_round_trip() -> None:
    dl = BrowserSpoofDownloader(
        user_agent="Mozilla/5.0 (lmfetch-e2e)",
        extra_headers={"Referer": "https://lmfetch.test/"},
        timeout=15,
    )
    res = dl.fetch("https://httpbin.org/headers")
    payload = json.loads(res.bytes_.decode())
    headers = payload["headers"]
    assert headers.get("User-Agent") == "Mozilla/5.0 (lmfetch-e2e)"
    assert headers.get("Referer") == "https://lmfetch.test/"


class _ForwardProxy(BaseHTTPRequestHandler):
    """Tiny HTTP forward-proxy used to prove ProxiedDownloader routes through it.

    Only handles plain GET. CONNECT/HTTPS is out of scope for this e2e — we drive
    it against the local origin server registered via the parent test fixture.
    """

    log: list[str] = []

    def do_GET(self):  # noqa: N802
        self.log.append(self.path)
        try:
            with urllib.request.urlopen(self.path, timeout=5) as r:
                body = r.read()
                self.send_response(r.status)
                ct = r.headers.get("Content-Type")
                if ct:
                    self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except Exception as e:  # noqa: BLE001
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, *a, **kw):
        pass


def test_e2e_proxied_downloader_actually_traverses_proxy() -> None:
    class Origin(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b"origin-bytes"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a, **kw): pass

    origin = HTTPServer(("127.0.0.1", 0), Origin)
    threading.Thread(target=origin.serve_forever, daemon=True).start()

    _ForwardProxy.log = []
    proxy = HTTPServer(("127.0.0.1", 0), _ForwardProxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()

    try:
        ohost, oport = origin.server_address
        phost, pport = proxy.server_address
        url = f"http://{ohost}:{oport}/avatar.png"

        dl = ProxiedDownloader(f"http://{phost}:{pport}", timeout=10)
        res = dl.fetch(url)

        assert res.bytes_ == b"origin-bytes"
        assert _ForwardProxy.log == [url], "proxy must have logged exactly the one URL it forwarded"
    finally:
        origin.shutdown()
        proxy.shutdown()


def test_e2e_router_picks_proxy_for_matching_host_only() -> None:
    """One rule routes via proxy, another goes direct — proxy log proves the split."""
    class Origin(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a, **kw): pass

    proxied_origin = HTTPServer(("127.0.0.1", 0), Origin)
    direct_origin = HTTPServer(("127.0.0.1", 0), Origin)
    threading.Thread(target=proxied_origin.serve_forever, daemon=True).start()
    threading.Thread(target=direct_origin.serve_forever, daemon=True).start()

    _ForwardProxy.log = []
    proxy = HTTPServer(("127.0.0.1", 0), _ForwardProxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()

    try:
        p_host, p_port = proxy.server_address
        po_host, po_port = proxied_origin.server_address
        do_host, do_port = direct_origin.server_address

        # Both origins are on 127.0.0.1, so we route by port via custom pattern.
        # Use hostname patterns instead: bind direct origin to "localhost", proxied to "127.0.0.1".
        # urllib resolves both to loopback; we keep the URL host string distinct:
        proxied_url = f"http://127.0.0.1:{po_port}/p.png"
        direct_url = f"http://localhost:{do_port}/d.png"

        router = build_router([
            DomainRule(pattern="127.0.0.1", downloader=ProxiedDownloader(f"http://{p_host}:{p_port}")),
            DomainRule(pattern="*", downloader=PlainDownloader()),
        ])

        router.fetch(proxied_url)
        router.fetch(direct_url)

        assert _ForwardProxy.log == [proxied_url], (
            f"proxy log should contain only the 127.0.0.1 URL, got {_ForwardProxy.log}"
        )
    finally:
        proxied_origin.shutdown()
        direct_origin.shutdown()
        proxy.shutdown()
