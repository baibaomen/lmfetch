# lmfetch on alien (llm-dev wiring)

Insert lmfetch between `new-api` and `local-llm-server` so vision requests
hitting Qwen3.6 get their `image_url` parts fetched, cached, and rewritten
to `data:base64` — without changing anything client-side.

## Layout

```
client → llm-dev.baibaomen.com (new-api, channel #44 "local-qwen3.6-35b-a3b")
            base_url:  http://lmfetch:8000          ← M5 change
                │
                └─► lmfetch (this compose)
                        upstream:  http://local-llm-server:8080
                            │
                            └─► local-llm-server (llama.cpp + Qwen3.6-35B-A3B)
```

`new-api`, `lmfetch`, and `local-llm-server` all share the
`llm-devbaibaomencom_newapi-internal` docker network created by
`/data/llm-dev.baibaomen.com/docker-compose.yml`, so DNS just works.

## Bring up

On alien (`/data/lmfetch/`):

```bash
# 1. Build the image (from the lmfetch repo root)
docker build -t lmfetch:latest /path/to/lmfetch

# 2. Start
docker compose up -d

# 3. Smoke test
docker exec lmfetch python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read())"
# → b'{"status":"ok"}'

# 4. Switch new-api channel #44 base_url to http://lmfetch:8000
#    via the new-api admin UI, OR direct SQL:
docker exec llm-dev-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "UPDATE channels SET base_url='http://lmfetch:8000' WHERE id=44;"
# new-api picks up the change without restart (fetches per-request).
```

## Verify (Jack-visible)

```bash
curl -X POST https://llm-dev.baibaomen.com/v1/chat/completions \
  -H "Authorization: Bearer $BBM_LLM_DEV_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-35b-a3b",
    "messages": [{"role":"user","content":[
      {"type":"text","text":"What is the dominant subject of this image?"},
      {"type":"image_url","image_url":{"url":"https://httpbin.org/image/png"}}
    ]}],
    "max_tokens": 64,
    "chat_template_kwargs": {"enable_thinking": false}
  }' | jq -r '.choices[0].message.content'
# → expect a sentence describing the pig drawing
```

Cache lives in `./cache` (bind-mounted), capped at 10 GiB.

## Roll back

```bash
docker exec llm-dev-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "UPDATE channels SET base_url='http://local-llm-server:8080' WHERE id=44;"
docker compose down
```
