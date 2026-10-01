"""Chronological timeline of an investigation's observations."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.api.investigations import _get_investigation_or_404
from app.database.models.user import User
from app.database.repositories.graph_repos import (
    EntityRepository,
    EvidenceRepository,
    RelationshipRepository,
)
from app.database.session import get_session

router = APIRouter(prefix="/investigations", tags=["timeline"])


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


@router.get("/{inv_id}/timeline")
async def investigation_timeline(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _get_investigation_or_404(inv_id, session)
    entities = await EntityRepository(session).list_for_investigation(inv_id)
    evidence = await EvidenceRepository(session).list_for_investigation(inv_id)
    rels = await RelationshipRepository(session).list_for_investigation(inv_id)

    events: list[dict] = []
    for e in entities:
        events.append(
            {"kind": "entity_added", "at": _iso(e.created_at), "label": f"{e.type}: {e.value}", "source_url": None}
        )
    for ev in evidence:
        at = ev.first_seen or ev.collected_at
        events.append(
            {"kind": "evidence", "at": _iso(at), "label": f"{ev.type} observed", "source_url": ev.source_url}
        )
    for r in rels:
        events.append(
            {
                "kind": "relationship",
                "at": _iso(r.observed_at),
                "label": r.rel_type.replace("_", " "),
                "source_url": r.source_url,
            }
        )
    events = [e for e in events if e["at"]]
    events.sort(key=lambda x: x["at"])
    return {"events": events, "count": len(events)}
