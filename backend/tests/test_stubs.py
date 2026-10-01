from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.database.entities import EntityType, EvidenceContract
from app.providers.base import BaseProvider, ProviderHealth, ProviderType


def test_base_provider_is_abstract():
    with pytest.raises(TypeError):
        BaseProvider()  # type: ignore[abstract]


async def test_concrete_provider_can_be_built():
    class Dummy(BaseProvider):
        name = "dummy"
        type = ProviderType.OTHER

        async def health_check(self) -> ProviderHealth:
            return ProviderHealth(name=self.name, healthy=True, configured=True)

        async def search(self, query):
            return [{"q": query}]

    d = Dummy()
    health = await d.health_check()
    assert health.healthy is True
    assert await d.search("x") == [{"q": "x"}]
    assert d.configuration()["type"] == "other"


def test_evidence_requires_provenance():
    with pytest.raises(ValidationError):
        EvidenceContract(type=EntityType.PHONE)  # missing source_url + collected_at

    ev = EvidenceContract(
        type=EntityType.PHONE,
        source_url="https://example.com/contact",
        collected_at=datetime.now(timezone.utc),
    )
    assert ev.source_url.startswith("https://")
