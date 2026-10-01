"""Shared API dependencies."""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_token
from app.database.models.user import User
from app.database.repositories.user_repo import UserRepository
from app.database.session import get_session

_bearer = HTTPBearer(auto_error=False)

_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="not_authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_operator(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds is None or not creds.credentials:
        raise _UNAUTH
    try:
        payload = decode_token(creds.credentials)
    except TokenError:
        raise _UNAUTH
    sub = payload.get("sub")
    if not sub:
        raise _UNAUTH
    try:
        user_id = uuid.UUID(str(sub))
    except ValueError:
        raise _UNAUTH
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise _UNAUTH
    return user
