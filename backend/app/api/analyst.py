"""AI analyst endpoint: grounded summary of an investigation's evidence."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.analyst import build_context, build_messages
from app.ai.router import AIProvider, get_ai_provider
from app.api.deps import get_current_operator
from app.api.investigations import _entity_out, _get_investigation_or_404
from app.database.models.user import User
from app.database.repositories.graph_repos import (
    EntityRepository,
    EvidenceRepository as EvidRepo,
    RelationshipRepository,
)
from app.database.session import get_session
from app.schemas.investigation import EvidenceOut, RelationshipOut

router = APIRouter(prefix="/investigations", tags=["analyst"])


def get_analyst_provider() -> AIProvider | None:
    return get_ai_provider()


@router.post("/{inv_id}/analyze")
async def analyze_investigation(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    provider: AIProvider | None = Depends(get_analyst_provider),
) -> dict:
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ai_unavailable"
        )
    inv = await _get_investigation_or_404(inv_id, session)
    entities = [_entity_out(e).model_dump(mode="json") for e in await EntityRepository(session).list_for_investigation(inv_id)]
    evidence = [EvidenceOut(**e.model_dump()).model_dump(mode="json") for e in await EvidRepo(session).list_for_investigation(inv_id)]
    rels = [RelationshipOut(**r.model_dump()).model_dump(mode="json") for r in await RelationshipRepository(session).list_for_investigation(inv_id)]

    context = build_context(
        {"code": inv.code, "name": inv.name, "description": inv.description},
        entities,
        evidence,
        rels,
    )
    try:
        summary = await provider.chat(build_messages(context))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ai_error: {exc}")

    return {
        "investigation_id": str(inv_id),
        "model": provider.name,
        "summary": summary,
        "evidence_counts": {
            "entities": len(entities),
            "evidence": len(evidence),
            "relationships": len(rels),
        },
        "note": "AI-generated analysis grounded in the listed evidence. Verify every claim against its source.",
    }
