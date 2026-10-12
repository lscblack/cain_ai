"""Real HTTP fetcher + robots.txt gate for the crawler (SSRF-guarded).

Egress policy: .onion always via Tor; all other traffic via `crawl_proxy` when
set (Tor SOCKS or an http proxy) so crawling can be anonymised. With a system
VPN (e.g. ProtonVPN connected) leave `crawl_proxy` empty — OS egress is already
VPN'd. `crawl_require_proxy` fails closed (no proxy -> no open-web crawl).
Per-host rate limiting honours a politeness delay and robots Crawl-delay.
"""
from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import get_settings
from app.core.net import UnsafeUrlError, validate_public_url
from app.crawlers.runner import Fetched

_UA = "KAI-OSINT/0.1 (+local research; public pages only; honours robots.txt)"

# Per-host last-request timestamps for rate limiting (politeness).
_last_hit: dict[str, float] = {}
_host_locks: dict[str, asyncio.Lock] = {}
_robots_delay: dict[str, float] = {}  # host -> robots Crawl-delay (seconds)


def _proxy_for(url: str) -> str | None:
    """Tor SOCKS for .onion; otherwise the configured all-traffic crawl proxy."""
    s = get_settings()
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith(".onion"):
        return s.tor_socks_proxy or None
    return s.crawl_proxy or None


async def _rate_limit(host: str, extra_delay: float = 0.0) -> None:
    s = get_settings()
    delay = max(s.crawl_rate_delay, extra_delay, _robots_delay.get(host, 0.0))
    if delay <= 0:
        return
    lock = _host_locks.setdefault(host, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        wait = delay - (now - _last_hit.get(host, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _last_hit[host] = time.monotonic()


async def httpx_fetch(url: str) -> Fetched:
    try:
        validate_public_url(url)
    except UnsafeUrlError:
        return Fetched(status=0)
    host = (urlsplit(url).hostname or "").lower()
    proxy = _proxy_for(url)
    if host.endswith(".onion") and not proxy:
        return Fetched(status=0)  # onion requested but Tor not configured
    # Fail closed: don't let open-web crawls leave without an anonymising proxy.
    if (not host.endswith(".onion") and get_settings().crawl_require_proxy and not proxy):
        return Fetched(status=0)
    await _rate_limit(host)
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
        try:
            cd = rp.crawl_delay(_UA)
            if cd:
                _robots_delay[(urlsplit(base).hostname or "").lower()] = float(cd)
        except Exception:
            pass
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
