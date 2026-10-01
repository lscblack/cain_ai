"""Contract models for the core investigation graph.

These Pydantic models describe the *shape* of entities, evidence, and
relationships that later phases will realize as concrete DB tables (Phase 2+).
They are the single source of truth for the fields every observation must
carry — most importantly provenance (``source_url`` + ``collected_at``) and an
explicit, bounded confidence that is never phrased as a confirmed identity.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    FACE = "face"
    PHONE = "phone"
    EMAIL = "email"
    USERNAME = "username"
    DOMAIN = "domain"
    URL = "url"
    IMAGE = "image"
    ORGANIZATION = "organization"
    LOCATION = "location"
    DOCUMENT = "document"
    VEHICLE = "vehicle"
    AIRCRAFT = "aircraft"
    VESSEL = "vessel"


class ConfidenceBand(str, Enum):
    """Human-facing wording — never 'confirmed identity'."""

    OBSERVED = "observed_on_source"
    POSSIBLE = "possible_association"
    STRONG = "strong_similarity"
    POTENTIAL_MATCH = "potential_match"


class EntityContract(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: EntityType
    value: str
    label: str | None = None


class EvidenceContract(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: EntityType
    source_url: str
    collected_at: datetime
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    hash: str | None = None
    confidence: float | None = None
    band: ConfidenceBand | None = None
    raw_metadata: dict = Field(default_factory=dict)
    processed_metadata: dict = Field(default_factory=dict)


class RelationshipContract(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_id: uuid.UUID
    target_id: uuid.UUID
    rel_type: str
    source_url: str
    observed_at: datetime
    confidence: float | None = None
    evidence_excerpt: str | None = None
