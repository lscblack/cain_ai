"""Public (no-auth) lookups over the crawled corpus: phone / email / username.

Returns the pages where a contact was observed plus any faces indexed from those
pages — so the public can pivot from a handle/number/email to images + source.
Rate-limited per IP. Observations only, never identity claims.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import check_rate_limit
from app.core.redis import get_redis
from app.database.models.face import Face
from app.database.models.source import Page
from app.database.session import get_session
from app.intelligence.detect import QueryType, detect_query_type
from app.intelligence.face.crops import has_crop

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/lookup")
async def public_lookup(
    request: Request,
    q: str = Query(min_length=2, max_length=200),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    ip = request.client.host if request.client else "unknown"
    await check_rate_limit(redis, f"rl:publookup:{ip}", limit=40, window_seconds=600)

    det = detect_query_type(q)
    needle = det.normalized or q.strip()

    # Which page contact column(s) to match, based on detected type.
    conds = []
    if det.type == QueryType.EMAIL:
        conds.append(Page.emails.contains([needle]))
    elif det.type == QueryType.PHONE:
        conds.append(Page.phones.contains([needle]))
    elif det.type == QueryType.USERNAME:
        conds.append(Page.usernames.contains([needle.lstrip("@")]))
    else:
        # unknown: try all three
        conds = [Page.emails.contains([needle]), Page.phones.contains([needle]),
                 Page.usernames.contains([needle.lstrip("@")])]

    pages = (await session.execute(select(Page).where(or_(*conds)).limit(50))).scalars().all()

    results = []
    for p in pages:
        faces = (
            await session.execute(select(Face).where(Face.source_url == p.url).limit(8))
        ).scalars().all()
        results.append(
            {
                "page_url": p.url,
                "page_title": p.title,
                "domain": urlsplit(p.url).hostname,
                "emails": p.emails,
                "phones": p.phones,
                "usernames": p.usernames,
                "faces": [
                    {
                        "face_id": str(fa.id),
                        "crop_url": f"/intelligence/face/public/crop/{fa.id}",
                        # Full direct links — the exact page and image URL the face was
                        # found at, never reduced to the root domain.
                        "source_url": fa.source_url,
                        "image_url": (fa.extra or {}).get("image_url"),
                    }
                    for fa in faces
                    if has_crop(str(fa.id))
                ],
            }
        )
    # Self-learning: if we have little/no data on this term, queue it for discovery
    # so next time it's searched KAI has crawled data + images about it.
    try:
        from app.discovery import learning

        await learning.record_term(redis, needle, det.type.value, local_hits=len(results))
    except Exception:
        pass

    return {
        "query": q,
        "detected_type": det.type.value,
        "normalized": needle,
        "count": len(results),
        "results": results,
        "note": "Pages where this identifier was observed. Co-location is an observation, not proof of ownership.",
    }
