"""FastAPI passthrough server (M3).

Receives OpenAI-compatible /v1/chat/completions, rewrites every
image_url message part to data:base64 (going through cache + downloader),
then forwards the request to the configured upstream engine.
"""
from __future__ import annotations
