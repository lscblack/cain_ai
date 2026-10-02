"""Standalone crawl worker process.

Run with ``python -m app.crawlers.worker`` beside the web application.
"""
from __future__ import annotations

import asyncio
import uuid

from app.api.sources import _run_crawl
from app.core.logging import get_logger
from app.core.redis import get_redis_client
from app.crawlers.queue import CRAWL_QUEUE
from app.crawlers.scheduler import scheduler_loop

logger = get_logger("kai.crawl-worker")


async def _consume() -> None:
    redis = get_redis_client()
    while True:
        _queue, source_id = await redis.blpop(CRAWL_QUEUE, timeout=5) or (None, None)
        if source_id is None:
            continue
        try:
            await _run_crawl(uuid.UUID(source_id))
        except Exception:
            logger.exception("crawl worker failed for source %s", source_id)


async def run() -> None:
    scheduler = asyncio.create_task(scheduler_loop())
    try:
        await _consume()
    finally:
        scheduler.cancel()
        await asyncio.gather(scheduler, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(run())