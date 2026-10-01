"""Crawl source management + crawl triggering (local index)."""
from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.core.logging import get_logger
from app.crawlers.http import RobotsGate, httpx_fetch
from app.crawlers.runner import crawl_source
from app.database.models.face import Face
from app.database.models.source import Image, Page, Source
from app.database.models.user import User
from app.database.repositories.audit_repo import AuditRepository
from app.database.session import async_session_maker, get_session
from app.intelligence.face.service import get_face_engine
from app.schemas.source import SourceCreate, SourceOut, SourceStats

router = APIRouter(prefix="/sources", tags=["sources"])
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


@router.delete("/{sid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    sid: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> None:
    src = await _get_or_404(sid, session)
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


@router.post("/{sid}/crawl", status_code=status.HTTP_202_ACCEPTED)
async def trigger_crawl(
    sid: uuid.UUID,
    background: BackgroundTasks,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    src = await _get_or_404(sid, session)
    if src.status == "crawling":
        return {"status": "already_crawling", "source_id": str(sid)}
    await AuditRepository(session).record("source.crawl", actor_id=operator.id, detail={"domain": src.domain})
    background.add_task(_run_crawl, sid)
    return {"status": "crawl_started", "source_id": str(sid)}
