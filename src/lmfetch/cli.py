"""lmfetch CLI — `lmfetch serve` (env-driven).

Reads:
  LMFETCH_UPSTREAM_URL       (required) — e.g. http://local-llm-server:8080
  LMFETCH_CACHE_DIR          (default /var/lib/lmfetch/cache)
  LMFETCH_CACHE_MAX_BYTES    (default 10737418240 = 10 GiB)
  LMFETCH_HOST               (default 0.0.0.0)
  LMFETCH_PORT               (default 8000)

This intentionally does NOT expose proxy / spoof routing yet — the simple
deployment shape (lmfetch in front of a local inference container, fetching
public URLs directly) doesn't need it. Per-domain routing config lands when
an actual deployment requires it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping

from .cache import Cache
from .downloader import PlainDownloader
from .server import build_app


_DEFAULT_CACHE_DIR = "/var/lib/lmfetch/cache"
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB


def build_app_from_env(env: Mapping[str, str]):
    upstream = env.get("LMFETCH_UPSTREAM_URL")
    if not upstream:
        raise SystemExit(
            "LMFETCH_UPSTREAM_URL is required (e.g. http://local-llm-server:8080)"
        )
    cache_dir = Path(env.get("LMFETCH_CACHE_DIR", _DEFAULT_CACHE_DIR))
    max_bytes = int(env.get("LMFETCH_CACHE_MAX_BYTES", _DEFAULT_MAX_BYTES))
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache = Cache(cache_dir, max_bytes=max_bytes)
    downloader = PlainDownloader(timeout=30)
    return build_app(cache=cache, downloader=downloader, upstream_url=upstream)


def main(argv: list[str] | None = None) -> None:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv or argv[0] != "serve":
        raise SystemExit("usage: lmfetch serve   (configure via LMFETCH_* env vars)")

    import uvicorn

    app = build_app_from_env(os.environ)
    host = os.environ.get("LMFETCH_HOST", "0.0.0.0")
    port = int(os.environ.get("LMFETCH_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
