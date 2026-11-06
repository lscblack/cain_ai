"""voice intelligence tables

Revision ID: e7b1c2d3f4a5
Revises: c1a2b3d4e5f6
Create Date: 2026-11-04

Additive only. The app also runs ``create_all`` at startup, so a table may already
exist when this runs; existing tables are left untouched.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e7b1c2d3f4a5"
down_revision = "c1a2b3d4e5f6"
branch_labels = None
depends_on = None

TABLES = [
    "voice_generations", "voice_assets", "voice_conversion_sessions",
    "voice_profiles", "voice_model_registry",
]


def _base() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
    ]


def _owner() -> sa.Column:
    return sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


def _json(name: str) -> sa.Column:
    return sa.Column(name, postgresql.JSONB(), nullable=False)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "voice_profiles" not in existing:
        op.create_table(
            "voice_profiles", *_base(), _owner(),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("language", sa.String(), nullable=False),
            sa.Column("transcript", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("status_detail", sa.Text(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("model_id", sa.String(), nullable=False),
            sa.Column("model_version", sa.String(), nullable=False),
            sa.Column("consent_confirmed", sa.Boolean(), nullable=False),
            sa.Column("consent_basis", sa.String(), nullable=False),
            sa.Column("consent_subject", sa.String(), nullable=False),
            sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_s", sa.Float(), nullable=False),
            _json("meta"),
            sa.UniqueConstraint("user_id", "name", name="uq_voice_profile_user_name"),
        )
        op.create_index("ix_voice_profiles_id", "voice_profiles", ["id"])
        op.create_index("ix_voice_profiles_user_id", "voice_profiles", ["user_id"])
        op.create_index("ix_voice_profiles_status", "voice_profiles", ["status"])
        op.create_index(
            "uq_voice_profile_user_default", "voice_profiles", ["user_id"], unique=True,
            postgresql_where=sa.text("is_default"),
        )

    if "voice_assets" not in existing:
        op.create_table(
            "voice_assets", *_base(), _owner(),
            sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("voice_profiles.id", ondelete="CASCADE"), nullable=True),
            sa.Column("generation_id", sa.Uuid(), nullable=True),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("rel_path", sa.String(), nullable=False),
            sa.Column("mime", sa.String(), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("sha256", sa.String(), nullable=False),
            sa.Column("engine_id", sa.String(), nullable=False),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("format_version", sa.Integer(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            _json("meta"),
        )
        op.create_index("ix_voice_assets_id", "voice_assets", ["id"])
        op.create_index("ix_voice_assets_user_id", "voice_assets", ["user_id"])
        op.create_index("ix_voice_assets_kind", "voice_assets", ["kind"])
        op.create_index("ix_voice_assets_generation_id", "voice_assets", ["generation_id"])
        op.create_index("ix_voice_assets_profile_kind", "voice_assets", ["profile_id", "kind"])

    if "voice_generations" not in existing:
        op.create_table(
            "voice_generations", *_base(), _owner(),
            sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("voice_profiles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("language", sa.String(), nullable=False),
            _json("params"),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("progress", sa.Float(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("engine_id", sa.String(), nullable=False),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("device", sa.String(), nullable=False),
            sa.Column("duration_s", sa.Float(), nullable=False),
            sa.Column("inference_s", sa.Float(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_voice_generations_id", "voice_generations", ["id"])
        op.create_index("ix_voice_generations_profile_id", "voice_generations", ["profile_id"])
        op.create_index("ix_voice_generations_status", "voice_generations", ["status"])
        op.create_index("ix_voice_generations_user_created", "voice_generations", ["user_id", "created_at"])

    if "voice_conversion_sessions" not in existing:
        op.create_table(
            "voice_conversion_sessions", *_base(), _owner(),
            sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("engine_id", sa.String(), nullable=False),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("device", sa.String(), nullable=False),
            sa.Column("virtual_mic", sa.Boolean(), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            _json("stats"),
            sa.Column("error", sa.Text(), nullable=False),
        )
        op.create_index("ix_voice_conversion_sessions_id", "voice_conversion_sessions", ["id"])
        op.create_index("ix_voice_conversion_sessions_user_id", "voice_conversion_sessions", ["user_id"])
        op.create_index("ix_voice_conversion_sessions_status", "voice_conversion_sessions", ["status"])

    if "voice_model_registry" not in existing:
        op.create_table(
            "voice_model_registry", *_base(),
            sa.Column("model_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("installed_revision", sa.String(), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            _json("health"),
        )
        op.create_index("ix_voice_model_registry_id", "voice_model_registry", ["id"])
        op.create_index("ix_voice_model_registry_model_id", "voice_model_registry", ["model_id"], unique=True)


def downgrade() -> None:
    # Drops metadata only. Audio on disk is deliberately not touched by a migration.
    for name in TABLES:
        op.drop_table(name)
