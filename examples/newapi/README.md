# Example: new-api / one-api gateway → lmfetch → llama.cpp (or any vision engine)

This compose snippet drops `lmfetch` into an existing OpenAI-compatible gateway
stack so vision requests with `image_url` get fetched, cached, and rewritten to
`data:base64` before hitting the inference engine — without changing anything
client-side.

## Topology

```
client → gateway (new-api / one-api / LiteLLM)
            channel base_url:  http://lmfetch:8000
                │
                └─►  lmfetch  upstream=http://inference:8080
                        │
                        └─►  vision-capable engine (llama.cpp / vLLM / SGLang)
```

For DNS to "just work" between containers, all three must share a docker
network. Easiest path: join the network your gateway already created.

## Bring up

```bash
# 1. Pull the image (or build locally with `docker build -t lmfetch:latest .`
#    from the repo root and switch the `image:` line accordingly).
docker compose pull

# 2. Edit docker-compose.yml:
#    - LMFETCH_UPSTREAM_URL  → your inference container DNS name + port
#    - networks.gateway-net.name → the external network shared by your gateway
#      and inference containers (e.g. `mygateway_default`)

# 3. Start
docker compose up -d

# 4. Smoke test
docker exec lmfetch python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read())"
# → b'{"status":"ok"}'

# 5. In the gateway admin UI (or DB), point the relevant channel's base_url at
#    `http://lmfetch:8000`. The gateway calls lmfetch, lmfetch calls upstream.
```

## Verify (vision round-trip)

From any client that talks to the gateway:

```bash
curl -X POST https://your-gateway.example.com/v1/chat/completions \
  -H "Authorization: Bearer $YOUR_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-vision-model",
    "messages": [{"role":"user","content":[
      {"type":"text","text":"What is the dominant subject of this image?"},
      {"type":"image_url","image_url":{"url":"https://httpbin.org/image/png"}}
    ]}],
    "max_tokens": 64
  }' | jq -r '.choices[0].message.content'
# → expect a sentence describing the picture
```

The cache lives in `./cache` (bind-mounted), capped at 10 GiB by default.

## Roll back

Point the gateway channel's `base_url` back at the inference engine directly,
then `docker compose down`. Cache directory is left intact unless you remove it
manually.
