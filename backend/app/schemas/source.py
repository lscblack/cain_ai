"""Source (crawl target) schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.net import UnsafeUrlError, validate_public_url


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str
    allowed_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    max_depth: int = Field(default=1, ge=0, le=5)
    max_pages: int = Field(default=50, ge=1, le=5000)
    schedule: str = Field(default="manual", pattern="^(manual|hourly|6h|daily|weekly)$")

    @field_validator("base_url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        # Block SSRF targets at creation time (resolves DNS).
        try:
            validate_public_url(v)
        except UnsafeUrlError as exc:
            raise ValueError(f"unsafe base_url: {exc}")
        return v


class SourceOut(BaseModel):
    id: uuid.UUID
    name: str
    base_url: str
    domain: str
    allowed_paths: list[str]
    excluded_paths: list[str]
    max_depth: int
    max_pages: int
    schedule: str
    status: str
    last_crawled_at: str | None
    last_error: str | None
    created_at: datetime


class SourceStats(BaseModel):
    source_id: uuid.UUID
    pages: int
    images: int
    faces: int
    status: str
    last_crawled_at: str | None
