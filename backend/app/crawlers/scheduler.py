"""Scheduled crawl producer for the standalone crawl worker.

Periodically triggers crawls for sources whose `schedule` interval has elapsed.
Sources default to `manual` and are never auto-crawled. Runs as a background
jobs are placed on Redis so crawling never runs in the web process.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.redis import get_redis_client
from app.crawlers.queue import enqueue_crawls
from app.database.models.source import Source
from app.database.session import async_session_maker

logger = get_logger("kai.scheduler")

_INTERVALS = {"hourly": 3600, "6h": 21600, "daily": 86400, "weekly": 604800}
_TICK_SECONDS = 300


def _due(source: Source, now: datetime) -> bool:
    if source.schedule not in _INTERVALS or source.status == "crawling":
        return False
    if not source.last_crawled_at:
        return True
    try:
        last = datetime.fromisoformat(source.last_crawled_at)
    except ValueError:
        return True
    return (now - last).total_seconds() >= _INTERVALS[source.schedule]


async def _tick() -> list[str]:
    """One scheduler pass; returns the ids of sources it triggered."""
    now = datetime.now(timezone.utc)
    triggered: list[str] = []
    async with async_session_maker() as session:
        sources = (await session.execute(select(Source))).scalars().all()
    due_ids = []
    for src in sources:
        if _due(src, now):
            logger.info("scheduler: triggering crawl for %s (%s)", src.domain, src.schedule)
            triggered.append(str(src.id))
            due_ids.append(src.id)
    await enqueue_crawls(get_redis_client(), due_ids)
    return triggered


async def scheduler_loop() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("scheduler tick failed")
        await asyncio.sleep(_TICK_SECONDS)


_LEARNING_TICK_SECONDS = 900  # every 15 min, discover sources for data-poor searched terms


async def learning_loop() -> None:
    """Periodically turn searched-but-data-poor terms into new crawled sources."""
    from app.discovery import learning

    while True:
        try:
            run_id = await learning.process_pending(get_redis_client())
            if run_id:
                logger.info("learning: launched discovery run %s", run_id)
        except Exception:
            logger.exception("learning tick failed")
        await asyncio.sleep(_LEARNING_TICK_SECONDS)


_DEDUPE_TICK_SECONDS = 3600  # hourly auto-remove of near-identical faces (no clicking)


async def dedupe_loop() -> None:
    """Automatically drop near-duplicate faces on a schedule so the index stays clean."""
    from app.intelligence.face.dedupe import run_dedupe

    # Delay the first pass so startup + any active crawl settles first.
    await asyncio.sleep(600)
    while True:
        try:
            async with async_session_maker() as session:
                result = await run_dedupe(session)
            if result.get("removed"):
                logger.info("dedupe: auto-removed %d duplicate face(s)", result["removed"])
        except Exception:
            logger.exception("dedupe tick failed")
        await asyncio.sleep(_DEDUPE_TICK_SECONDS)
