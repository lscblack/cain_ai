"""Voice Intelligence tables.

Audio lives on disk (see ``app.voice.storage``); PostgreSQL only keeps references,
metadata and ownership. Voice representations are model-specific, so each one is a
``VoiceAsset`` carrying the engine id, engine version and format version that made
it — a representation is only reused by a compatible engine.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin

# Profile lifecycle.
PROFILE_DRAFT = "draft"
PROFILE_PROCESSING = "processing"
PROFILE_READY = "ready"
PROFILE_FAILED = "failed"

# Asset kinds.
ASSET_SOURCE = "source"                  # the file exactly as uploaded
ASSET_REFERENCE = "reference"            # normalized mono WAV used by the engines
ASSET_REPRESENTATION = "representation"  # engine-specific voice representation
ASSET_GENERATION = "generation"          # synthesized audio

# Generation lifecycle.
GEN_QUEUED = "queued"
GEN_RUNNING = "running"
GEN_COMPLETED = "completed"
GEN_FAILED = "failed"
GEN_CANCELED = "canceled"


class VoiceProfile(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "voice_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_voice_profile_user_name"),
        # At most one default voice per owner, enforced by the database.
        Index(
            "uq_voice_profile_user_default", "user_id", unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    user_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    )
    name: str = Field(nullable=False)
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    language: str = Field(default="auto", nullable=False)
    transcript: str = Field(default="", sa_column=Column(Text, nullable=False))
    status: str = Field(default=PROFILE_DRAFT, index=True, nullable=False)
    status_detail: str = Field(default="", sa_column=Column(Text, nullable=False))
    is_default: bool = Field(default=False, nullable=False)
    # Engine that produced the primary (TTS) representation.
    model_id: str = Field(default="", nullable=False)
    model_version: str = Field(default="", nullable=False)
    # Consent attestation — required before a profile can be created.
    consent_confirmed: bool = Field(default=False, nullable=False)
    consent_basis: str = Field(default="", nullable=False)   # own_voice | permission
    consent_subject: str = Field(default="", nullable=False)  # whose voice, in the owner's words
    consent_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    duration_s: float = Field(default=0.0, nullable=False)
    meta: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))


class VoiceAsset(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "voice_assets"
    __table_args__ = (Index("ix_voice_assets_profile_kind", "profile_id", "kind"),)

    user_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    )
    profile_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("voice_profiles.id", ondelete="CASCADE"), nullable=True),
    )
    generation_id: uuid.UUID | None = Field(default=None, index=True)
    kind: str = Field(index=True, nullable=False)
    # Path RELATIVE to the voice storage root; never returned to clients.
    rel_path: str = Field(nullable=False)
    mime: str = Field(default="application/octet-stream", nullable=False)
    size_bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    sha256: str = Field(default="", nullable=False)
    engine_id: str = Field(default="", nullable=False)
    engine_version: str = Field(default="", nullable=False)
    format_version: int = Field(default=1, nullable=False)
    active: bool = Field(default=True, nullable=False)
    meta: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))


class VoiceGeneration(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "voice_generations"
    __table_args__ = (Index("ix_voice_generations_user_created", "user_id", "created_at"),)

    user_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    )
    profile_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("voice_profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    )
    text: str = Field(sa_column=Column(Text, nullable=False))
    language: str = Field(default="auto", nullable=False)
    params: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    status: str = Field(default=GEN_QUEUED, index=True, nullable=False)
    progress: float = Field(default=0.0, nullable=False)
    error: str = Field(default="", sa_column=Column(Text, nullable=False))
    engine_id: str = Field(default="", nullable=False)
    engine_version: str = Field(default="", nullable=False)
    device: str = Field(default="", nullable=False)
    duration_s: float = Field(default=0.0, nullable=False)
    inference_s: float = Field(default=0.0, nullable=False)
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class VoiceConversionSession(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "voice_conversion_sessions"

    user_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    )
    # Survives profile deletion as an anonymous usage record.
    profile_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True),
    )
    status: str = Field(default="active", index=True, nullable=False)
    engine_id: str = Field(default="", nullable=False)
    engine_version: str = Field(default="", nullable=False)
    device: str = Field(default="", nullable=False)
    virtual_mic: bool = Field(default=False, nullable=False)
    ended_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    # Measured, never estimated: see RealtimeAudioService.
    stats: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    error: str = Field(default="", sa_column=Column(Text, nullable=False))


class VoiceModelRegistry(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "voice_model_registry"

    model_id: str = Field(unique=True, index=True, nullable=False)
    status: str = Field(default="not_installed", nullable=False)
    installed_revision: str = Field(default="", nullable=False)
    size_bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    error: str = Field(default="", sa_column=Column(Text, nullable=False))
    health: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
