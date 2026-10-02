"""Source Discovery Engine API.

Operators launch a discovery run (discover -> qualify -> score -> approve -> crawl)
and poll its live progress. Also exposes the self-learning term queue so searched
terms with little/no local data get auto-discovered next time.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.api.deps import get_current_operator
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.crawlers.queue import enqueue_discovery
from app.database.models.user import User
from app.discovery import learning
from app.discovery.engine import _run_key, mark_queued, new_run_id
from app.discovery.search import search_available

logger = get_logger("kai.api.discovery")
router = APIRouter(prefix="/discovery", tags=["discovery"])


class DiscoveryRunIn(BaseModel):
    country: str = Field(default="rwanda", max_length=80)
    categories: list[str] = Field(default_factory=lambda: ["people", "phone", "images"])
    targets: list[str] = Field(default_factory=lambda: ["phone", "username", "images"])
    min_score: int = Field(default=60, ge=0, le=100)
    max_domains: int = Field(default=200, ge=1, le=500)
    auto_crawl: bool = False


class DiscoveryRunStarted(BaseModel):
    id: str
    available: bool


@router.get("/status")
async def discovery_status(operator: User = Depends(get_current_operator)) -> dict:
    return {"available": search_available()}


@router.post("/run", response_model=DiscoveryRunStarted, status_code=status.HTTP_202_ACCEPTED)
async def start_discovery(
    body: DiscoveryRunIn,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> DiscoveryRunStarted:
    if not search_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discovery search unavailable: set SERPAPI_API_KEY.",
        )
    run_id = new_run_id()
    params = {
        "run_id": run_id,
        "country": body.country,
        "categories": body.categories,
        "targets": body.targets,
        "min_score": body.min_score,
        "max_domains": body.max_domains,
        "auto_crawl": body.auto_crawl,
    }
    # Run in the background worker (de-prioritised process) so a discovery run never
    # competes with interactive API traffic. The UI polls progress from Redis.
    await mark_queued(redis, run_id, params)
    await enqueue_discovery(redis, params)
    logger.info("discovery run %s queued by %s", run_id, operator.email)
    return DiscoveryRunStarted(id=run_id, available=True)


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    raw = await redis.get(_run_key(run_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Run not found or expired.")
    return json.loads(raw)


@router.get("/terms")
async def list_terms(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    return {"terms": await learning.list_terms(redis)}


@router.delete("/terms", status_code=status.HTTP_204_NO_CONTENT)
async def clear_terms(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> None:
    await learning.clear_terms(redis)
