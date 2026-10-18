"""Persistence for KAI's security-tool capabilities.

Tables:
- tool_verifications   last discovered/verified state of each registered tool
- tool_executions      every tool run (audit + Execution History UI)
- install_requests     package-install approval workflow
- authorized_targets   operator-approved scopes for ACTIVE assessment
- security_findings    structured findings with evidence/provenance
"""
from __future__ import annotations

import uuid

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin


class ToolVerification(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "tool_verifications"

    tool_name: str = Field(index=True, nullable=False)
    installed: bool = Field(default=False)
    path: str | None = Field(default=None)
    version: str | None = Field(default=None)
    verified_at: str | None = Field(default=None)  # ISO8601 of last probe


class ToolExecution(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "tool_executions"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    conversation_id: uuid.UUID | None = Field(default=None, index=True)
    tool_name: str = Field(index=True, nullable=False)
    operation: str = Field(nullable=False)
    args: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]"))
    target: str | None = Field(default=None)
    posture: str | None = Field(default=None)  # passive | active | disruptive
    status: str = Field(default="ok", index=True)  # ok | error | timeout | blocked | denied
    exit_code: int | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    stdout: str = Field(default="", sa_column=Column(Text, nullable=False))
    stderr: str = Field(default="", sa_column=Column(Text, nullable=False))
    error: str | None = Field(default=None)


class InstallRequest(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "install_requests"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    capability: str | None = Field(default=None)
    package: str = Field(nullable=False)
    source: str = Field(default="apt")  # apt | ...
    reason: str = Field(default="")
    needs_root: bool = Field(default=True)
    # pending | approved | rejected | installing | installed | failed
    status: str = Field(default="pending", index=True)
    decided_by: uuid.UUID | None = Field(default=None)
    decided_at: str | None = Field(default=None)
    installed_version: str | None = Field(default=None)
    log: str = Field(default="", sa_column=Column(Text, nullable=False))


class AuthorizedTarget(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "authorized_targets"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    target: str = Field(index=True, nullable=False)  # host | domain | CIDR | IP
    scope: str = Field(default="active")  # passive | active
    note: str = Field(default="")
    active: bool = Field(default=True)


class SecurityFinding(UUIDMixin, TimestampMixin, table=True):
    __tablename__ = "security_findings"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    conversation_id: uuid.UUID | None = Field(default=None, index=True)
    title: str = Field(nullable=False)
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    severity: str = Field(default="info")  # info | low | medium | high | critical
    confidence: str = Field(default="suspected")  # suspected | likely | confirmed
    status: str = Field(default="suspected", index=True)  # suspected | verified
    asset: str | None = Field(default=None)
    tool: str | None = Field(default=None)
    evidence: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]"))
    impact: str = Field(default="")
    remediation: str = Field(default="")
    validation: str = Field(default="")
    limitations: str = Field(default="")
