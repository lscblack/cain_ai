"""Reverse-image discovery providers (external, key-gated).

These are *discovery* adapters — they surface candidate image URLs from public
reverse-image engines. KAI never depends on them for its permanent corpus, and
without an API key a provider reports UNAVAILABLE rather than inventing results.

A real call path (SerpAPI Google Lens / Yandex) is implemented behind an
injectable HTTP client; it only runs when a key is configured.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.core.config import get_settings
from app.providers.base import BaseProvider, ProviderHealth, ProviderType

# http_get(url, params) -> parsed JSON dict
HttpGet = Callable[[str, dict], Awaitable[dict]]


async def _default_http_get(url: str, params: dict) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


class SerpApiReverseImage(BaseProvider):
    """Google Lens / Yandex reverse image via SerpAPI (needs SERPAPI_API_KEY)."""

    name = "serpapi_reverse_image"
    type = ProviderType.REVERSE_IMAGE

    def __init__(self, http_get: HttpGet | None = None) -> None:
        self._http_get = http_get or _default_http_get

    @property
    def _key(self) -> str:
        return get_settings().serpapi_api_key

    @property
    def enabled(self) -> bool:  # type: ignore[override]
        return bool(self._key)

    async def health_check(self) -> ProviderHealth:
        configured = bool(self._key)
        return ProviderHealth(
            name=self.name,
            healthy=configured,
            configured=configured,
            detail="configured" if configured else "SERPAPI_API_KEY not set",
        )

    async def search(self, query: Any) -> list[dict]:
        """query: {image_url: str, engine?: 'google_lens'|'yandex'}.

        Returns candidate dicts: {source_url, image_url, title, provider}.
        """
        if not self._key:
            return []
        image_url = query.get("image_url") if isinstance(query, dict) else str(query)
        engine = (query.get("engine") if isinstance(query, dict) else None) or "google_lens"
        params = {"engine": engine, "url": image_url, "api_key": self._key}
        data = await self._http_get("https://serpapi.com/search", params)
        out: list[dict] = []
        for item in data.get("visual_matches", []) or []:
            out.append(
                {
                    "provider": self.name,
                    "source_url": item.get("link"),
                    "image_url": item.get("thumbnail") or item.get("image"),
                    "title": item.get("title"),
                }
            )
        return out
