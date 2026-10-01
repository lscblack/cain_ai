"""Power Up — provider status panel + operator enable/disable toggles.

Reports each registered provider's type, enabled state, whether it is configured,
and a health check. Operator toggles persist in Redis. Never exposes secrets.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis.asyncio import Redis

from app.api.deps import get_current_operator
from app.core.redis import get_redis
from app.database.models.user import User
from app.providers.registry import registry

router = APIRouter(prefix="/powerup", tags=["powerup"])

_DISABLED_SET = "kai:providers:disabled"


class ToggleIn(BaseModel):
    enabled: bool


async def _disabled(redis: Redis) -> set[str]:
    try:
        return set(await redis.smembers(_DISABLED_SET))
    except Exception:
        return set()


@router.get("/providers")
async def list_providers(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    disabled = await _disabled(redis)
    out = []
    for provider in registry.all():
        health = await provider.health_check()
        base_enabled = bool(getattr(provider, "enabled", False))
        out.append(
            {
                "name": provider.name,
                "type": getattr(provider.type, "value", str(provider.type)),
                "enabled": base_enabled and provider.name not in disabled,
                "operator_disabled": provider.name in disabled,
                "configured": health.configured,
                "healthy": health.healthy,
                "detail": health.detail,
            }
        )
    out.sort(key=lambda p: (p["type"], p["name"]))
    return {"providers": out}


@router.post("/providers/{name}/toggle")
async def toggle_provider(
    name: str,
    body: ToggleIn,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    if registry.get(name) is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="provider_not_found")
    try:
        if body.enabled:
            await redis.srem(_DISABLED_SET, name)
        else:
            await redis.sadd(_DISABLED_SET, name)
    except Exception:
        pass
    return {"name": name, "enabled": body.enabled}
