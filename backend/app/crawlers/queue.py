"""Redis-backed job queues shared by the API and the background worker."""
from __future__ import annotations

import json
from collections.abc import Iterable
from uuid import UUID

from redis.asyncio import Redis

CRAWL_QUEUE = "kai:crawl:queue"
# User-triggered case crawls jump ahead of the background self-learning backlog.
CRAWL_PRIORITY_QUEUE = "kai:crawl:queue:priority"
DISCOVERY_QUEUE = "kai:discovery:queue"


async def enqueue_crawls(redis: Redis, source_ids: Iterable[UUID], *, priority: bool = False) -> int:
    """Queue source IDs and return the number of jobs added.

    priority=True routes to the fast lane (drained before the background backlog)
    so an operator's active investigation crawls right away.
    """
    ids = [str(source_id) for source_id in source_ids]
    if not ids:
        return 0
    queue = CRAWL_PRIORITY_QUEUE if priority else CRAWL_QUEUE
    return int(await redis.rpush(queue, *ids))


async def enqueue_discovery(redis: Redis, job: dict) -> int:
    """Queue a discovery run (JSON job) for the background worker."""
    return int(await redis.rpush(DISCOVERY_QUEUE, json.dumps(job)))
