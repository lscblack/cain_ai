"""System / admin observability panel (spec §39)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.core.redis import get_redis
from app.database.models.entity import Entity
from app.database.models.evidence import Evidence
from app.database.models.face import Face
from app.database.models.investigation import Investigation
from app.database.models.source import Image, Page, Source
from app.database.models.user import User
from app.database.session import get_session
from app.intelligence.face.service import get_face_engine

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/stats")
async def system_stats(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    # resource usage
    resources: dict = {}
    try:
        import psutil

        vm = psutil.virtual_memory()
        process = psutil.Process()
        process_cpu_percent = process.cpu_percent(interval=0.1)
        resources = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "cpu_cores": psutil.cpu_count(logical=True) or 1,
            "cpu_process_percent": process_cpu_percent,
            "cpu_process_cores": round(process_cpu_percent / 100, 2),
            "cpu_process_threads": process.num_threads(),
            "ram_percent": vm.percent,
            "ram_used_mb": round(vm.used / 1024 / 1024),
            "ram_total_mb": round(vm.total / 1024 / 1024),
        }
    except Exception:
        resources = {"detail": "psutil_unavailable"}

    async def _count(model) -> int:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())

    # dependency health
    db_ok = redis_ok = False
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    try:
        redis_ok = bool(await redis.ping())
    except Exception:
        redis_ok = False

    async def _count_entity(type_: str) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).select_from(Entity).where(Entity.type == type_)
                )
            ).scalar_one()
        )

    engine = get_face_engine()
    return {
        "resources": resources,
        "services": {"postgres": db_ok, "redis": redis_ok, "face_engine": engine.available()},
        "counts": {
            "investigations": await _count(Investigation),
            "entities": await _count(Entity),
            "evidence": await _count(Evidence),
            "faces": await _count(Face),
            "sources": await _count(Source),
            "pages": await _count(Page),
            "images": await _count(Image),
            "phones": await _count_entity("phone"),
            "emails": await _count_entity("email"),
            "usernames": await _count_entity("username"),
            "domains": await _count_entity("domain"),
        },
    }


@router.get("/power")
async def power_state(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    from app.core import power

    return await power.power_status(redis)


@router.post("/power/stop")
async def power_stop(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.core import power
    from app.database.models.audit import AuditLog

    result = await power.stop_kai(redis)
    session.add(AuditLog(actor_id=operator.id, action="power.stop", detail=result))
    await session.flush()
    return result


@router.post("/power/start")
async def power_start(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.core import power
    from app.database.models.audit import AuditLog

    result = await power.start_kai(redis)
    session.add(AuditLog(actor_id=operator.id, action="power.start", detail=result))
    await session.flush()
    return result


@router.get("/analytics")
async def usage_analytics(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Public-usage analytics: visitors and feature usage (hashed IPs only)."""
    from app.core.analytics import read_analytics

    return await read_analytics(redis)
