"""Phone intelligence endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.api.investigations import _entity_out
from app.database.models.entity import Entity
from app.database.models.evidence import Evidence
from app.database.models.user import User
from app.database.session import get_session
from app.intelligence.phone.normalize import analyze_phone
from app.schemas.investigation import EvidenceOut
from app.schemas.phone import PhoneAnalysisOut, PhoneIntelligenceOut, PhoneQuery

router = APIRouter(prefix="/intelligence/phone", tags=["phone"])


@router.post("", response_model=PhoneIntelligenceOut)
async def phone_intelligence(
    body: PhoneQuery,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> PhoneIntelligenceOut:
    analysis = analyze_phone(body.number, body.region)

    # Search the local corpus against every known textual variant of the number.
    needles = set(analysis.variants) if analysis.parsed else set()
    needles.add(body.number.strip())
    conditions = [Entity.value.ilike(f"%{n}%") for n in needles if n]
    ent_matches: list[Entity] = []
    evd_matches: list[Evidence] = []
    if conditions:
        ent_matches = list(
            (await session.execute(select(Entity).where(or_(*conditions)).limit(100)))
            .scalars()
            .all()
        )
        evd_matches = list(
            (
                await session.execute(
                    select(Evidence)
                    .where(or_(*[Evidence.source_url.ilike(f"%{n}%") for n in needles if n]))
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )

    return PhoneIntelligenceOut(
        analysis=PhoneAnalysisOut(**analysis.to_dict()),
        local_entity_matches=[_entity_out(e) for e in ent_matches],
        local_evidence_matches=[EvidenceOut(**e.model_dump()) for e in evd_matches],
    )
