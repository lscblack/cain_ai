"""Standalone crawl worker process.

Run with ``python -m app.crawlers.worker`` beside the web application.
"""
from __future__ import annotations

import asyncio
import json
import uuid

from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from app.api.sources import _run_crawl
from app.core.logging import get_logger
from app.core.redis import get_redis_client
from app.crawlers.queue import CRAWL_QUEUE, DISCOVERY_QUEUE
from app.crawlers.scheduler import learning_loop, scheduler_loop

logger = get_logger("kai.crawl-worker")


async def _run_discovery_job(raw: str) -> None:
    from app.discovery.engine import run_discovery, run_term_discovery

    try:
        job = json.loads(raw)
    except Exception:
        logger.warning("discovery worker: bad job payload")
        return
    redis = get_redis_client()
    if job.get("kind") == "terms":
        # Self-learning run: discover sources for specific searched terms.
        await run_term_discovery(
            job["run_id"],
            redis=redis,
            terms=job.get("terms", []),
            min_score=job.get("min_score", 55),
            max_domains=job.get("max_domains", 60),
            auto_crawl=job.get("auto_crawl", True),
        )
        return
    await run_discovery(
        job["run_id"],
        redis=redis,
        countries=job.get("countries") or ([job["country"]] if job.get("country") else None),
        categories=job.get("categories", []),
        targets=job.get("targets", []),
        min_score=job.get("min_score", 60),
        max_domains=job.get("max_domains", 200),
        auto_crawl=job.get("auto_crawl", False),
    )


async def _consume_queue(queue: str, handler) -> None:
    """Drain a single Redis list, one job at a time, forever.

    Each queue gets its own consumer so a long crawl backlog can never starve
    operator-triggered discovery (and vice versa).
    """
    redis = get_redis_client()
    while True:
        try:
            popped = await redis.blpop(queue, timeout=5)
        except RedisTimeoutError:
            continue  # idle wait expired — expected
        except RedisConnectionError:
            logger.warning("worker: redis connection lost on %s, retrying", queue)
            await asyncio.sleep(1)
            continue
        if not popped:
            continue
        _q, value = popped
        try:
            await handler(value)
        except Exception:
            logger.exception("worker job failed (%s): %s", queue, value)


async def _handle_crawl(value: str) -> None:
    await _run_crawl(uuid.UUID(value))


async def run() -> None:
    tasks = [
        asyncio.create_task(_consume_queue(CRAWL_QUEUE, _handle_crawl)),
        asyncio.create_task(_consume_queue(DISCOVERY_QUEUE, _run_discovery_job)),
        asyncio.create_task(scheduler_loop()),
        asyncio.create_task(learning_loop()),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(run())