"""The single operator account."""
from __future__ import annotations

from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class User(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "users"

    email: str = Field(index=True, unique=True, nullable=False)
    password_hash: str = Field(nullable=False)
