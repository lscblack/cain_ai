"""Minimal Redis-backed fixed-window rate limiter."""
from __future__ import annotations

from fastapi import HTTPException, status
from redis.asyncio import Redis


async def check_rate_limit(redis: Redis, key: str, *, limit: int, window_seconds: int) -> None:
    """Increment the counter for `key`; raise 429 if it exceeds `limit` in the window."""
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
    except Exception:
        # Fail open: never block legitimate use because the limiter backend is down.
        return
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limited",
            headers={"Retry-After": str(window_seconds)},
        )
