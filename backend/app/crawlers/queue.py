"""Redis-backed crawl job queue shared by the API and crawl worker."""
from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from redis.asyncio import Redis

CRAWL_QUEUE = "kai:crawl:queue"


async def enqueue_crawls(redis: Redis, source_ids: Iterable[UUID]) -> int:
    """Queue source IDs and return the number of jobs added."""
    ids = [str(source_id) for source_id in source_ids]
    if not ids:
        return 0
    return int(await redis.rpush(CRAWL_QUEUE, *ids))
