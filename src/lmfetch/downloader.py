"""Pluggable downloaders.

Built-ins land in M2:
- plain          httpx default
- proxied        per-domain HTTP/SOCKS proxy
- browser-spoof  custom UA + Accept-Language headers

Dispatch is glob-based on URL host.
"""
from __future__ import annotations
