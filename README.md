# lmfetch

> Image fetch + cache sidecar for OpenAI-compatible vision APIs.
> Sits between your client and any inference engine that speaks `image_url` (llama.cpp / vLLM / SGLang / llama-cpp-python / TGI ...).

## What it does

OpenAI vision protocol lets you send `{"type":"image_url","image_url":{"url":"https://..."}}` to a multimodal model. Most engines implement this by **having the inference server itself download the URL** every time the message appears in a request. That's fine until:

- the URL host is blocked from the inference box (GFW, hotlink restrictions, …);
- the URL hits a timeout, hard-coded in the engine;
- the URL went away — replaying an old conversation now 500s;
- the same image gets re-encoded for the vision tower on every turn;
- you want to track URL-stable but content-changing assets (avatars, banners) across time.

`lmfetch` fixes all of these in a single drop-in HTTP proxy:

- **Content-addressed image cache** (URL hash + content hash, multiple versions per URL coexist)
- **Pluggable downloaders**: per-domain rules to switch UA / proxy / headers (built-ins: plain, proxied, browser-spoof)
- **LRU eviction** with configurable disk budget (default 1 GB)
- **Graceful fallback** — when a URL can't be fetched and isn't cached, serve a built-in "Image Not Available" PNG instead of 500-ing the entire chat completion
- **Configurable fetch limits** (max-size, timeout) — fixes llama.cpp's hard-coded 10 MB / 10 s
- **Engine-agnostic**: outbound traffic is plain `data:` URLs, so the downstream engine doesn't need any modification

## Status

Early. See [STATUS.md](STATUS.md) for the roadmap.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 baibaomen `<baibaomen@gmail.com>`.

If you use lmfetch (or vendor any of its modules into another project), please keep the copyright notice. That's the only condition.
