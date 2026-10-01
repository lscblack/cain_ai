"""Universal search schemas."""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.investigation import EntityOut, EvidenceOut


class SearchResponse(BaseModel):
    query: str
    detected_type: str
    normalized: str
    entity_matches: list[EntityOut]
    evidence_matches: list[EvidenceOut]
