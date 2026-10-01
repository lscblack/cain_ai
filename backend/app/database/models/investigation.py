"""Investigation (case) — the root everything attaches to."""
from __future__ import annotations

import uuid

from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class Investigation(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "investigations"

    code: str = Field(index=True, unique=True, nullable=False)  # CASE-YYYY-NNNN
    name: str = Field(nullable=False)
    description: str | None = Field(default=None)
    status: str = Field(default="open", nullable=False)  # open | archived
    created_by: uuid.UUID | None = Field(default=None, index=True)
