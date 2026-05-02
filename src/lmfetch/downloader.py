"""Pluggable image downloaders.

Three built-ins:
  - PlainDownloader            : stdlib urllib, no extras
  - ProxiedDownloader          : route via HTTP/HTTPS proxy (set http(s)_proxy on the opener)
  - BrowserSpoofDownloader     : custom UA + arbitrary headers (for hotlink-blocking CDNs)

Dispatch is glob-based on URL host, evaluated in order. The first matching
rule wins; put a `pattern="*"` catch-all last.

Errors raise FetchError so the server layer can fall back to the placeholder.
"""
from __future__ import annotations

import fnmatch
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Protocol


class FetchError(Exception):
    """Raised when a downloader cannot retrieve the URL."""


@dataclass(frozen=True)
class FetchResult:
    bytes_: bytes
    content_type: str | None
    status: int


class Downloader(Protocol):
    def fetch(self, url: str) -> FetchResult: ...


def _do_request(req: urllib.request.Request, opener: urllib.request.OpenerDirector | None = None,
                timeout: float = 30.0) -> FetchResult:
    o = opener or urllib.request.build_opener()
    try:
        with o.open(req, timeout=timeout) as r:
            data = r.read()
            return FetchResult(
                bytes_=data,
                content_type=r.headers.get("Content-Type"),
                status=r.status if hasattr(r, "status") else r.getcode(),
            )
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} for {req.full_url}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"URL error for {req.full_url}: {e.reason}") from e
    except OSError as e:
        raise FetchError(f"network error for {req.full_url}: {e}") from e


class PlainDownloader:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def fetch(self, url: str) -> FetchResult:
        return _do_request(urllib.request.Request(url), timeout=self.timeout)


class BrowserSpoofDownloader:
    DEFAULT_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.user_agent = user_agent or self.DEFAULT_UA
        self.extra_headers = dict(extra_headers or {})
        self.timeout = timeout

    def fetch(self, url: str) -> FetchResult:
        headers = {"User-Agent": self.user_agent, **self.extra_headers}
        return _do_request(urllib.request.Request(url, headers=headers), timeout=self.timeout)


class ProxiedDownloader:
    def __init__(self, proxy_url: str, *, timeout: float = 30.0) -> None:
        self.proxy_url = proxy_url
        self.timeout = timeout
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )

    def fetch(self, url: str) -> FetchResult:
        return _do_request(urllib.request.Request(url), opener=self._opener, timeout=self.timeout)


@dataclass(frozen=True)
class DomainRule:
    pattern: str
    downloader: Downloader


@dataclass
class _Router:
    rules: list[DomainRule] = field(default_factory=list)

    def fetch(self, url: str) -> FetchResult:
        host = urllib.parse.urlparse(url).hostname or ""
        for rule in self.rules:
            if fnmatch.fnmatch(host, rule.pattern):
                return rule.downloader.fetch(url)
        raise FetchError(f"no downloader matched host {host!r}")


def build_router(rules: list[DomainRule]) -> Downloader:
    return _Router(list(rules))
