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


class ToolDoc(UUIDMixin, TimestampMixin, table=True):
    """Operator-provided documentation for a security tool (scraped from a URL,
    uploaded as a file, or pasted). Injected into the model's context as
    read-only reference so it understands how the tool works."""

    __tablename__ = "tool_docs"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    tool_name: str | None = Field(default=None, index=True)  # catalogue tool it documents
    title: str = Field(nullable=False)
    source_type: str = Field(default="text")  # url | file | text
    source_ref: str | None = Field(default=None)  # the URL or filename
    content_text: str = Field(default="", sa_column=Column(Text, nullable=False))
    char_count: int = Field(default=0)


class KaiSkill(UUIDMixin, TimestampMixin, table=True):
    """An operator-authored skill: a reusable playbook that teaches KAI how the
    operator wants a recurring task done (like a Claude skill). Unlike ToolDoc
    (untrusted reference DATA), a skill is the OPERATOR'S OWN INSTRUCTION to
    their agent and is injected as guidance KAI should follow when relevant.
    Enabled skills are summarised into the system context each turn."""

    __tablename__ = "kai_skills"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    name: str = Field(nullable=False)                       # short title / slug
    description: str = Field(default="")                    # when to use it
    content_text: str = Field(default="", sa_column=Column(Text, nullable=False))
    enabled: bool = Field(default=True, index=True)
    char_count: int = Field(default=0)


class KaiProfile(UUIDMixin, TimestampMixin, table=True):
    """What KAI has learned about how THIS operator works and prefers things
    done — their style, defaults, recurring targets, do's and don'ts. One row per
    operator, editable by hand and extendable via 'learn from this session'.
    Injected into every turn so KAI adapts to the operator over time."""

    __tablename__ = "kai_profile"

    user_id: uuid.UUID = Field(index=True, unique=True, nullable=False)
    content_text: str = Field(default="", sa_column=Column(Text, nullable=False))
    char_count: int = Field(default=0)


class KaiCapabilities(UUIDMixin, TimestampMixin, table=True):
    """What the KAI model is permitted to do, controlled by the operator from
    the Capabilities panel. One row per operator. Enforced authoritatively in
    the tool gate (service.run_operation); the orchestrator also reads it to
    tell the model what is available and to gate shell auto-run."""

    __tablename__ = "kai_capabilities"

    user_id: uuid.UUID = Field(index=True, unique=True, nullable=False)
    # Master switch for the installed-tool catalogue (nmap, msf search, etc.).
    tools_enabled: bool = Field(default=True)
    # Raw terminal: the model may call the `shell.run` operation. ON by default
    # (operator wants the terminal always available). Every command is audited.
    shell_enabled: bool = Field(default=True)
    # When True, shell commands run without per-command approval (full agent
    # mode). When False, each command waits for the operator even in auto-run.
    shell_auto_run: bool = Field(default=True)
    # Allow privileged (root) shell commands via pkexec/sudo. OFF by default.
    # pkexec still shows the desktop password prompt, so the operator types
    # their password at the OS dialog even in auto-run.
    shell_sudo: bool = Field(default=False)


class CustomCapability(UUIDMixin, TimestampMixin, table=True):
    """An operator-defined security-tool capability. ``entry`` holds a
    catalogue-shaped spec (name, binary, source, ops[...]) that is merged into
    the live tool registry via ``_spec_from_catalogue`` so the tool appears in
    the inventory/palette and KAI can run it. Non-apt tools (go/pip/github) are
    installed by KAI via the terminal on first use, exactly like built-in
    catalogue tools from those sources."""

    __tablename__ = "custom_capabilities"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    name: str = Field(index=True, nullable=False)       # tool name (unique per user)
    title: str = Field(default="")
    category: str = Field(default="custom")
    enabled: bool = Field(default=True, index=True)
    entry: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))


class KaiFile(UUIDMixin, TimestampMixin, table=True):
    """A file KAI produced in the operator's workspace (via file.write or a
    shell command), downloadable from the chat. ``rel_path`` is relative to the
    per-operator workspace dir; the download endpoint resolves + validates it
    stays inside that dir before streaming."""

    __tablename__ = "kai_files"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    conversation_id: uuid.UUID | None = Field(default=None, index=True)
    name: str = Field(nullable=False)                 # basename shown/downloaded
    rel_path: str = Field(nullable=False)             # path within the workspace
    size: int = Field(default=0)
    content_type: str = Field(default="application/octet-stream")