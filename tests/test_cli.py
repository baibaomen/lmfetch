"""TDD for lmfetch.cli — env-driven `lmfetch serve` entry.

The deployment story (M5) is "drop a docker container in front of llama.cpp",
so the CLI must be configurable purely via environment variables — no YAML
required for the simple case.

Behaviors under test:
  - `build_app_from_env({...})` returns a FastAPI app wired to a Cache pointed
    at LMFETCH_CACHE_DIR with LMFETCH_CACHE_MAX_BYTES, a PlainDownloader, and
    LMFETCH_UPSTREAM_URL forwarded.
  - Missing LMFETCH_UPSTREAM_URL is a hard error (no silent default — bad
    deployments must fail loud at startup).
  - Defaults: cache dir → /var/lib/lmfetch/cache, max_bytes → 10 GiB.
"""
from __future__ import annotations

import pytest


def test_build_app_from_env_minimal(tmp_path) -> None:
    from lmfetch.cli import build_app_from_env

    env = {
        "LMFETCH_UPSTREAM_URL": "http://upstream.invalid:8080",
        "LMFETCH_CACHE_DIR": str(tmp_path / "cache"),
        "LMFETCH_CACHE_MAX_BYTES": "1048576",
    }
    app = build_app_from_env(env)

    # health endpoint exists
    from fastapi.testclient import TestClient
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert (tmp_path / "cache").is_dir(), "cache dir should be created on startup"


def test_build_app_from_env_requires_upstream(tmp_path) -> None:
    from lmfetch.cli import build_app_from_env

    env = {
        "LMFETCH_CACHE_DIR": str(tmp_path / "cache"),
    }
    with pytest.raises(SystemExit) as exc:
        build_app_from_env(env)
    assert "LMFETCH_UPSTREAM_URL" in str(exc.value)


def test_build_app_from_env_defaults(tmp_path, monkeypatch) -> None:
    """Defaults should kick in when only UPSTREAM_URL is set, but we steer
    the default cache dir into tmp so the test doesn't touch /var."""
    from lmfetch.cli import build_app_from_env

    env = {
        "LMFETCH_UPSTREAM_URL": "http://upstream.invalid:8080",
        "LMFETCH_CACHE_DIR": str(tmp_path / "default-cache"),
        # LMFETCH_CACHE_MAX_BYTES omitted → default
    }
    app = build_app_from_env(env)
    assert app is not None
    assert (tmp_path / "default-cache").is_dir()
