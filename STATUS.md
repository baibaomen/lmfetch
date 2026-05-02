# lmfetch — STATUS

> 路线图视角：从「llama.cpp 同步 URL 拉图老踩坑」走到「engine-agnostic 的图片 fetch+cache sidecar，主流引擎都能直接挂上」。

## 总体路线图

```
现状：llama.cpp / vLLM / SGLang 都内置「服务端拉 image_url」逻辑。
       拉不到就 500，拉得到也每次重拉，硬编码 10MB / 10s，无法定制 UA / 代理。
       ↓
M0  仓库脚手架（README/LICENSE/pyproject/包骨架）       ← 现在
       ↓
M1  cache：URL+内容双哈希 CAS、SQLite 索引、LRU 配额淘汰   （TDD）
       ↓
M2  downloader：plain / proxied / browser-spoof 三种内置  （TDD）
       并提供按域名规则路由的注册机制
       ↓
M3  server：FastAPI 透传 OpenAI vision 协议
       消息里所有 image_url → 走 cache → 替换为 data:base64
       下游（llama.cpp / vLLM / …）只看到 data URL
       ↓
M4  placeholder：拉不到也不抛，回 not_available.png
       ↓
M5  部署：alien 上 docker-compose，挂在 new-api 与 llama-server 之间
       ↓
M6  开源发布：v0.1，docs，examples（llama.cpp + vLLM compose）
       ↓
M7  上游回馈：把 max_size/timeout 配置化先 PR 到 llama.cpp；
            视情况贡献 C++ 版 cache 模块
```

## 当前位置

- [x] M0 脚手架
- [x] M1 cache（CAS + LRU + 多版本，TDD 全绿 + e2e 验收）
- [x] M2 downloader（plain / spoof / proxied + 域名路由，e2e 真实 httpbin/proxy 验收）
- [x] M3 server（FastAPI 透传，image_url → data:base64，**真实 qwen3.6 e2e 通过**）
- [x] M4 placeholder 接线（fetch 失败回 not_available.png，**qwen3.6 读出 "Image Not Available"**）
- [x] M5 alien 部署（Dockerfile + compose 接到 llm-dev new-api 和 local-llm-server 之间，
  **真线 vision 请求过 lmfetch 缓存命中后 qwen 仍正常回答**）
- [ ] M6 OSS 发布（下一步）
- [ ] M5 alien 部署
- [ ] M6 OSS 发布
- [ ] M7 上游 PR

## 验收口径（Jack 视角）

- M1 完成：跑 `pytest`，全绿；同 URL 灌两个不同字节内容，目录里能看到两个版本，`Cache.get(url)` 都返回。
- M2 完成：用一个被 GFW 封的图片地址（如 google CDN）配上 proxied 规则，能下载下来。
- M3 完成：客户端发 `{"type":"image_url","url":"https://..."}`，下游 llama.cpp 收到的是 `data:image/png;base64,...`，回答正确。
- M4 完成：故意把 URL 写成 404，整个链路不 500，模型收到一张写着 "Image Not Available" 的图。
- M5 完成：alien 上能从 new-api 走 lmfetch 走 llama-server 完整识别一张 minio 图。
- M6 完成：发个 v0.1 release tag，README 里 examples 别人能 docker-compose up 直接用。
