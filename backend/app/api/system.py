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
        resources = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
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
        },
    }
