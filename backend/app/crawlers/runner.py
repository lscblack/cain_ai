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
from app.crawlers.extract import (
    extract_contacts,
    extract_structured,
    enrich_from_structured,
    region_for_host,
    extract_images_with_context,
    extract_links,
    extract_page_meta,
    extract_person_names,
    path_allowed,
)
from app.database.models.face import Face
from app.database.models.source import Image, Page, Source
from app.intelligence.face.dedup import average_hash, sha256_bytes
from app.intelligence.face.engine import FaceEngine
from app.intelligence.face.similarity import DEDUP_THRESHOLD
from app.intelligence.face.vector_index import max_similarity
from app.intelligence.face.service import detect_and_embed_async


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
    faces_duplicate: int = 0
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

    # Face-dedup: load embeddings already indexed from this source so we skip
    # near-identical faces (same person/photo re-served at different URLs).
    seen_embeddings: list[list[float]] = []
    if base_host:
        rows = (
            await session.execute(
                select(Face.embedding).where(Face.source_url.ilike(f"%{base_host}%"))
            )
        ).scalars().all()
        seen_embeddings = [list(e) for e in rows if e]
    queue: deque[tuple[str, int]] = deque([(source.base_url, 0)])
    visited: set[str] = set()

    # Respect the source's max_pages but never exceed the global ceiling, so one
    # site configured with an absurd cap can't monopolise the worker.
    from app.core.config import get_settings
    page_budget = min(source.max_pages, get_settings().crawl_max_pages_ceiling)

    while queue and stats.pages_processed < page_budget:
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
            # Content unchanged, but we already have the HTML in hand — backfill
            # contacts with the improved extractor for pages the old one missed
            # (no phones AND no emails), so re-crawls enrich the existing index.
            if not existing.phones and not existing.emails:
                contacts = extract_contacts(html, region=region_for_host(base_host))
                if contacts["emails"] or contacts["phones"] or contacts["usernames"]:
                    existing.emails = contacts["emails"]
                    existing.phones = contacts["phones"]
                    existing.usernames = contacts["usernames"]
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
            meta = extract_page_meta(html)
            page_names = extract_person_names(html)
            _region = region_for_host(base_host)
            contacts = extract_contacts(html, region=_region)
            # Fold schema.org/OpenGraph structured data in — titles, orgs, locations,
            # social links, and extra emails/phones — for a fuller map of the target.
            structured = extract_structured(html)
            contacts, page_names, page.meta = enrich_from_structured(
                contacts, page_names, structured, region=_region
            )
            page.title = meta.get("title")
            page.description = meta.get("description")
            page.emails = contacts["emails"]
            page.phones = contacts["phones"]
            page.usernames = contacts["usernames"]
            session.add(page)
            await session.flush()

            _img_cap = min(_MAX_IMAGES_PER_PAGE, get_settings().crawl_max_images_per_page)
            contexts = extract_images_with_context(html, url)[:_img_cap]
            page_images = 0
            page_faces = 0
            for ctx in contexts:
                faces_added, is_dup = await _process_image(
                    session, source, page, ctx["url"], fetch=fetch, engine=engine, stats=stats,
                    safe=safe, context={"alt": ctx.get("alt"), "caption": ctx.get("caption"),
                                        "page_title": page.title, "names": page_names,
                                        "emails": contacts["emails"], "phones": contacts["phones"],
                                        "usernames": contacts["usernames"],
                                        "titles": page.meta.get("titles"), "orgs": page.meta.get("orgs"),
                                        "locations": page.meta.get("locations")},
                    seen_embeddings=seen_embeddings,
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

        # Commit per page so locks are released incrementally and a stalled
        # site never holds a long transaction (which blocks DDL/other work).
        try:
            await session.commit()
        except Exception:
            await session.rollback()

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
    context: dict | None = None,
    seen_embeddings: list | None = None,
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
            faces = await detect_and_embed_async(engine, resp.body)
        except Exception:
            faces = []
        from app.intelligence.face.crops import save_crop

        ctx = context or {}
        for f in faces:
            # Skip near-identical faces already indexed from this source.
            if seen_embeddings is not None:
                if max_similarity(f.embedding, seen_embeddings) >= DEDUP_THRESHOLD:
                    stats.faces_duplicate += 1
                    continue
                seen_embeddings.append(f.embedding)
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
                extra={
                    **f.extra,
                    "image_url": img_url,
                    "page_title": ctx.get("page_title"),
                    "caption": ctx.get("caption"),
                    "alt": ctx.get("alt"),
                    "names": ctx.get("names") or [],
                    "emails": ctx.get("emails") or [],
                    "phones": ctx.get("phones") or [],
                    "usernames": ctx.get("usernames") or [],
                    "titles": ctx.get("titles") or [],
                    "orgs": ctx.get("orgs") or [],
                    "locations": ctx.get("locations") or [],
                },
            )
            session.add(rec)
            await session.flush()
            save_crop(resp.body, f.bbox, str(rec.id))
            faces_added += 1
        img_row.faces_found = faces_added
        stats.faces_indexed += faces_added
    await session.flush()
    return faces_added, False
