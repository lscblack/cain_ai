"""Face record: a detected face with its ArcFace embedding and provenance.

Embeddings are stored as JSON float arrays (portable, no pgvector dependency at
current scale). The model + version + dimension are stored so the whole corpus
can be re-indexed when the model changes.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class Face(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "faces"

    investigation_id: uuid.UUID | None = Field(default=None, index=True, foreign_key="investigations.id")
    source_url: str | None = Field(default=None)

    image_hash: str = Field(index=True, nullable=False)
    face_crop_hash: str | None = Field(default=None, index=True)

    bbox: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    det_score: float = Field(default=0.0)
    quality: float = Field(default=0.0, index=True)

    model: str = Field(nullable=False)
    model_version: str = Field(nullable=False)
    embedding_dim: int = Field(nullable=False)
    embedding: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))

    extra: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
