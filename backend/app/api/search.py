"""Universal search — detect the query type and search the local corpus.

Phase 3 searches what KAI already holds (entities + evidence across all
investigations). External enrichment providers are added in Phases 4-6 and
will plug in behind this same endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.api.investigations import _entity_out
from app.database.models.entity import Entity
from app.database.models.evidence import Evidence
from app.database.models.user import User
from app.database.session import get_session
from app.intelligence.detect import detect_query_type
from app.schemas.investigation import EvidenceOut
from app.schemas.search import SearchResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def universal_search(
    q: str = Query(min_length=1, max_length=2000),
    limit: int = Query(default=50, ge=1, le=200),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    detection = detect_query_type(q)
    needle = detection.normalized or q.strip()
    like = f"%{needle}%"

    ent_rows = (
        await session.execute(
            select(Entity)
            .where(or_(Entity.value.ilike(like), Entity.label.ilike(like)))
            .limit(limit)
        )
    ).scalars().all()

    evd_rows = (
        await session.execute(
            select(Evidence)
            .where(or_(Evidence.source_url.ilike(like), Evidence.hash.ilike(like)))
            .limit(limit)
        )
    ).scalars().all()

    return SearchResponse(
        query=q,
        detected_type=detection.type.value,
        normalized=needle,
        entity_matches=[_entity_out(e) for e in ent_rows],
        evidence_matches=[EvidenceOut(**e.model_dump()) for e in evd_rows],
    )
