"""Targeted, incremental domain crawler feeding the local face index.

Bounded by depth and page count, same-host only, honouring allowed/excluded
paths and SSRF rules. The HTTP fetcher and face engine are injected so the
pipeline is fully testable offline. Incremental: a page whose content hash is
unchanged since last crawl is skipped.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.net import UnsafeUrlError, validate_public_url
from app.crawlers.extract import extract_image_urls, extract_links, path_allowed
from app.database.models.face import Face
from app.database.models.source import Image, Page, Source
from app.intelligence.face.dedup import average_hash, sha256_bytes
from app.intelligence.face.engine import FaceEngine


@dataclass
class Fetched:
    status: int
    content_type: str = ""
    body: bytes = b""
    etag: str | None = None


Fetcher = Callable[[str], Awaitable[Fetched]]
RobotsCheck = Callable[[str], Awaitable[bool]]
SafeCheck = Callable[[str], Awaitable[bool]]


@dataclass
class CrawlStats:
    pages_processed: int = 0
    pages_skipped: int = 0
    pages_failed: int = 0
    images_indexed: int = 0
    images_duplicate: int = 0
    faces_indexed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


_IMG_TYPES = ("image/jpeg", "image/png", "image/webp", "image/bmp")
_MAX_IMAGES_PER_PAGE = 40
_MAX_IMAGE_BYTES = 12 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _safe(url: str) -> bool:
    try:
        validate_public_url(url)
        return True
    except UnsafeUrlError:
        return False


async def crawl_source(
    session: AsyncSession,
    source: Source,
    *,
    fetch: Fetcher,
    engine: FaceEngine | None = None,
    robots: RobotsCheck | None = None,
    safe_check: SafeCheck | None = None,
) -> CrawlStats:
    stats = CrawlStats()
    safe = safe_check or _safe
    base_host = urlsplit(source.base_url).hostname
    queue: deque[tuple[str, int]] = deque([(source.base_url, 0)])
    visited: set[str] = set()

    while queue and stats.pages_processed < source.max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if urlsplit(url).hostname != base_host:
            continue
        if not path_allowed(url, source.allowed_paths, source.excluded_paths):
            continue
        if not await safe(url):
            continue
        if robots is not None and not await robots(url):
            stats.pages_skipped += 1
            continue

        try:
            resp = await fetch(url)
        except Exception as exc:  # noqa: BLE001
            stats.pages_failed += 1
            stats.errors.append(f"{url}: {exc}")
            continue

        existing = (
            await session.execute(select(Page).where(Page.url == url, Page.source_id == source.id))
        ).scalar_one_or_none()

        if resp.status != 200 or "html" not in (resp.content_type or ""):
            if existing is None:
                existing = Page(source_id=source.id, url=url)
                session.add(existing)
            existing.http_status = resp.status
            existing.crawl_status = "failed" if resp.status != 200 else "skipped"
            existing.last_crawled_at = _now()
            stats.pages_failed += 1 if resp.status != 200 else 0
            await session.flush()
            continue

        content_hash = sha256_bytes(resp.body)
        html = resp.body.decode("utf-8", "replace")

        if existing is not None and existing.content_hash == content_hash:
            existing.last_crawled_at = _now()
            existing.crawl_status = "skipped"
            stats.pages_skipped += 1
            await session.flush()
        else:
            page = existing or Page(source_id=source.id, url=url)
            changed = page.content_hash != content_hash
            page.content_hash = content_hash
            page.http_status = resp.status
            page.etag = resp.etag
            page.last_crawled_at = _now()
            if changed:
                page.last_changed_at = _now()
            page.crawl_status = "ok"
            session.add(page)
            await session.flush()

            img_urls = extract_image_urls(html, url)[:_MAX_IMAGES_PER_PAGE]
            page_images = 0
            page_faces = 0
            for img_url in img_urls:
                faces_added, is_dup = await _process_image(
                    session, source, page, img_url, fetch=fetch, engine=engine, stats=stats, safe=safe
                )
                if is_dup:
                    continue
                page_images += 1
                page_faces += faces_added
            page.images_found = page_images
            page.faces_found = page_faces
            session.add(page)
            await session.flush()
            stats.pages_processed += 1

        # enqueue links
        if depth < source.max_depth:
            for link in extract_links(html, url, same_host_only=True):
                if link not in visited and path_allowed(
                    link, source.allowed_paths, source.excluded_paths
                ):
                    queue.append((link, depth + 1))

    source.last_crawled_at = _now()
    source.status = "idle"
    session.add(source)
    await session.flush()
    return stats


async def _process_image(
    session: AsyncSession,
    source: Source,
    page: Page,
    img_url: str,
    *,
    fetch: Fetcher,
    engine: FaceEngine | None,
    stats: CrawlStats,
    safe: SafeCheck = _safe,
) -> tuple[int, bool]:
    if not await safe(img_url):
        return 0, False
    try:
        resp = await fetch(img_url)
    except Exception:
        return 0, False
    if resp.status != 200 or resp.content_type not in _IMG_TYPES:
        return 0, False
    if not resp.body or len(resp.body) > _MAX_IMAGE_BYTES:
        return 0, False

    image_hash = sha256_bytes(resp.body)
    dup = (
        await session.execute(select(Image).where(Image.image_hash == image_hash))
    ).scalar_one_or_none()
    if dup is not None:
        stats.images_duplicate += 1
        return 0, True

    phash = average_hash(resp.body)
    img_row = Image(
        source_id=source.id,
        page_id=page.id,
        image_url=img_url,
        image_hash=image_hash,
        phash=phash,
    )
    session.add(img_row)
    stats.images_indexed += 1

    faces_added = 0
    if engine is not None and engine.available():
        try:
            faces = engine.detect_and_embed(resp.body)
        except Exception:
            faces = []
        from app.intelligence.face.crops import save_crop

        for f in faces:
            rec = Face(
                source_url=page.url,
                image_hash=image_hash,
                bbox=f.bbox,
                det_score=f.det_score,
                quality=f.quality,
                model=engine.model_name,
                model_version=engine.model_version,
                embedding_dim=len(f.embedding),
                embedding=f.embedding,
                extra=f.extra,
            )
            session.add(rec)
            await session.flush()
            save_crop(resp.body, f.bbox, str(rec.id))
            faces_added += 1
        img_row.faces_found = faces_added
        stats.faces_indexed += faces_added
    await session.flush()
    return faces_added, False
