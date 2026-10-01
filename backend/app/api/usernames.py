"""Username intelligence endpoint (public platform presence)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.api.investigations import _entity_out
from app.database.models.entity import Entity
from app.database.models.user import User
from app.database.session import get_session
from app.intelligence.username.check import Fetcher, check_username, is_valid_username
from app.intelligence.username.http import httpx_fetch
from app.schemas.investigation import EntityOut

router = APIRouter(prefix="/intelligence/username", tags=["username"])


def get_username_fetcher() -> Fetcher:
    """The HTTP fetcher used for presence checks. Overridden in tests."""
    return httpx_fetch


def get_avatar_fetcher():
    """unavatar fetcher (bytes|None). Overridden in tests."""
    from app.providers.unavatar import fetch_avatar

    return fetch_avatar


class UsernameQuery(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    platforms: list[str] | None = None


class UsernameHitOut(BaseModel):
    platform: str
    name: str
    username: str
    url: str
    status: str
    http_status: int | None
    checked_at: str


class UsernameIntelligenceOut(BaseModel):
    username: str
    results: list[UsernameHitOut]
    found_count: int
    local_entity_matches: list[EntityOut]
    note: str = (
        "A reachable public profile at a handle is an observation. It does not confirm the "
        "same person controls accounts across platforms."
    )


@router.post("", response_model=UsernameIntelligenceOut)
async def username_intelligence(
    body: UsernameQuery,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    fetcher: Fetcher = Depends(get_username_fetcher),
) -> UsernameIntelligenceOut:
    if not is_valid_username(body.username):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_username")

    hits = await check_username(body.username, fetcher, platform_keys=body.platforms)
    results = [UsernameHitOut(**h.to_dict()) for h in hits]

    ent_matches = list(
        (
            await session.execute(
                select(Entity).where(Entity.value.ilike(f"%{body.username}%")).limit(100)
            )
        )
        .scalars()
        .all()
    )

    return UsernameIntelligenceOut(
        username=body.username,
        results=results,
        found_count=sum(1 for r in results if r.status == "found"),
        local_entity_matches=[_entity_out(e) for e in ent_matches],
    )


class AvatarIndexIn(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    platforms: list[str] | None = None
    investigation_id: uuid.UUID | None = None


@router.post("/index-avatars")
async def index_avatars(
    body: AvatarIndexIn,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    avatar_fetch=Depends(get_avatar_fetcher),
):
    """Resolve avatars for a username across platforms (via unavatar) and index any
    detected faces into KAI's face index (source_url = the platform profile)."""
    import hashlib

    from sqlalchemy import select as _select

    from app.database.models.face import Face
    from app.intelligence.face.crops import save_crop
    from app.intelligence.face.service import detect_and_embed_async, get_face_engine
    from app.intelligence.username.platforms import PLATFORMS_BY_KEY
    from app.providers.unavatar import PROVIDER_MAP

    if not is_valid_username(body.username):
        raise HTTPException(status_code=422, detail="invalid_username")
    engine = get_face_engine()
    if not engine.available():
        raise HTTPException(status_code=503, detail="face_engine_unavailable")

    keys = body.platforms or list(PROVIDER_MAP.keys())
    results = []
    indexed = 0
    for key in keys:
        provider = PROVIDER_MAP.get(key, key)
        profile_url = PLATFORMS_BY_KEY[key].url_for(body.username) if key in PLATFORMS_BY_KEY else None
        data = await avatar_fetch(body.username, provider)
        if not data:
            results.append({"platform": key, "avatar": False, "faces": 0})
            continue
        image_hash = hashlib.sha256(data).hexdigest()
        dup = (await session.execute(_select(Face).where(Face.image_hash == image_hash))).scalar_one_or_none()
        if dup is not None:
            results.append({"platform": key, "avatar": True, "faces": 0, "duplicate": True})
            continue
        try:
            faces = await detect_and_embed_async(engine, data)
        except Exception as exc:  # noqa: BLE001
            from app.core.logging import get_logger
            get_logger("kai.avatars").warning("avatar detect failed for %s: %r", key, exc)
            faces = []
        n = 0
        for f in faces:
            rec = Face(
                investigation_id=body.investigation_id,
                source_url=profile_url or f"unavatar:{provider}/{body.username}",
                image_hash=image_hash,
                bbox=f.bbox, det_score=f.det_score, quality=f.quality,
                model=engine.model_name, model_version=engine.model_version,
                embedding_dim=len(f.embedding), embedding=f.embedding, extra={**f.extra, "platform": key},
            )
            session.add(rec)
            await session.flush()
            save_crop(data, f.bbox, str(rec.id))
            n += 1
            indexed += 1
        results.append({"platform": key, "avatar": True, "faces": n})
    await session.flush()
    return {
        "username": body.username,
        "faces_indexed": indexed,
        "results": results,
        "note": "Avatars resolved via unavatar.io and indexed as observed faces. An avatar on a handle is an observation, not a confirmed identity.",
    }
