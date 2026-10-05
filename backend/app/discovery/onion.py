"""Dark-web (Tor onion) discovery for a search term.

Finds .onion addresses via Ahmia — a clearnet search engine that indexes public
Tor hidden services and filters out abuse material. Ahmia itself is reached over
the clearnet; the discovered .onion sites are then crawled through the SSRF-guarded
Tor-routed crawler (requires TOR_SOCKS_PROXY). Public-source OSINT only.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable
from urllib.parse import unquote, urlsplit

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("kai.discovery.onion")

TextGet = Callable[[str], Awaitable[str]]

AHMIA_SEARCH = "https://ahmia.fi/search/?q={q}"
# v2 (16) and v3 (56) onion addresses
_ONION_RE = re.compile(r"https?://[a-z2-7]{16}(?:[a-z2-7]{40})?\.onion[^\s\"'<>)]*", re.I)
_REDIRECT_RE = re.compile(r"redirect_url=([^\"'&<>]+)", re.I)


def onion_available() -> bool:
    """Onion discovery+crawl needs a configured Tor SOCKS proxy."""
    return bool(get_settings().tor_socks_proxy)


async def _default_get(url: str) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True,
                                 headers={"User-Agent": "KAI-OSINT/0.1"}) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


# Search-engine / infra onions that show up in result pages but aren't targets.
_ONION_STOP = {
    "juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion",  # ahmia
    "msydqstlz2kzerdg.onion",  # ahmia (old)
}


def _extract_onions(html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def push(u: str) -> None:
        u = u.strip()
        host = (urlsplit(u).hostname or "").lower()
        if host.endswith(".onion") and host not in seen and host not in _ONION_STOP:
            seen.add(host)
            found.append(u)

    # Ahmia wraps results in /search/redirect?...&redirect_url=<onion>
    for m in _REDIRECT_RE.findall(html):
        push(unquote(m))
    for m in _ONION_RE.findall(html):
        push(m)
    return found


async def search_onion(term: str, *, limit: int = 15, http_get: TextGet | None = None) -> list[str]:
    """Return up to `limit` distinct .onion URLs mentioning `term` (via Ahmia)."""
    if not term.strip():
        return []
    getter = http_get or _default_get
    try:
        from urllib.parse import quote

        html = await getter(AHMIA_SEARCH.format(q=quote(term)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ahmia search failed for %r: %s", term, exc)
        return []
    return _extract_onions(html)[:limit]
