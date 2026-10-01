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
        v = (v or "").strip()
        # Accept a bare domain (example.com) by defaulting to https://.
        if v and "://" not in v:
            v = f"https://{v}"
        # Block SSRF targets at creation time (resolves DNS).
        try:
            validate_public_url(v)
        except UnsafeUrlError as exc:
            raise ValueError(f"unsafe base_url: {exc}")
        return v


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = None
    allowed_paths: list[str] | None = None
    excluded_paths: list[str] | None = None
    max_depth: int | None = Field(default=None, ge=0, le=5)
    max_pages: int | None = Field(default=None, ge=1, le=5000)
    schedule: str | None = Field(default=None, pattern="^(manual|hourly|6h|daily|weekly)$")
    status: str | None = Field(default=None, pattern="^(idle|paused|error)$")
    category: str | None = None
    priority: str | None = Field(default=None, pattern="^(high|medium|low)$")

    @field_validator("base_url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v and "://" not in v:
            v = f"https://{v}"
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
    category: str | None = None
    priority: str | None = None
    last_crawled_at: str | None
    last_error: str | None
    created_at: datetime


class BulkSourceIn(BaseModel):
    # Either a list of SourceCreate OR a CSV/line-based text blob.
    items: list[SourceCreate] | None = None
    csv: str | None = None
    # defaults applied to CSV rows that omit a field
    default_max_depth: int = Field(default=1, ge=0, le=5)
    default_max_pages: int = Field(default=50, ge=1, le=5000)
    default_schedule: str = Field(default="manual", pattern="^(manual|hourly|6h|daily|weekly)$")


class BulkSourceResult(BaseModel):
    created: list[SourceOut]
    errors: list[dict]


class SourceStats(BaseModel):
    source_id: uuid.UUID
    pages: int
    images: int
    faces: int
    status: str
    last_crawled_at: str | None
