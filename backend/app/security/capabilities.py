"""Operator-controlled KAI capabilities (the Capabilities panel).

One :class:`~app.database.models.security.KaiCapabilities` row per operator
records what KAI is permitted to do. The tool gate (``service.run_operation``)
reads this authoritatively; the orchestrator reads it to decide what to
advertise to the model and whether shell commands may auto-run.

The raw-terminal operation key lives here (``SHELL_OP_KEY``) because it is not a
catalogue tool — it is gated purely by these capabilities.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.security import KaiCapabilities

# The raw-terminal operation. Not in the tool registry — handled directly by
# service.run_operation and gated by KaiCapabilities.shell_enabled.
SHELL_OP_KEY = "shell.run"


async def get_capabilities(session: AsyncSession, user_id: uuid.UUID) -> KaiCapabilities:
    """Return this operator's capabilities row, creating it with defaults on
    first access so callers can always rely on a row existing."""
    row = (
        await session.execute(
            select(KaiCapabilities).where(KaiCapabilities.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = KaiCapabilities(user_id=user_id)
        session.add(row)
        await session.flush()
        await session.refresh(row)
    return row


async def update_capabilities(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    tools_enabled: bool | None = None,
    shell_enabled: bool | None = None,
    shell_auto_run: bool | None = None,
    shell_sudo: bool | None = None,
) -> KaiCapabilities:
    """Patch the operator's capabilities. ``None`` fields are left unchanged."""
    row = await get_capabilities(session, user_id)
    if tools_enabled is not None:
        row.tools_enabled = bool(tools_enabled)
    if shell_enabled is not None:
        row.shell_enabled = bool(shell_enabled)
    if shell_auto_run is not None:
        row.shell_auto_run = bool(shell_auto_run)
    if shell_sudo is not None:
        row.shell_sudo = bool(shell_sudo)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


def to_dict(row: KaiCapabilities) -> dict:
    return {
        "tools_enabled": row.tools_enabled,
        "shell_enabled": row.shell_enabled,
        "shell_auto_run": row.shell_auto_run,
        "shell_sudo": row.shell_sudo,
    }
