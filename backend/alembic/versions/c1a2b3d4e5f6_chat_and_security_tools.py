"""chat conversations/messages + security tool tables

Revision ID: c1a2b3d4e5f6
Revises: a3f74fe69131
Create Date: 2026-10-18

Backward-compatible: adds new tables only; touches nothing existing.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

revision = "c1a2b3d4e5f6"
down_revision = "a3f74fe69131"
branch_labels = None
depends_on = None

_TS = [
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("id", sa.Uuid(), nullable=False),
]
_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    op.create_table(
        "conversations", *_TS,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", _STR(), nullable=False),
        sa.Column("model", _STR(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_id"), "conversations", ["id"], unique=False)
    op.create_index(op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False)
    op.create_index(op.f("ix_conversations_archived"), "conversations", ["archived"], unique=False)

    op.create_table(
        "messages", *_TS,
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", _STR(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_id"), "messages", ["id"], unique=False)
    op.create_index(op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False)

    op.create_table(
        "tool_verifications", *_TS,
        sa.Column("tool_name", _STR(), nullable=False),
        sa.Column("installed", sa.Boolean(), nullable=False),
        sa.Column("path", _STR(), nullable=True),
        sa.Column("version", _STR(), nullable=True),
        sa.Column("verified_at", _STR(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_verifications_id"), "tool_verifications", ["id"], unique=False)
    op.create_index(op.f("ix_tool_verifications_tool_name"), "tool_verifications", ["tool_name"], unique=False)

    op.create_table(
        "tool_executions", *_TS,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("tool_name", _STR(), nullable=False),
        sa.Column("operation", _STR(), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("target", _STR(), nullable=True),
        sa.Column("posture", _STR(), nullable=True),
        sa.Column("status", _STR(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("error", _STR(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_executions_id"), "tool_executions", ["id"], unique=False)
    op.create_index(op.f("ix_tool_executions_user_id"), "tool_executions", ["user_id"], unique=False)
    op.create_index(op.f("ix_tool_executions_conversation_id"), "tool_executions", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_tool_executions_tool_name"), "tool_executions", ["tool_name"], unique=False)
    op.create_index(op.f("ix_tool_executions_status"), "tool_executions", ["status"], unique=False)

    op.create_table(
        "install_requests", *_TS,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("capability", _STR(), nullable=True),
        sa.Column("package", _STR(), nullable=False),
        sa.Column("source", _STR(), nullable=False),
        sa.Column("reason", _STR(), nullable=False),
        sa.Column("needs_root", sa.Boolean(), nullable=False),
        sa.Column("status", _STR(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", _STR(), nullable=True),
        sa.Column("installed_version", _STR(), nullable=True),
        sa.Column("log", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_install_requests_id"), "install_requests", ["id"], unique=False)
    op.create_index(op.f("ix_install_requests_user_id"), "install_requests", ["user_id"], unique=False)
    op.create_index(op.f("ix_install_requests_status"), "install_requests", ["status"], unique=False)

    op.create_table(
        "authorized_targets", *_TS,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("target", _STR(), nullable=False),
        sa.Column("scope", _STR(), nullable=False),
        sa.Column("note", _STR(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_authorized_targets_id"), "authorized_targets", ["id"], unique=False)
    op.create_index(op.f("ix_authorized_targets_user_id"), "authorized_targets", ["user_id"], unique=False)
    op.create_index(op.f("ix_authorized_targets_target"), "authorized_targets", ["target"], unique=False)

    op.create_table(
        "security_findings", *_TS,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("title", _STR(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", _STR(), nullable=False),
        sa.Column("confidence", _STR(), nullable=False),
        sa.Column("status", _STR(), nullable=False),
        sa.Column("asset", _STR(), nullable=True),
        sa.Column("tool", _STR(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("impact", _STR(), nullable=False),
        sa.Column("remediation", _STR(), nullable=False),
        sa.Column("validation", _STR(), nullable=False),
        sa.Column("limitations", _STR(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_security_findings_id"), "security_findings", ["id"], unique=False)
    op.create_index(op.f("ix_security_findings_user_id"), "security_findings", ["user_id"], unique=False)
    op.create_index(op.f("ix_security_findings_conversation_id"), "security_findings", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_security_findings_status"), "security_findings", ["status"], unique=False)


def downgrade() -> None:
    for t in (
        "security_findings", "authorized_targets", "install_requests",
        "tool_executions", "tool_verifications", "messages", "conversations",
    ):
        op.drop_table(t)
