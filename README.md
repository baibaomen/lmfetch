# lmfetch

> **Image fetch + cache sidecar for OpenAI-compatible vision APIs.**
> Drop it between any OpenAI-compatible client and any vision-capable inference
> engine (llama.cpp / vLLM / SGLang / llama-cpp-python / TGI / …). lmfetch
> handles the `image_url` parts so the engine doesn't have to.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

## Why

OpenAI's vision protocol lets clients send

```json
{"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}}
```

inside a chat message. Most engines implement this by **having the inference
process itself fetch the URL** every time the message comes in. That breaks in
production:

- the URL host is unreachable from the inference box (firewall, hotlink,
  geo-blocking, transient outage) → the chat 500s;
- the URL went away — replaying an old conversation now 500s;
- the same image gets re-downloaded on every turn even though it never changed;
- limits are hard-coded in the engine (e.g. llama.cpp: 10 MB / 10 s) — no way to
  bump them, no way to set a custom User-Agent or route via a proxy.

`lmfetch` is a thin OpenAI-compatible HTTP proxy that fixes this in one place:

- **Content-addressed image cache** — URL hash + content hash (multiple
  versions per URL coexist; you don't lose history when the URL's content
  changes), LRU eviction, configurable disk budget.
- **Pluggable downloaders** — per-domain rules to swap UA / Referer / proxy /
  full browser-spoof headers. Built-ins: plain, proxied, browser-spoof.
- **Graceful fallback** — when a URL can't be fetched, lmfetch injects a
  bundled "Image Not Available" placeholder PNG so the chat completes
  instead of 500-ing.
- **Engine-agnostic** — outbound traffic to the inference engine is plain
  `data:` URLs, so the downstream engine doesn't need any modification.

## Architecture

```
┌────────┐     image_url(http)      ┌──────────┐    image_url(data:base64)    ┌───────────┐
│ client │ ───────────────────────► │ lmfetch  │ ───────────────────────────► │ inference │
└────────┘   /v1/chat/completions   └──────────┘    /v1/chat/completions      └───────────┘
                                          │
                                          └─► CAS cache (URL hash + content hash + LRU)
```

lmfetch presents a thin OpenAI-compatible surface (`/v1/chat/completions`,
`/healthz`); everything it doesn't recognize is forwarded to the upstream
inference engine unchanged.

## Quickstart (Docker)

```bash
docker run -d --name lmfetch \
  -p 8000:8000 \
  -v $PWD/lmfetch-cache:/var/lib/lmfetch/cache \
  -e LMFETCH_UPSTREAM_URL=http://host.docker.internal:8080 \
  -e LMFETCH_CACHE_MAX_BYTES=10737418240 \
  ghcr.io/baibaomen/lmfetch:latest

# Point your client at http://localhost:8000 instead of the inference engine
# directly. lmfetch forwards everything to LMFETCH_UPSTREAM_URL.
curl -s http://localhost:8000/healthz
# → {"status":"ok"}
```

## Quickstart (from source)

```bash
git clone https://github.com/baibaomen/lmfetch.git
cd lmfetch
uv pip install -e .

LMFETCH_UPSTREAM_URL=http://localhost:8080 \
LMFETCH_CACHE_DIR=$PWD/.cache \
lmfetch serve
```

## Configuration

All configuration is via environment variables.

| Variable                  | Required | Default                       | Notes                                                           |
| ------------------------- | :------: | ----------------------------- | --------------------------------------------------------------- |
| `LMFETCH_UPSTREAM_URL`    |   yes    | —                             | Base URL of the OpenAI-compatible inference engine to forward to |
| `LMFETCH_CACHE_DIR`       |    no    | `/var/lib/lmfetch/cache`      | Cache root (will be created)                                    |
| `LMFETCH_CACHE_MAX_BYTES` |    no    | `10737418240` (10 GiB)        | LRU eviction kicks in above this                                |
| `LMFETCH_HOST`            |    no    | `0.0.0.0`                     | Listen address                                                  |
| `LMFETCH_PORT`            |    no    | `8000`                        | Listen port                                                     |

## Examples

- [`examples/newapi/`](examples/newapi/) — drop-in compose for stacks that put
  an OpenAI gateway (new-api / one-api / LiteLLM) in front of a local inference
  engine. Topology: `client → gateway → lmfetch → inference`.

More examples (vLLM standalone, SGLang, llama-cpp-python) coming with later
releases.

## Status

v0.1 — early but working. See [STATUS.md](STATUS.md) for the roadmap and
milestone-by-milestone acceptance criteria. End-to-end vision round-trip is
covered by tests against a real upstream (configure with `LMFETCH_E2E_*` env
vars; tests skip cleanly when not set).

## Development

```bash
git clone https://github.com/baibaomen/lmfetch.git
cd lmfetch
uv venv && uv pip install -e ".[dev]"
pytest -q
```

End-to-end tests against a real vision upstream are opt-in:

```bash
export LMFETCH_E2E_UPSTREAM_URL=https://your-gateway.example.com
export LMFETCH_E2E_MODEL=your-vision-model
export LMFETCH_E2E_TOKEN=your-bearer-token
pytest tests/test_e2e_m3.py tests/test_e2e_m4.py -q
```

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 baibaomen
`<baibaomen@gmail.com>`. If you use lmfetch (or vendor any of its modules into
another project), please keep the copyright notice. That's the only condition.
