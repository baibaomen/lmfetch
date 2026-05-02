# lmfetch — STATUS

> Roadmap view: from "the inference server keeps tripping over `image_url` URLs"
> to "an engine-agnostic image fetch + cache sidecar that any OpenAI-compatible
> vision engine can drop in front of."

## Roadmap

```
Today: llama.cpp / vLLM / SGLang all implement "server-side fetch image_url"
        inside the inference process. Failures 500 the chat. Successful fetches
        re-download per-turn. Limits are hard-coded (10 MB / 10 s on llama.cpp).
        No way to customize User-Agent, route via proxy, or persist results.
        ↓
M0   Repo scaffold (README / LICENSE / pyproject / package skeleton)
        ↓
M1   Cache: URL+content double-hash CAS, SQLite index, LRU eviction (TDD)
        ↓
M2   Downloader: plain / proxied / browser-spoof, per-domain rule routing (TDD)
        ↓
M3   Server: FastAPI passthrough of OpenAI vision protocol
        every image_url → cache lookup → replace with data:base64
        downstream engine only ever sees data: URLs
        ↓
M4   Placeholder: when a URL can't be fetched, serve a built-in "not available"
        PNG instead of 500-ing the chat
        ↓
M5   Deployment: docker-compose example sitting between an OpenAI gateway
        (one-api / LiteLLM) and a local llama.cpp server, with cache persistence
        ↓
M6   v0.1 OSS launch: README quickstart, examples (llama.cpp + vLLM compose),
        CHANGELOG, CI, GHCR image
        ↓
M7   Upstream contributions: PR llama.cpp to make max_size / timeout configurable;
        contribute a C++ port of the cache module if it lands well
```

## Progress

- [x] M0 scaffold
- [x] M1 cache (CAS + LRU + multi-version, TDD + e2e green)
- [x] M2 downloader (plain / spoof / proxied + domain router, e2e against real httpbin / a local forward proxy)
- [x] M3 server (FastAPI passthrough, image_url → data:base64, **real-vision-model e2e green**)
- [x] M4 placeholder (FetchError → bundled PNG, **the model reads back "Image Not Available"**)
- [x] M5 deployment (Dockerfile + compose example wired between an OpenAI gateway and llama.cpp; verified end-to-end with a real vision request, including warm-cache reuse)
- [ ] M6 v0.1 OSS launch (next)
- [ ] M7 upstream PR

## Acceptance (user-visible, milestone-by-milestone)

- M1 done: `pytest` green; feed two different content bytes for the same URL → both versions present on disk, `Cache.get(url)` returns both.
- M2 done: a hotlink-blocked image URL fetched successfully via a `BrowserSpoofDownloader` rule with a realistic UA + Referer.
- M3 done: client sends `{"type":"image_url","url":"https://..."}`; downstream engine receives `data:image/png;base64,...`; the model answers correctly about the picture.
- M4 done: deliberately bad URL — the chat still completes, the model receives the placeholder and reports it as such.
- M5 done: example compose stack (gateway → lmfetch → llama.cpp) starts clean; vision request flows end-to-end; cache directory accumulates blobs; second turn for the same URL reuses cache (blob count unchanged).
- M6 done: `v0.1.0` release tag exists; `examples/` compose files come up with `docker compose up`; README quickstart works for someone who's never seen the repo.
