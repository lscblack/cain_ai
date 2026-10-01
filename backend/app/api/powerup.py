"""Power Up — provider status panel.

Reports each registered provider's type, enabled state, whether it is configured,
and a health check result. Never exposes secret values.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_operator
from app.database.models.user import User
from app.providers.registry import registry

router = APIRouter(prefix="/powerup", tags=["powerup"])


@router.get("/providers")
async def list_providers(operator: User = Depends(get_current_operator)) -> dict:
    out = []
    for provider in registry.all():
        health = await provider.health_check()
        out.append(
            {
                "name": provider.name,
                "type": getattr(provider.type, "value", str(provider.type)),
                "enabled": bool(getattr(provider, "enabled", False)),
                "configured": health.configured,
                "healthy": health.healthy,
                "detail": health.detail,
            }
        )
    out.sort(key=lambda p: (p["type"], p["name"]))
    return {"providers": out}
