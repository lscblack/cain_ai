"""Audit log — append-only record of operator actions."""
from __future__ import annotations

import uuid

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class AuditLog(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "audit_logs"

    actor_id: uuid.UUID | None = Field(default=None, index=True)
    action: str = Field(nullable=False, index=True)
    detail: dict | None = Field(default=None, sa_column=Column(JSONB))
    ip: str | None = Field(default=None)
