"""Crawl source, crawled pages, and extracted images (local index)."""
from __future__ import annotations

import uuid

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class Source(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "sources"

    name: str = Field(nullable=False)
    base_url: str = Field(nullable=False)
    domain: str = Field(index=True, nullable=False)
    allowed_paths: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    excluded_paths: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    max_depth: int = Field(default=1)
    max_pages: int = Field(default=50)
    schedule: str = Field(default="manual")  # manual|hourly|6h|daily|weekly
    status: str = Field(default="idle")  # idle|crawling|error|paused
    category: str | None = Field(default=None, index=True)
    priority: str | None = Field(default=None, index=True)  # high|medium|low
    last_crawled_at: str | None = Field(default=None)
    last_error: str | None = Field(default=None)


class Page(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "pages"

    source_id: uuid.UUID = Field(index=True, nullable=False, foreign_key="sources.id")
    url: str = Field(index=True, nullable=False)
    content_hash: str | None = Field(default=None, index=True)
    http_status: int | None = Field(default=None)
    etag: str | None = Field(default=None)
    last_crawled_at: str | None = Field(default=None)
    last_changed_at: str | None = Field(default=None)
    crawl_status: str = Field(default="pending")  # pending|ok|skipped|failed
    images_found: int = Field(default=0)
    faces_found: int = Field(default=0)
    title: str | None = Field(default=None)
    description: str | None = Field(default=None)
    emails: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]"))
    phones: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]"))
    usernames: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]"))


class Image(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "images"

    source_id: uuid.UUID | None = Field(default=None, index=True, foreign_key="sources.id")
    page_id: uuid.UUID | None = Field(default=None, index=True, foreign_key="pages.id")
    image_url: str = Field(nullable=False)
    image_hash: str = Field(index=True, nullable=False)  # sha256
    phash: str | None = Field(default=None, index=True)  # perceptual hash (hex)
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)
    faces_found: int = Field(default=0)
