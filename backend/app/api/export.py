"""Evidence export (JSON / CSV) for an investigation."""
from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.api.investigations import _entity_out, _get_investigation_or_404
from app.database.models.user import User
from app.database.repositories.graph_repos import (
    EntityRepository,
    EvidenceRepository,
    RelationshipRepository,
)
from app.database.session import get_session
from app.schemas.investigation import EvidenceOut, RelationshipOut

router = APIRouter(prefix="/investigations", tags=["export"])


@router.get("/{inv_id}/export")
async def export_investigation(
    inv_id: uuid.UUID,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
):
    inv = await _get_investigation_or_404(inv_id, session)
    entities = [_entity_out(e).model_dump(mode="json") for e in await EntityRepository(session).list_for_investigation(inv_id)]
    evidence = [EvidenceOut(**e.model_dump()).model_dump(mode="json") for e in await EvidenceRepository(session).list_for_investigation(inv_id)]
    rels = [RelationshipOut(**r.model_dump()).model_dump(mode="json") for r in await RelationshipRepository(session).list_for_investigation(inv_id)]

    if format == "json":
        return JSONResponse(
            {
                "investigation": {"code": inv.code, "name": inv.name, "status": inv.status},
                "exported_by": operator.email,
                "entities": entities,
                "evidence": evidence,
                "relationships": rels,
            },
            headers={"Content-Disposition": f'attachment; filename="{inv.code}.json"'},
        )

    # CSV: one row per evidence item (the provenance-bearing records)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["type", "source_url", "collected_at", "first_seen", "last_seen", "confidence", "band", "hash"])
    for ev in evidence:
        writer.writerow(
            [ev["type"], ev["source_url"], ev["collected_at"], ev.get("first_seen"),
             ev.get("last_seen"), ev.get("confidence"), ev.get("band"), ev.get("hash")]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{inv.code}-evidence.csv"'},
    )
