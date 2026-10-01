"""Username presence provider across public platforms."""
from __future__ import annotations

from typing import Any

from app.intelligence.username.check import check_username, is_valid_username
from app.intelligence.username.http import httpx_fetch
from app.providers.base import BaseProvider, ProviderHealth, ProviderType


class UsernameProvider(BaseProvider):
    name = "public_username"
    type = ProviderType.USERNAME
    enabled = True

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name, healthy=True, configured=True, detail="public profile presence checks"
        )

    async def search(self, query: Any) -> list[dict]:
        username = query.get("username") if isinstance(query, dict) else str(query)
        platform_keys = query.get("platforms") if isinstance(query, dict) else None
        if not is_valid_username(username or ""):
            return []
        hits = await check_username(username, httpx_fetch, platform_keys=platform_keys)
        return [h.to_dict() for h in hits]
