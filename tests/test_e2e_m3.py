"""End-to-end acceptance for M3 server, against the REAL qwen3.6 upstream.

Spins up lmfetch in-process bound to a random localhost port, configured
to forward to https://llm-dev.baibaomen.com (the real qwen3.6-35b-a3b
served by llama.cpp on alien). Then drives a vision request through it and
asserts the round-trip works end-to-end:

  Client --image_url(http)--> lmfetch --image_url(data:base64)--> llama.cpp --> qwen3.6
                                                                              |
  Client <--("the image is X")--------- lmfetch <----------------- response <-+

Requires:
  - BBM_LLM_DEV_TOKEN env var with a valid bearer for llm-dev.baibaomen.com
  - internet egress (httpbin.org for the test image; llm-dev.baibaomen.com for upstream)

Skipped otherwise so unit-only runs stay green.

Acceptance reads as a single Jack-visible sentence: "I sent an http://...png URL,
qwen3.6 saw the actual picture, and answered about it" — and the cache directory
ends up holding the fetched bytes so the next call can hit warm.
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
IMAGE_URL = "https://httpbin.org/image/png"
TOKEN = os.environ.get("BBM_LLM_DEV_TOKEN", "")


def _net_ok() -> bool:
    try:
        with socket.create_connection(("llm-dev.baibaomen.com", 443), timeout=3):
            pass
        with socket.create_connection(("httpbin.org", 443), timeout=3):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(not TOKEN, reason="BBM_LLM_DEV_TOKEN not set"),
    pytest.mark.skipif(not _net_ok(), reason="upstream/image host not reachable"),
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
        downloader=PlainDownloader(timeout=20),
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


def _vision_request(model=MODEL, image_url=IMAGE_URL, prompt="What is the dominant subject of this image? Reply in one short sentence."):
    return {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }],
        "max_tokens": 256,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_e2e_m3_qwen_via_lmfetch(lmfetch_server) -> None:
    base, cache = lmfetch_server

    with httpx.Client(timeout=120) as c:
        r = c.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json=_vision_request(),
        )

    assert r.status_code == 200, f"lmfetch->qwen failed: {r.status_code} {r.text[:500]}"
    body = r.json()
    content = body["choices"][0]["message"]["content"].strip()
    print(f"\n[E2E] qwen via lmfetch said: {content!r}\n")
    assert content, "qwen produced empty content (max_tokens too small? thinking ate it?)"
    # The Wikipedia transparency demo PNG shows a tabletop game / dice. The model
    # must produce *something* image-derived; we don't pin exact wording but require
    # the response is plausibly about an image, not a generic refusal.
    refusals = ["i cannot", "unable to", "no image", "as a text-only"]
    low = content.lower()
    assert not any(r in low for r in refusals), f"qwen refused to look at image: {content}"

    hits = cache.get(IMAGE_URL)
    assert len(hits) == 1, "lmfetch should have cached exactly one version of the source image"
    assert hits[0].size > 1000, "cached blob suspiciously small for a PNG"


def test_e2e_m3_qwen_warm_cache_no_refetch(lmfetch_server) -> None:
    """Second turn for the same URL: lmfetch must not re-download — qwen still sees the picture."""
    base, cache = lmfetch_server

    with httpx.Client(timeout=120) as c:
        r1 = c.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json=_vision_request(),
        )
        assert r1.status_code == 200, r1.text[:500]
        size_after_first = cache.total_bytes()
        first_blob_count = len(list((cache.root / "blobs").rglob("*.bin")))

        r2 = c.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json=_vision_request(prompt="Now describe the colors you see, briefly."),
        )

    assert r2.status_code == 200, r2.text[:500]
    body = r2.json()
    content = body["choices"][0]["message"]["content"].strip()
    print(f"\n[E2E warm] qwen via lmfetch (warm cache) said: {content!r}\n")
    assert content
    assert cache.total_bytes() == size_after_first, "no new bytes should have entered cache"
    assert len(list((cache.root / "blobs").rglob("*.bin"))) == first_blob_count
