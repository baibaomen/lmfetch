"""Content-addressed image cache (URL hash + content hash, LRU eviction).

Implementation lands in M1 — TDD'd from tests/test_cache.py.
"""
from __future__ import annotations
