"""Relationship — an *observed* edge between two entities (never 'same person')."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class Relationship(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "relationships"

    investigation_id: uuid.UUID = Field(index=True, nullable=False, foreign_key="investigations.id")
    source_entity_id: uuid.UUID = Field(nullable=False, foreign_key="entities.id")
    target_entity_id: uuid.UUID = Field(nullable=False, foreign_key="entities.id")

    rel_type: str = Field(nullable=False)
    source_url: str = Field(nullable=False)
    observed_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)
    confidence: float | None = Field(default=None)
    evidence_excerpt: str | None = Field(default=None)
