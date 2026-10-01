"""BaseProvider — the contract every external intelligence source implements.

Later phases add concrete providers (phone, reverse-image, maps, aviation...)
by subclassing this. The investigation engine depends only on this interface,
so providers can be added without touching the core.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel


class ProviderType(str, Enum):
    PHONE = "phone"
    EMAIL = "email"
    USERNAME = "username"
    DOMAIN = "domain"
    REVERSE_IMAGE = "reverse_image"
    MAP = "map"
    AVIATION = "aviation"
    MARITIME = "maritime"
    SATELLITE = "satellite"
    WEATHER = "weather"
    CCTV = "cctv"
    AI = "ai"
    OTHER = "other"


class ProviderHealth(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None
    configured: bool = False


class BaseProvider(ABC):
    """Abstract provider. Subclasses set ``name``/``type`` and implement methods."""

    name: str
    type: ProviderType
    enabled: bool = False

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Return whether the provider is reachable and configured."""
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: Any) -> list[dict]:
        """Run a provider-specific search; return raw result dicts (with provenance)."""
        raise NotImplementedError

    async def enrich(self, entity: Any) -> dict:
        """Optional enrichment of an existing entity. Default: no-op."""
        return {}

    def rate_limit(self) -> dict:
        """Describe this provider's rate limit (requests/window). Default: none."""
        return {}

    def configuration(self) -> dict:
        """Non-secret configuration summary safe to show in the UI."""
        return {"name": self.name, "type": getattr(self.type, "value", None), "enabled": self.enabled}
