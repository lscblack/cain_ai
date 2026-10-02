"""Collect candidate site domains from public search (SerpAPI Google).

Key-gated: without SERPAPI_API_KEY this returns nothing (UNAVAILABLE). The HTTP
getter is injectable for offline tests.
"""
from __future__ import annotations

from typing import Awaitable, Callable
from urllib.parse import urlsplit

from app.core.config import get_settings

JsonGet = Callable[[str, dict], Awaitable[dict]]


async def _default_get(url: str, params: dict) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


def search_available() -> bool:
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
    """Run each query; return {domain: example_url}. Deduped by domain."""
    key = get_settings().serpapi_api_key
    if not key:
        return {}
    getter = http_get or _default_get
    found: dict[str, str] = {}
    for q in queries:
        try:
            data = await getter(
                "https://serpapi.com/search",
                {"engine": "google", "q": q, "num": per_query, "api_key": key},
            )
        except Exception:
            continue
        for item in (data.get("organic_results") or []):
            link = item.get("link")
            dom = _domain(link or "")
            if dom and dom not in found:
                found[dom] = f"https://{dom}/"
    return found
