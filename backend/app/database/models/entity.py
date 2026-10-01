"""Entity — a node in an investigation's graph (face, phone, email, ...)."""
from __future__ import annotations

import uuid

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class Entity(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "entities"

    investigation_id: uuid.UUID = Field(index=True, nullable=False, foreign_key="investigations.id")
    type: str = Field(index=True, nullable=False)
    value: str = Field(nullable=False)
    label: str | None = Field(default=None)
    meta: dict = Field(default_factory=dict, sa_column=Column("metadata", JSONB, nullable=False))
