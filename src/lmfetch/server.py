"""FastAPI passthrough server.

Receives OpenAI-compatible /v1/chat/completions, rewrites every
{"type":"image_url","image_url":{"url":"http(s)://..."}} message part to
{"type":"image_url","image_url":{"url":"data:<ct>;base64,<...>"}} after
running the URL through the lmfetch cache + downloader, then forwards the
modified request to the configured upstream engine.

`build_app(cache, downloader, upstream_url)` returns a FastAPI app instance.
The CLI (`lmfetch serve`) lives in cli.py.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

from .cache import Cache
from .downloader import Downloader, FetchError
from .placeholder import PLACEHOLDER_PATH

log = logging.getLogger("lmfetch.server")


_PLACEHOLDER_BYTES = PLACEHOLDER_PATH.read_bytes()
_PLACEHOLDER_CT = "image/png"


def _resolve_image_url(url: str, cache: Cache, downloader: Downloader) -> tuple[bytes, str]:
    hits = cache.get(url)
    if hits:
        entry = hits[0]
        return entry.blob_path.read_bytes(), _guess_ct_from_blob(entry.blob_path.read_bytes())
    res = downloader.fetch(url)
    cache.put(url, res.bytes_)
    ct = res.content_type or "image/png"
    return res.bytes_, ct.split(";", 1)[0].strip()


def _guess_ct_from_blob(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _rewrite_messages(messages: list[dict[str, Any]], cache: Cache, downloader: Downloader) -> None:
    """In-place rewrite of every image_url part whose URL is fetchable."""
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            iu = part.get("image_url") or {}
            url = iu.get("url")
            if not isinstance(url, str) or url.startswith("data:"):
                continue
            try:
                data, ct = _resolve_image_url(url, cache, downloader)
            except FetchError as e:
                log.warning("fetch failed for %s, serving placeholder: %s", url, e)
                data, ct = _PLACEHOLDER_BYTES, _PLACEHOLDER_CT
            b64 = base64.b64encode(data).decode("ascii")
            part["image_url"] = {"url": f"data:{ct};base64,{b64}"}


def build_app(*, cache: Cache, downloader: Downloader, upstream_url: str) -> FastAPI:
    app = FastAPI(title="lmfetch", version="0.0.1")
    upstream_url = upstream_url.rstrip("/")

    @app.post("/v1/chat/completions")
    async def chat_completions(req: Request) -> Response:
        payload = await req.json()
        messages = payload.get("messages")
        if isinstance(messages, list):
            _rewrite_messages(messages, cache, downloader)

        # forward selected headers; strip Host so httpx sets the upstream's
        skip = {"host", "content-length", "accept-encoding", "connection"}
        fwd_headers = {k: v for k, v in req.headers.items() if k.lower() not in skip}

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            up = await client.post(
                upstream_url + "/v1/chat/completions",
                json=payload,
                headers=fwd_headers,
            )
        return Response(
            content=up.content,
            status_code=up.status_code,
            media_type=up.headers.get("content-type", "application/json"),
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
