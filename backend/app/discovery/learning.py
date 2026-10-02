"""Self-learning: remember searched terms with little/no local data so KAI can go
find data (and images) about them next time.

Every public/operator lookup records its term here. A background pass pops the terms
with the fewest local hits and runs a focused discovery for them. This gives KAI the
ability to learn from data it doesn't yet have.
"""
from __future__ import annotations

import json
import time

from redis.asyncio import Redis

from app.core.logging import get_logger
from app.discovery.engine import new_run_id, run_term_discovery
from app.discovery.search import search_available

logger = get_logger("kai.discovery.learning")

TERMS_KEY = "kai:discovery:terms"          # hash term -> json meta
PENDING_KEY = "kai:discovery:terms:pending"  # set of terms awaiting discovery
LOW_DATA_HITS = 3  # at or below this many local hits => term is "data-poor"
MAX_TERM_LEN = 120


async def record_term(redis: Redis, term: str, kind: str, *, local_hits: int) -> None:
    """Note a searched term. Queue it for discovery when local data is scarce."""
    term = (term or "").strip()
    if not term or len(term) > MAX_TERM_LEN:
        return
    now = time.time()
    try:
        raw = await redis.hget(TERMS_KEY, term)
        meta = json.loads(raw) if raw else {"kind": kind, "count": 0, "first_seen": now}
        meta["count"] = int(meta.get("count", 0)) + 1
        meta["kind"] = kind
        meta["last_seen"] = now
        meta["local_hits"] = local_hits
        await redis.hset(TERMS_KEY, term, json.dumps(meta))
        if local_hits <= LOW_DATA_HITS:
            await redis.sadd(PENDING_KEY, term)
        else:
            await redis.srem(PENDING_KEY, term)
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_term failed: %s", exc)


async def list_terms(redis: Redis) -> list[dict]:
    try:
        data = await redis.hgetall(TERMS_KEY)
        pending = set(await redis.smembers(PENDING_KEY))
    except Exception:
        return []
    out: list[dict] = []
    for term, raw in data.items():
        t = term.decode() if isinstance(term, bytes) else term
        try:
            meta = json.loads(raw)
        except Exception:
            meta = {}
        meta["term"] = t
        meta["pending"] = (term in pending) or (t in {p.decode() if isinstance(p, bytes) else p for p in pending})
        out.append(meta)
    out.sort(key=lambda m: m.get("last_seen", 0), reverse=True)
    return out


async def clear_terms(redis: Redis) -> None:
    try:
        await redis.delete(TERMS_KEY, PENDING_KEY)
    except Exception:
        pass


async def process_pending(redis: Redis, *, batch: int = 8) -> str | None:
    """Pop up to `batch` data-poor terms and launch one discovery run for them.

    Returns the run id, or None if there is nothing to do / search unavailable.
    """
    if not search_available():
        return None
    try:
        members = list(await redis.smembers(PENDING_KEY))
    except Exception:
        return None
    if not members:
        return None
    terms = [(m.decode() if isinstance(m, bytes) else m) for m in members][:batch]
    try:
        await redis.srem(PENDING_KEY, *members[:batch])
    except Exception:
        pass
    run_id = new_run_id()
    logger.info("learning discovery %s for %d term(s)", run_id, len(terms))
    await run_term_discovery(run_id, redis=redis, terms=terms)
    return run_id
