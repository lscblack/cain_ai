"""Local phone-intelligence provider (offline, libphonenumber-backed).

Implements the BaseProvider contract. It performs no network calls and makes no
ownership claims — it returns observed metadata about the number itself.
"""
from __future__ import annotations

from typing import Any

from app.intelligence.phone.normalize import analyze_phone
from app.providers.base import BaseProvider, ProviderHealth, ProviderType


class PhoneProvider(BaseProvider):
    name = "local_phone"
    type = ProviderType.PHONE
    enabled = True

    async def health_check(self) -> ProviderHealth:
        # Offline library; always available once imported.
        try:
            analyze_phone("+250788123456")
            return ProviderHealth(name=self.name, healthy=True, configured=True, detail="libphonenumber")
        except Exception as exc:  # pragma: no cover - defensive
            return ProviderHealth(name=self.name, healthy=False, detail=str(exc))

    async def search(self, query: Any) -> list[dict]:
        """query: {number: str, region: str | None}."""
        number = query.get("number") if isinstance(query, dict) else str(query)
        region = query.get("region") if isinstance(query, dict) else None
        analysis = analyze_phone(number or "", region)
        return [analysis.to_dict()]
