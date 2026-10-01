"""Local email-intelligence provider (DNS/MX/SPF/DMARC + derivations)."""
from __future__ import annotations

from typing import Any

from app.intelligence.email.analyze import analyze_email, default_dns_resolver
from app.providers.base import BaseProvider, ProviderHealth, ProviderType


class EmailProvider(BaseProvider):
    name = "local_email"
    type = ProviderType.EMAIL
    enabled = True

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name, healthy=True, configured=True, detail="format + dns (dnspython)"
        )

    async def search(self, query: Any) -> list[dict]:
        email = query.get("email") if isinstance(query, dict) else str(query)
        check_dns = query.get("check_dns", True) if isinstance(query, dict) else True
        resolver = default_dns_resolver if check_dns else None
        return [analyze_email(email or "", dns_resolver=resolver).to_dict()]
