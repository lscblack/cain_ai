"""Single-operator authentication.

First-run registration creates the one operator and then self-locks. There is
no open registration and no password reset flow in Phase 1 (solo, local).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.core.ratelimit import check_rate_limit
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password, verify_password
from app.database.models.user import User
from app.database.repositories.audit_repo import AuditRepository
from app.database.repositories.user_repo import UserRepository
from app.database.session import get_session
from app.schemas.auth import (
    LoginIn,
    OperatorOut,
    RegisterIn,
    RegistrationStatus,
    TokenOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# A fixed dummy argon2 hash so login against a non-existent user still performs
# a verify (reduces user-enumeration timing signal).
_DUMMY_HASH = hash_password("kai-dummy-password-for-timing")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/registration-status", response_model=RegistrationStatus)
async def registration_status(session: AsyncSession = Depends(get_session)) -> RegistrationStatus:
    count = await UserRepository(session).count()
    return RegistrationStatus(registration_open=count == 0)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    users = UserRepository(session)
    audit = AuditRepository(session)
    if await users.count() > 0:
        await audit.record("operator.register_denied", ip=_client_ip(request))
        await session.commit()  # persist audit before the error unwinds the request
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="registration_closed")

    user = await users.add(
        User(email=str(body.email).lower(), password_hash=hash_password(body.password))
    )
    await session.flush()
    await audit.record("operator.register", actor_id=user.id, ip=_client_ip(request))
    return TokenOut(access_token=create_access_token(str(user.id)))


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> TokenOut:
    ip = _client_ip(request) or "unknown"
    await check_rate_limit(redis, f"rl:login:{ip}", limit=10, window_seconds=300)
    users = UserRepository(session)
    audit = AuditRepository(session)
    user = await users.get_by_email(str(body.email).lower())

    # Always run a verify to flatten timing between existing/non-existing users.
    stored_hash = user.password_hash if user else _DUMMY_HASH
    ok = verify_password(body.password, stored_hash)

    if not user or not ok:
        await audit.record(
            "operator.login_failed",
            actor_id=user.id if user else None,
            detail={"email": str(body.email).lower()},
            ip=_client_ip(request),
        )
        await session.commit()  # persist audit before the error unwinds the request
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    await audit.record("operator.login", actor_id=user.id, ip=_client_ip(request))
    return TokenOut(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=OperatorOut)
async def me(operator: User = Depends(get_current_operator)) -> OperatorOut:
    return OperatorOut(id=operator.id, email=operator.email, created_at=operator.created_at)
