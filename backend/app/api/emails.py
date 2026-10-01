"""Email intelligence endpoint."""
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
from app.intelligence.email.analyze import analyze_email, default_dns_resolver
from app.schemas.email import EmailAnalysisOut, EmailIntelligenceOut, EmailQuery
from app.schemas.investigation import EvidenceOut

router = APIRouter(prefix="/intelligence/email", tags=["email"])


@router.post("", response_model=EmailIntelligenceOut)
async def email_intelligence(
    body: EmailQuery,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> EmailIntelligenceOut:
    resolver = default_dns_resolver if body.check_dns else None
    analysis = analyze_email(body.email, dns_resolver=resolver)

    needle = (analysis.input or body.email).strip().lower()
    ent_matches = list(
        (await session.execute(select(Entity).where(Entity.value.ilike(f"%{needle}%")).limit(100)))
        .scalars()
        .all()
    )
    evd_matches = list(
        (
            await session.execute(
                select(Evidence)
                .where(or_(Evidence.source_url.ilike(f"%{needle}%")))
                .limit(100)
            )
        )
        .scalars()
        .all()
    )

    return EmailIntelligenceOut(
        analysis=EmailAnalysisOut(**analysis.to_dict()),
        local_entity_matches=[_entity_out(e) for e in ent_matches],
        local_evidence_matches=[EvidenceOut(**e.model_dump()) for e in evd_matches],
    )
