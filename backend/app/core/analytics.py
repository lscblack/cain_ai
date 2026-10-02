"""Lightweight public-usage analytics in Redis (privacy-friendly).

Counts public events and unique visitors (IP hashed with the app secret, never
stored raw). Fast (no DB writes on the hot path) and read back by operators.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.core.config import get_settings

_PREFIX = "kai:an"
_RECENT = f"{_PREFIX}:recent"


def hash_ip(ip: str) -> str:
    return hashlib.sha256(f"{ip}:{get_settings().app_secret_key}".encode()).hexdigest()[:16]


async def record_event(redis: Redis, event: str, ip: str, detail: str | None = None) -> None:
    try:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        ih = hash_ip(ip)
        pipe = redis.pipeline()
        pipe.incr(f"{_PREFIX}:total")
        pipe.incr(f"{_PREFIX}:event:{event}")
        pipe.incr(f"{_PREFIX}:day:{day}")
        pipe.sadd(f"{_PREFIX}:visitors", ih)
        pipe.sadd(f"{_PREFIX}:visitors:{day}", ih)
        pipe.expire(f"{_PREFIX}:visitors:{day}", 60 * 60 * 24 * 90)
        pipe.expire(f"{_PREFIX}:day:{day}", 60 * 60 * 24 * 90)
        pipe.lpush(_RECENT, json.dumps({"event": event, "ip": ih, "detail": detail, "at": time.time()}))
        pipe.ltrim(_RECENT, 0, 199)
        await pipe.execute()
    except Exception:
        pass  # analytics must never break a request


async def read_analytics(redis: Redis) -> dict:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    events = ["public_search", "public_compare", "public_lookup", "public_submit", "public_view"]
    try:
        total = int(await redis.get(f"{_PREFIX}:total") or 0)
        by_event = {e: int(await redis.get(f"{_PREFIX}:event:{e}") or 0) for e in events}
        unique = int(await redis.scard(f"{_PREFIX}:visitors") or 0)
        unique_today = int(await redis.scard(f"{_PREFIX}:visitors:{day}") or 0)
        today = int(await redis.get(f"{_PREFIX}:day:{day}") or 0)
        raw = await redis.lrange(_RECENT, 0, 29)
        recent = []
        for r in raw:
            try:
                recent.append(json.loads(r))
            except Exception:
                pass
        # last 7 days series
        series = []
        for i in range(6, -1, -1):
            from datetime import timedelta

            d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y%m%d")
            series.append({"day": d, "events": int(await redis.get(f"{_PREFIX}:day:{d}") or 0),
                           "visitors": int(await redis.scard(f"{_PREFIX}:visitors:{d}") or 0)})
        return {
            "total_events": total, "events_today": today,
            "unique_visitors": unique, "unique_visitors_today": unique_today,
            "by_event": by_event, "recent": recent, "series": series,
            "available": True,
        }
    except Exception:
        return {"available": False}
