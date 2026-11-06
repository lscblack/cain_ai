"""Request bodies for the voice API. Responses are built in app.api.voice."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    language: str | None = Field(default=None, max_length=32)
    transcript: str | None = Field(default=None, max_length=5000)
    is_default: bool | None = None


class CloneRequest(BaseModel):
    model_id: str | None = Field(default=None, max_length=64)


class TtsRequest(BaseModel):
    profile_id: uuid.UUID
    text: str = Field(min_length=1)
    language: str = Field(default="auto", max_length=32)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch_semitones: float = Field(default=0.0, ge=-12.0, le=12.0)
    temperature: float = Field(default=0.9, ge=0.1, le=1.5)
    top_p: float = Field(default=1.0, ge=0.1, le=1.0)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


class ModelAction(BaseModel):
    action: Literal["install", "load", "unload", "health"]


class VirtualMicAction(BaseModel):
    enabled: bool
