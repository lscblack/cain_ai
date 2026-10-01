"""Email intelligence schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.investigation import EntityOut, EvidenceOut


class EmailQuery(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    check_dns: bool = True


class EmailAnalysisOut(BaseModel):
    input: str
    valid_format: bool
    local: str | None
    domain: str | None
    gravatar_url: str | None
    derived_usernames: list[str]
    mx_records: list[str] | None
    has_mx: bool | None
    spf: str | None
    dmarc: str | None
    dns_checked: bool
    notes: list[str]


class EmailIntelligenceOut(BaseModel):
    analysis: EmailAnalysisOut
    local_entity_matches: list[EntityOut]
    local_evidence_matches: list[EvidenceOut]
    note: str = (
        "DNS/MX/SPF/DMARC and derived usernames are direct signals about the address "
        "and domain. Linking the address to a person is an inference, not a fact."
    )
