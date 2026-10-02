"""Standalone crawl worker process.

Run with ``python -m app.crawlers.worker`` beside the web application.
"""
from __future__ import annotations

import asyncio
import uuid

from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from app.api.sources import _run_crawl
from app.core.logging import get_logger
from app.core.redis import get_redis_client
from app.crawlers.queue import CRAWL_QUEUE
from app.crawlers.scheduler import learning_loop, scheduler_loop

logger = get_logger("kai.crawl-worker")


async def _consume() -> None:
    redis = get_redis_client()
    while True:
        try:
            popped = await redis.blpop(CRAWL_QUEUE, timeout=5)
        except RedisTimeoutError:
            # Idle wait expired with no job queued — expected, keep polling.
            continue
        except RedisConnectionError:
            logger.warning("crawl worker: redis connection lost, retrying")
            await asyncio.sleep(1)
            continue
        _queue, source_id = popped or (None, None)
        if source_id is None:
            continue
        try:
            await _run_crawl(uuid.UUID(source_id))
        except Exception:
            logger.exception("crawl worker failed for source %s", source_id)


async def run() -> None:
    scheduler = asyncio.create_task(scheduler_loop())
    learning = asyncio.create_task(learning_loop())
    try:
        await _consume()
    finally:
        scheduler.cancel()
        learning.cancel()
        await asyncio.gather(scheduler, learning, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(run())