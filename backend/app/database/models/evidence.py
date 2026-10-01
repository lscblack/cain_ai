"""Evidence — a provenanced observation attached to an investigation/entity."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class Evidence(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "evidence"

    investigation_id: uuid.UUID = Field(index=True, nullable=False, foreign_key="investigations.id")
    entity_id: uuid.UUID | None = Field(default=None, index=True, foreign_key="entities.id")
    type: str = Field(nullable=False)

    # Provenance — never optional.
    source_url: str = Field(nullable=False)
    collected_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)

    first_seen: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    last_seen: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))

    hash: str | None = Field(default=None, index=True)
    confidence: float | None = Field(default=None)
    band: str | None = Field(default=None)

    raw_metadata: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    processed_metadata: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
