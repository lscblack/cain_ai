"""Username intelligence endpoint (public platform presence)."""
from __future__ import annotations

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
