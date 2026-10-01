"""Investigation / entity / evidence / relationship schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.net import UnsafeUrlError
from app.database.entities import ConfidenceBand, EntityType


def _validate_http_url(v: str) -> str:
    """Lightweight scheme/host check (no network) reusing SSRF rules' spirit."""
    from urllib.parse import urlsplit

    parts = urlsplit(v)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise UnsafeUrlError("source_url must be an absolute http(s) URL")
    return v


# ---- Investigation ----------------------------------------------------------
class InvestigationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class InvestigationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(default=None, pattern="^(open|archived)$")


class InvestigationOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class InvestigationDetail(InvestigationOut):
    entity_count: int
    evidence_count: int
    relationship_count: int


# ---- Entity -----------------------------------------------------------------
class EntityCreate(BaseModel):
    type: EntityType
    value: str = Field(min_length=1, max_length=2000)
    label: str | None = Field(default=None, max_length=200)
    metadata: dict = Field(default_factory=dict)


class EntityOut(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID
    type: str
    value: str
    label: str | None
    metadata: dict
    created_at: datetime


# ---- Evidence ---------------------------------------------------------------
class EvidenceCreate(BaseModel):
    type: EntityType
    source_url: str
    collected_at: datetime | None = None
    entity_id: uuid.UUID | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    hash: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    band: ConfidenceBand | None = None
    raw_metadata: dict = Field(default_factory=dict)
    processed_metadata: dict = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v)


class EvidenceOut(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID
    entity_id: uuid.UUID | None
    type: str
    source_url: str
    collected_at: datetime
    first_seen: datetime | None
    last_seen: datetime | None
    hash: str | None
    confidence: float | None
    band: str | None
    raw_metadata: dict
    processed_metadata: dict
    created_at: datetime


# ---- Relationship -----------------------------------------------------------
class RelationshipCreate(BaseModel):
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    rel_type: str = Field(min_length=1, max_length=100)
    source_url: str
    observed_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_excerpt: str | None = Field(default=None, max_length=2000)

    @field_validator("source_url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v)


class RelationshipOut(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    rel_type: str
    source_url: str
    observed_at: datetime
    confidence: float | None
    evidence_excerpt: str | None
    created_at: datetime


# ---- Graph ------------------------------------------------------------------
class GraphOut(BaseModel):
    nodes: list[EntityOut]
    edges: list[RelationshipOut]
