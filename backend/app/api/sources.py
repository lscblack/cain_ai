"""Crawl source management + crawl triggering (local index)."""
from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.core.ratelimit import check_rate_limit
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.core.logging import get_logger
from app.crawlers.http import RobotsGate, httpx_fetch
from app.crawlers.queue import enqueue_crawls
from app.crawlers.runner import crawl_source
from app.database.models.face import Face
from app.database.models.source import Image, Page, Source
from app.database.models.user import User
from app.database.repositories.audit_repo import AuditRepository
from app.core.redis import get_redis
from app.database.session import async_session_maker, get_session
from app.intelligence.face.service import get_face_engine
from app.schemas.source import (
    BulkSourceIn,
    BulkSourceResult,
    BulkUpdateIn,
    SourceCreate,
    SourceOut,
    SourceStats,
    SourceUpdate,
)

router = APIRouter(prefix="/sources", tags=["sources"])


class PublicSubmitIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=3, max_length=500)


@router.post("/public-submit", status_code=status.HTTP_201_CREATED)
async def public_submit_source(
    body: PublicSubmitIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Public, unauthenticated: anyone can suggest a website to crawl.
    Deduped by domain; rate-limited per IP. Added as manual (operator reviews/crawls)."""
    ip = request.client.host if request.client else "unknown"
    await check_rate_limit(redis, f"rl:pubsrc:{ip}", limit=10, window_seconds=3600)

    try:
        payload = SourceCreate(name=body.name, base_url=body.url)  # validates + SSRF + normalizes
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"invalid_url: {str(exc)[:160]}")

    domain = urlsplit(payload.base_url).hostname or ""
    existing = (
        await session.execute(select(Source.id).where(Source.domain == domain))
    ).scalar_one_or_none()
    if existing is not None:
        return {"status": "exists", "domain": domain}

    src = Source(
        name=payload.name, base_url=payload.base_url, domain=domain,
        allowed_paths=[], excluded_paths=[], max_depth=1, max_pages=50,
        schedule="manual", category="public-submission", priority="medium",
    )
    session.add(src)
    await session.flush()
    await AuditRepository(session).record("source.public_submit", detail={"domain": domain, "ip": ip})
    return {"status": "created", "domain": domain}
logger = get_logger("kai.sources")


async def _get_or_404(sid: uuid.UUID, session: AsyncSession) -> Source:
    src = (await session.execute(select(Source).where(Source.id == sid))).scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=404, detail="source_not_found")
    return src


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceCreate,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> SourceOut:
    domain = urlsplit(body.base_url).hostname or ""
    src = Source(
        name=body.name,
        base_url=body.base_url,
        domain=domain,
        allowed_paths=body.allowed_paths,
        excluded_paths=body.excluded_paths,
        max_depth=body.max_depth,
        max_pages=body.max_pages,
        schedule=body.schedule,
    )
    session.add(src)
    await session.flush()
    await AuditRepository(session).record("source.create", actor_id=operator.id, detail={"domain": domain})
    return SourceOut(**src.model_dump())


@router.post("/bulk", response_model=BulkSourceResult, status_code=status.HTTP_201_CREATED)
async def bulk_create_sources(
    body: BulkSourceIn,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> BulkSourceResult:
    """Add many sources at once from a list or pasted CSV / lines.

    CSV columns (header optional): name, base_url[, max_depth, max_pages, schedule].
    A bare domain is accepted (https:// is assumed)."""
    import csv as _csv
    import io

    raw_items: list[dict] = []
    if body.items:
        raw_items = [i.model_dump() for i in body.items]
    elif body.csv:
        reader = _csv.reader(io.StringIO(body.csv.strip()))
        for row in reader:
            cells = [c.strip() for c in row if c is not None]
            if not cells or not any(cells):
                continue
            if cells[0].lower() == "name":  # header
                continue
            name = cells[0]
            base_url = cells[1] if len(cells) > 1 and cells[1] else name
            raw_items.append(
                {
                    "name": name,
                    "base_url": base_url,
                    "max_depth": int(cells[2]) if len(cells) > 2 and cells[2] else body.default_max_depth,
                    "max_pages": int(cells[3]) if len(cells) > 3 and cells[3] else body.default_max_pages,
                    "schedule": cells[4] if len(cells) > 4 and cells[4] else body.default_schedule,
                }
            )

    created: list[SourceOut] = []
    errors: list[dict] = []
    for idx, item in enumerate(raw_items):
        try:
            payload = SourceCreate(**item)  # validates + normalizes URL
        except Exception as exc:  # noqa: BLE001
            errors.append({"row": idx + 1, "input": item, "error": str(exc)[:200]})
            continue
        domain = urlsplit(payload.base_url).hostname or ""
        src = Source(
            name=payload.name, base_url=payload.base_url, domain=domain,
            allowed_paths=payload.allowed_paths, excluded_paths=payload.excluded_paths,
            max_depth=payload.max_depth, max_pages=payload.max_pages, schedule=payload.schedule,
        )
        session.add(src)
        await session.flush()
        created.append(SourceOut(**src.model_dump()))
    await AuditRepository(session).record(
        "source.bulk_create", actor_id=operator.id, detail={"created": len(created), "errors": len(errors)}
    )
    return BulkSourceResult(created=created, errors=errors)


@router.get("", response_model=list[SourceOut])
async def list_sources(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[SourceOut]:
    rows = (await session.execute(select(Source).order_by(Source.created_at.desc()))).scalars().all()
    return [SourceOut(**s.model_dump()) for s in rows]


@router.get("/{sid}/stats", response_model=SourceStats)
async def source_stats(
    sid: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> SourceStats:
    src = await _get_or_404(sid, session)
    pages = (await session.execute(select(func.count()).select_from(Page).where(Page.source_id == sid))).scalar_one()
    images = (await session.execute(select(func.count()).select_from(Image).where(Image.source_id == sid))).scalar_one()
    # faces linked by image_hash of this source's images
    faces = (
        await session.execute(
            select(func.count())
            .select_from(Face)
            .where(Face.image_hash.in_(select(Image.image_hash).where(Image.source_id == sid)))
        )
    ).scalar_one()
    return SourceStats(
        source_id=sid, pages=pages, images=images, faces=faces,
        status=src.status, last_crawled_at=src.last_crawled_at,
    )


@router.patch("/{sid}", response_model=SourceOut)
async def update_source(
    sid: uuid.UUID,
    body: SourceUpdate,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> SourceOut:
    src = await _get_or_404(sid, session)
    data = body.model_dump(exclude_none=True)
    if "base_url" in data:
        src.domain = urlsplit(data["base_url"]).hostname or src.domain
    for key, val in data.items():
        setattr(src, key, val)
    session.add(src)
    await session.flush()
    await session.refresh(src)
    return SourceOut(**src.model_dump())


@router.post("/bulk-update")
async def bulk_update_sources(
    body: BulkUpdateIn,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Apply max_depth / max_pages / schedule / priority to all sources at once
    (optionally filtered by category or priority)."""
    from sqlalchemy import update as sa_update

    fields = {
        k: v
        for k, v in {
            "max_depth": body.max_depth,
            "max_pages": body.max_pages,
            "schedule": body.schedule,
            "priority": body.priority,
        }.items()
        if v is not None
    }
    if not fields:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    stmt = sa_update(Source).values(**fields)
    if body.filter_category:
        stmt = stmt.where(Source.category == body.filter_category)
    if body.filter_priority:
        stmt = stmt.where(Source.priority == body.filter_priority)
    result = await session.execute(stmt)
    await session.flush()
    await AuditRepository(session).record(
        "source.bulk_update", actor_id=operator.id, detail={"fields": list(fields), "rows": result.rowcount}
    )
    return {"updated": result.rowcount or 0, "fields": fields}


@router.post("/seed-defaults")
async def seed_defaults(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.core.seed import seed_default_sources

    return await seed_default_sources(session, only_if_empty=False)


@router.delete("/{sid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    sid: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> None:
    from sqlalchemy import delete as sa_delete

    src = await _get_or_404(sid, session)
    # cascade: pages + images reference this source
    await session.execute(sa_delete(Image).where(Image.source_id == sid))
    await session.execute(sa_delete(Page).where(Page.source_id == sid))
    await session.delete(src)
    await session.flush()


async def _run_crawl(source_id: uuid.UUID) -> None:
    """Background crawl with its own DB session."""
    engine = get_face_engine()
    robots = RobotsGate()
    async with async_session_maker() as session:
        src = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
        if src is None:
            return
        src.status = "crawling"
        src.last_error = None
        session.add(src)
        await session.commit()
        try:
            stats = await crawl_source(
                session, src, fetch=httpx_fetch, engine=engine, robots=robots.allowed
            )
            logger.info("crawl %s done: %s", src.domain, stats.to_dict())
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            src.status = "error"
            src.last_error = str(exc)[:500]
            session.add(src)
            await session.commit()
            logger.exception("crawl failed for %s", src.domain)


async def _run_crawl_all(source_ids: list[uuid.UUID], concurrency: int = 2) -> None:
    """Crawl many sources with bounded concurrency (one DB session per crawl)."""
    import asyncio

    sem = asyncio.Semaphore(concurrency)

    async def _one(sid: uuid.UUID) -> None:
        async with sem:
            await _run_crawl(sid)

    await asyncio.gather(*[_one(sid) for sid in source_ids], return_exceptions=True)


@router.get("/queue")
async def queue_status(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    from app.crawlers.queue import CRAWL_QUEUE

    try:
        depth = int(await redis.llen(CRAWL_QUEUE))
    except Exception:
        depth = 0
    return {"queued": depth}


@router.post("/queue/clear")
async def queue_clear(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Empty the crawl queue and reset any 'crawling' sources to idle."""
    from sqlalchemy import update as _update

    from app.crawlers.queue import CRAWL_QUEUE

    removed = 0
    try:
        removed = int(await redis.llen(CRAWL_QUEUE))
        await redis.delete(CRAWL_QUEUE)
    except Exception:
        pass
    await session.execute(_update(Source).where(Source.status == "crawling").values(status="idle"))
    await session.flush()
    await AuditRepository(session).record("source.queue_clear", actor_id=operator.id, detail={"removed": removed})
    return {"cleared": removed}


@router.post("/crawl-all", status_code=status.HTTP_202_ACCEPTED)
async def crawl_all(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    category: str | None = None,
    priority: str | None = None,
) -> dict:
    """Start crawling all sources (optionally filtered), with bounded concurrency."""
    stmt = select(Source.id).where(Source.status != "crawling")
    if category:
        stmt = stmt.where(Source.category == category)
    if priority:
        stmt = stmt.where(Source.priority == priority)
    ids = list((await session.execute(stmt)).scalars().all())
    if not ids:
        return {"status": "nothing_to_crawl", "scheduled": 0}
    await AuditRepository(session).record(
        "source.crawl_all", actor_id=operator.id, detail={"count": len(ids)}
    )
    await enqueue_crawls(redis, ids)
    return {"status": "crawl_started", "scheduled": len(ids)}


@router.post("/{sid}/crawl", status_code=status.HTTP_202_ACCEPTED)
async def trigger_crawl(
    sid: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    src = await _get_or_404(sid, session)
    if src.status == "crawling":
        return {"status": "already_crawling", "source_id": str(sid)}
    await AuditRepository(session).record("source.crawl", actor_id=operator.id, detail={"domain": src.domain})
    await enqueue_crawls(redis, [sid])
    return {"status": "crawl_started", "source_id": str(sid)}
