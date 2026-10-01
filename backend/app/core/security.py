"""Security primitives: password hashing (argon2) and JWT (HS256).

Kept dependency-light and pure so it is trivially unit-testable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from jose import JWTError, jwt

from app.core.config import get_settings

_ALGORITHM = "HS256"
_ph = PasswordHasher()


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, tampered, or expired."""


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(sub: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "iat": now, "exp": now + expires_delta}
    return jwt.encode(payload, settings.app_secret_key, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.app_secret_key,
            algorithms=[_ALGORITHM],  # pin algorithm; rejects alg=none / RS swaps
        )
    except JWTError as exc:  # expired, bad signature, malformed
        raise TokenError(str(exc)) from exc
