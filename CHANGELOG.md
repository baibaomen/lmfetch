# Changelog

All notable changes to this project will be documented in this file. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-03

First public release. Solves the "OpenAI-compatible vision engine downloads
`image_url` itself, every turn, and 500s on any failure" problem with a
drop-in HTTP proxy.

### Added

- **Cache** (M1) — content-addressed image cache: URL hash + content hash, so
  multiple versions of the same URL coexist instead of overwriting. SQLite
  index, LRU eviction, configurable disk budget.
- **Downloader** (M2) — pluggable downloader interface with built-ins
  `PlainDownloader`, `BrowserSpoofDownloader`, `ProxiedDownloader`, plus a
  `DomainRule(pattern, downloader)` router so different hosts can use
  different fetch strategies.
- **Server** (M3) — FastAPI passthrough that intercepts
  `/v1/chat/completions`, rewrites every `image_url` part to `data:base64`
  using cache-or-fetch, and forwards everything else unchanged. Already-`data:`
  URLs are passed through.
- **Placeholder fallback** (M4) — when a URL can't be fetched and isn't
  cached, lmfetch substitutes a bundled "Image Not Available" PNG instead of
  500-ing the chat. Vision models read the placeholder text back, so the user
  gets a clear answer instead of an opaque error.
- **Container deployment** (M5) — `Dockerfile` (Python 3.12 slim + uv) plus
  example `examples/newapi/` compose for stacks with an OpenAI gateway in
  front of a local inference engine.
- **CLI** — `lmfetch serve` reads configuration from `LMFETCH_*` environment
  variables.
- **Tests** — unit tests for cache / downloader / server / CLI; opt-in
  end-to-end tests (`tests/test_e2e_m3.py`, `tests/test_e2e_m4.py`) drive a
  real vision upstream via `LMFETCH_E2E_*` env vars and skip cleanly when
  unset.

### Notes

- Engine-agnostic: lmfetch only emits `data:` URLs to the upstream, so any
  OpenAI-compatible vision engine works without modification.
- Per-domain routing config (YAML) is intentionally not exposed yet — the
  current single-`PlainDownloader` shape is sufficient for the common
  deployment (lmfetch in front of a local engine, fetching public URLs
  directly). It will surface in a later release when a real deployment needs
  it.

[0.1.0]: https://github.com/baibaomen/lmfetch/releases/tag/v0.1.0
