"""Real HTTP fetcher + robots.txt gate for the crawler (SSRF-guarded).

Egress policy: .onion always via Tor; all other traffic via `crawl_proxy` when
set (Tor SOCKS or an http proxy) so crawling can be anonymised. With a system
VPN (e.g. ProtonVPN connected) leave `crawl_proxy` empty — OS egress is already
VPN'd. `crawl_require_proxy` fails closed (no proxy -> no open-web crawl).
Per-host rate limiting honours a politeness delay and robots Crawl-delay.
"""
from __future__ import annotations

import asyncio
import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import get_settings
from app.core.net import UnsafeUrlError, validate_public_url
from app.crawlers.runner import Fetched

# A realistic desktop browser UA so public pages don't 403 a bot string. We
# still honour robots.txt and only fetch public pages — this just lets us see
# what a normal browser would. No auth, no paywalls.
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
# Browser-like headers improve open-web access on sites that sniff them.
_BROWSER_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Upgrade-Insecure-Requests": "1",
}

# Per-host last-request timestamps for rate limiting (politeness).
_last_hit: dict[str, float] = {}
_host_locks: dict[str, asyncio.Lock] = {}
_robots_delay: dict[str, float] = {}  # host -> robots Crawl-delay (seconds)

# Wikipedia blocks scraping its /wiki/ pages but its REST API is open + keyless.
_WIKI_RE = re.compile(r"^https?://([a-z-]+)\.wikipedia\.org/wiki/([^?#]+)", re.I)
# Wikimedia's UA policy wants a descriptive agent (not a browser string).
_WIKI_UA = "KAI-OSINT/1.0 (OSINT research tool; local, public pages only; contact tech@nexventures.net)"


def _wikipedia_api(url: str) -> str | None:
    """Rewrite a Wikipedia article URL to its keyless REST HTML API endpoint."""
    m = _WIKI_RE.match(url)
    if not m:
        return None
    lang, title = m.group(1), m.group(2)
    return f"https://{lang}.wikipedia.org/api/rest_v1/page/html/{title}"


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

    # Wikipedia → keyless REST API (the /wiki/ page itself blocks bots).
    wiki_api = _wikipedia_api(url)
    fetch_url = wiki_api or url
    headers = {**_BROWSER_HEADERS, "User-Agent": _WIKI_UA} if wiki_api else _BROWSER_HEADERS

    async def _get(via: str | None) -> Fetched:
        async with httpx.AsyncClient(
            timeout=30.0 if via else 15.0, follow_redirects=True,
            headers=headers, proxy=via,
        ) as client:
            resp = await client.get(fetch_url)
            return Fetched(
                status=resp.status_code,
                content_type=resp.headers.get("content-type", "").split(";")[0].strip(),
                body=resp.content,
                etag=resp.headers.get("etag"),
            )

    try:
        res = await _get(proxy)
    except Exception:
        res = Fetched(status=0)
    # If an open-web page blocked us (datacenter/VPN IP reputation), retry once
    # over Tor — its exit IP differs and often isn't blocked.
    if (
        res.status in (0, 403, 429, 451, 503)
        and not host.endswith(".onion")
        and not proxy
        and get_settings().tor_socks_proxy
    ):
        try:
            alt = await _get(get_settings().tor_socks_proxy)
            if alt.status == 200:
                return alt
        except Exception:
            pass
    return res


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
