"""Collect candidate site domains from public web search.

Primary backend is SerpAPI (Google) when a key is configured and has budget;
otherwise it falls back to a keyless DuckDuckGo HTML scrape so discovery keeps
working without paid search credits. HTTP getters are injectable for offline tests.
"""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable
from urllib.parse import quote, unquote, urlsplit

from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger("kai.discovery.search")

JsonGet = Callable[[str, dict], Awaitable[dict]]
TextGet = Callable[[str], Awaitable[str]]

# DuckDuckGo HTML result links wrap the target in ...?uddg=<urlencoded>
_DDG_UDDG_RE = re.compile(r"uddg=([^&\"']+)")
_DDG_HREF_RE = re.compile(r'class="result__a"[^>]*href="([^"]+)"', re.I)


async def _default_get(url: str, params: dict) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def _default_text(url: str) -> str:
    import httpx

    async with httpx.AsyncClient(
        timeout=25.0, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) KAI-OSINT/0.1"},
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


def search_available() -> bool:
    # Always available: SerpAPI when keyed+funded, else the keyless DuckDuckGo fallback.
    return True


def serpapi_available() -> bool:
    return bool(get_settings().serpapi_api_key)


def _domain(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname
        return host.lower().lstrip("www.") if host else None
    except Exception:
        return None


async def search_candidates(
    queries: list[str], *, per_query: int = 10, http_get: JsonGet | None = None
) -> dict[str, str]:
    """SerpAPI backend. Returns {domain: example_url}; {} if no key / exhausted."""
    key = get_settings().serpapi_api_key
    if not key:
        return {}
    getter = http_get or _default_get
    found: dict[str, str] = {}
    exhausted = False
    for q in queries:
        if exhausted:
            break
        try:
            data = await getter(
                "https://serpapi.com/search",
                {"engine": "google", "q": q, "num": per_query, "api_key": key},
            )
        except Exception:
            continue
        if isinstance(data, dict) and data.get("error"):
            logger.warning("serpapi: %s", data.get("error"))
            exhausted = True  # out of searches / bad key — stop hammering
            break
        for item in (data.get("organic_results") or []):
            dom = _domain(item.get("link") or "")
            if dom and dom not in found:
                found[dom] = f"https://{dom}/"
    return found


def _ddg_links(html: str) -> list[str]:
    urls: list[str] = []
    for href in _DDG_HREF_RE.findall(html):
        m = _DDG_UDDG_RE.search(href)
        target = unquote(m.group(1)) if m else href
        if target.startswith("//"):
            target = "https:" + target
        if target.startswith("http"):
            urls.append(target)
    if not urls:  # fallback: any uddg anywhere
        for enc in _DDG_UDDG_RE.findall(html):
            urls.append(unquote(enc))
    return urls


async def search_candidates_ddg(
    queries: list[str], *, max_queries: int = 60, http_get_text: TextGet | None = None,
    delay: float = 0.8,
) -> dict[str, str]:
    """Keyless DuckDuckGo HTML backend. Capped + throttled to avoid rate limiting."""
    getter = http_get_text or _default_text
    found: dict[str, str] = {}
    for i, q in enumerate(queries[:max_queries]):
        try:
            html = await getter(f"https://html.duckduckgo.com/html/?q={quote(q)}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("ddg query failed: %s", exc)
            if http_get_text is None:
                await asyncio.sleep(delay)
            continue
        for link in _ddg_links(html):
            dom = _domain(link)
            if dom and not dom.endswith("duckduckgo.com") and dom not in found:
                found[dom] = f"https://{dom}/"
        if http_get_text is None and i < len(queries) - 1:
            await asyncio.sleep(delay)  # be polite to DDG
    return found


async def discover_candidates(queries: list[str], *, per_query: int = 10) -> dict[str, str]:
    """Try SerpAPI first; fall back to DuckDuckGo when it returns nothing."""
    found: dict[str, str] = {}
    if serpapi_available():
        found = await search_candidates(queries, per_query=per_query)
    if not found:
        found = await search_candidates_ddg(queries)
        if found:
            logger.info("discovery: used DuckDuckGo fallback (%d domains)", len(found))
    return found
