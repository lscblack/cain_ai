"""Redis-backed job queues shared by the API and the background worker."""
from __future__ import annotations

import json
from collections.abc import Iterable
from uuid import UUID

from redis.asyncio import Redis

CRAWL_QUEUE = "kai:crawl:queue"
DISCOVERY_QUEUE = "kai:discovery:queue"


async def enqueue_crawls(redis: Redis, source_ids: Iterable[UUID]) -> int:
    """Queue source IDs and return the number of jobs added."""
    ids = [str(source_id) for source_id in source_ids]
    if not ids:
        return 0
    return int(await redis.rpush(CRAWL_QUEUE, *ids))


async def enqueue_discovery(redis: Redis, job: dict) -> int:
    """Queue a discovery run (JSON job) for the background worker."""
    return int(await redis.rpush(DISCOVERY_QUEUE, json.dumps(job)))
