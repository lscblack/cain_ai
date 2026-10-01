"""Async Redis client provider."""
from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    """Process-wide singleton Redis client (lazy)."""
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def get_redis() -> Redis:
    """FastAPI dependency. Overridden with fakeredis in tests."""
    return get_redis_client()
