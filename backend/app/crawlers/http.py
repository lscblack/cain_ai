"""Real HTTP fetcher + robots.txt gate for the crawler (SSRF-guarded)."""
from __future__ import annotations

import urllib.robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import get_settings
from app.core.net import UnsafeUrlError, validate_public_url
from app.crawlers.runner import Fetched

_UA = "KAI-OSINT/0.1 (+local research; public pages only; honours robots.txt)"


def _proxy_for(url: str) -> str | None:
    """Return the Tor SOCKS proxy for .onion URLs when configured, else None."""
    host = urlsplit(url).hostname or ""
    if host.lower().endswith(".onion"):
        return get_settings().tor_socks_proxy or None
    return None


async def httpx_fetch(url: str) -> Fetched:
    try:
        validate_public_url(url)
    except UnsafeUrlError:
        return Fetched(status=0)
    proxy = _proxy_for(url)
    if urlsplit(url).hostname.lower().endswith(".onion") and not proxy:
        return Fetched(status=0)  # onion requested but Tor not configured
    try:
        async with httpx.AsyncClient(
            timeout=30.0 if proxy else 15.0, follow_redirects=True,
            headers={"User-Agent": _UA}, proxy=proxy,
        ) as client:
            resp = await client.get(url)
            return Fetched(
                status=resp.status_code,
                content_type=resp.headers.get("content-type", "").split(";")[0].strip(),
                body=resp.content,
                etag=resp.headers.get("etag"),
            )
    except Exception:
        return Fetched(status=0)


class RobotsGate:
    """Caches robots.txt per host and answers can-fetch for the KAI UA."""

    def __init__(self) -> None:
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    async def _load(self, base: str) -> urllib.robotparser.RobotFileParser | None:
        robots_url = urljoin(base, "/robots.txt")
        resp = await httpx_fetch(robots_url)
        if resp.status != 200 or not resp.body:
            return None  # no robots -> allow
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(resp.body.decode("utf-8", "replace").splitlines())
        return rp

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._cache:
            try:
                self._cache[host] = await self._load(host)
            except Exception:
                self._cache[host] = None
        rp = self._cache[host]
        if rp is None:
            return True
        return rp.can_fetch(_UA, url)
