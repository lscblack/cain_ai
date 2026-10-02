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
