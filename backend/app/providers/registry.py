"""Provider registry.

A single place to register and look up providers so the investigation engine,
the Power Up panel (Phase 14), and health checks don't need to know concrete
classes. Providers register themselves here at import time.
"""
from __future__ import annotations

from app.providers.base import BaseProvider, ProviderHealth


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}

    def register(self, provider: BaseProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(name)

    def all(self) -> list[BaseProvider]:
        return list(self._providers.values())

    def by_type(self, type_value: str) -> list[BaseProvider]:
        return [p for p in self._providers.values() if getattr(p.type, "value", None) == type_value]

    async def health(self) -> list[ProviderHealth]:
        return [await p.health_check() for p in self._providers.values()]


registry = ProviderRegistry()


def _bootstrap() -> None:
    from app.providers.email_provider import EmailProvider
    from app.providers.phone_provider import PhoneProvider
    from app.providers.username_provider import UsernameProvider

    registry.register(PhoneProvider())
    registry.register(EmailProvider())
    registry.register(UsernameProvider())


_bootstrap()
