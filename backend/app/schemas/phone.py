"""Phone intelligence schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.investigation import EntityOut, EvidenceOut


class PhoneQuery(BaseModel):
    number: str = Field(min_length=1, max_length=40)
    region: str | None = Field(default=None, max_length=2, description="ISO region hint, e.g. RW")


class PhoneAnalysisOut(BaseModel):
    input: str
    parsed: bool
    valid: bool
    possible: bool
    e164: str | None
    international: str | None
    national: str | None
    country_code: int | None
    region: str | None
    location: str | None
    carrier: str | None
    number_type: str
    variants: list[str]
    error: str | None


class PhoneIntelligenceOut(BaseModel):
    analysis: PhoneAnalysisOut
    local_entity_matches: list[EntityOut]
    local_evidence_matches: list[EvidenceOut]
    note: str = (
        "Metadata describes the number only. Appearance on a page is an observation, "
        "not proof of ownership."
    )
