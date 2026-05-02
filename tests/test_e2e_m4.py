"""End-to-end acceptance for M4 placeholder fallback, against real qwen3.6.

When the URL is unreachable (DNS doesn't resolve / connection refused), lmfetch
must NOT 500. It must inject the bundled "Image Not Available" placeholder PNG
as data:base64 so the upstream model still sees a real image and the chat
completes successfully.

Jack-visible acceptance: "I sent a deliberately broken URL through lmfetch,
qwen3.6 saw a 'not available' image and said so" — full link stays up, no 500.
"""
from __future__ import annotations

import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from lmfetch.cache import Cache
from lmfetch.downloader import PlainDownloader
from lmfetch.server import build_app


UPSTREAM = "https://llm-dev.baibaomen.com"
MODEL = "qwen3.6-35b-a3b"
# A URL that won't resolve / won't connect. Using a TLD that doesn't exist
# guarantees PlainDownloader raises FetchError without flaky-network risk.
BROKEN_URL = "http://no-such-host.lmfetch-e2e.invalid/missing.png"
TOKEN = os.environ.get("BBM_LLM_DEV_TOKEN", "")


def _net_ok() -> bool:
    try:
        with socket.create_connection(("llm-dev.baibaomen.com", 443), timeout=3):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(not TOKEN, reason="BBM_LLM_DEV_TOKEN not set"),
    pytest.mark.skipif(not _net_ok(), reason="llm-dev not reachable"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def lmfetch_server(tmp_path):
    cache = Cache(tmp_path / "cache", max_bytes=20 * 1024 * 1024)
    app = build_app(
        cache=cache,
        downloader=PlainDownloader(timeout=5),
        upstream_url=UPSTREAM,
    )
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=1) as c:
                if c.get(f"http://127.0.0.1:{port}/healthz").status_code == 200:
                    break
        except Exception:
            time.sleep(0.1)
    else:
        server.should_exit = True
        raise RuntimeError("lmfetch did not come up")

    try:
        yield f"http://127.0.0.1:{port}", cache
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_e2e_m4_broken_url_serves_placeholder_via_qwen(lmfetch_server) -> None:
    base, cache = lmfetch_server

    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Look at this image and answer in one short sentence: "
                        "what does it say or show?"
                    ),
                },
                {"type": "image_url", "image_url": {"url": BROKEN_URL}},
            ],
        }],
        "max_tokens": 256,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    with httpx.Client(timeout=120) as c:
        r = c.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json=payload,
        )

    assert r.status_code == 200, f"lmfetch must NOT 500 on broken URL: {r.status_code} {r.text[:500]}"
    body = r.json()
    content = body["choices"][0]["message"]["content"].strip()
    print(f"\n[E2E M4] qwen via lmfetch (placeholder) said: {content!r}\n")
    assert content, "qwen produced empty content"

    # The bundled placeholder PNG carries 'Image Not Available' text. The model
    # must read it — we accept any of these substrings, case-insensitive.
    low = content.lower()
    assert any(k in low for k in ("not available", "unavailable", "image not", "no image", "n/a")), (
        f"qwen should see the 'Image Not Available' placeholder, got: {content!r}"
    )

    # Cache must remain empty: a failed fetch should not pollute the cache with
    # placeholder bytes under the original URL.
    assert cache.get(BROKEN_URL) == [], "broken URL must not get cached as placeholder"
