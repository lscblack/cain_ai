"""Auth request/response schemas.

The operator identifier is called ``email`` for familiarity, but because KAI
is solo-local it accepts either a real email address or a simple local
username (e.g. ``operator@local`` or ``admin``). It is never sent anywhere.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._%+\-]*(@[a-z0-9._\-]+)?$")


def _normalize_identifier(v: str) -> str:
    v = v.strip().lower()
    if not (3 <= len(v) <= 254) or " " in v or not _IDENTIFIER_RE.match(v):
        raise ValueError("invalid operator identifier")
    return v


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _normalize_identifier(v)


class LoginIn(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _normalize_identifier(v)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OperatorOut(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime


class RegistrationStatus(BaseModel):
    registration_open: bool
