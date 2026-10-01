"""Geographic view of an investigation's located entities."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import get_current_operator
from app.api.investigations import _get_investigation_or_404
from app.core.config import get_settings
from app.database.models.user import User
from app.database.repositories.graph_repos import EntityRepository
from app.database.session import get_session
from app.intelligence.geo import extract_coords
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/investigations", tags=["maps"])


@router.get("/{inv_id}/map")
async def investigation_map(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _get_investigation_or_404(inv_id, session)
    entities = await EntityRepository(session).list_for_investigation(inv_id)
    points = []
    for e in entities:
        coords = extract_coords(e.value, e.meta)
        if coords is None:
            continue
        points.append(
            {
                "entity_id": str(e.id),
                "type": e.type,
                "label": e.label or e.value,
                "lat": coords[0],
                "lon": coords[1],
            }
        )
    return {"points": points, "count": len(points)}


@router.get("/map/config", tags=["maps"])
async def map_config(operator: User = Depends(get_current_operator)) -> dict:
    s = get_settings()
    # Only report whether tile providers are configured — never the token itself
    # unless it is a client-usable public token the operator chose to expose.
    return {
        "tomtom_configured": bool(s.tomtom_api_key),
        "cesium_configured": bool(s.cesium_ion_token),
    }
