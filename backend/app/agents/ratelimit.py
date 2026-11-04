"""Per-operator throttle for person investigations (people.investigate).

Counts the operator's own ``people.investigate`` audit rows in the last
minute: every investigation (POST stream, chat op, click-through) writes one,
so the audit log doubles as the rate counter without a new table.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.audit import AuditLog

ACTION = "people.investigate"
WINDOW_SECONDS = 60
MAX_PER_MINUTE = 10  # all investigations
MAX_WEB_PER_MINUTE = 5  # investigations that run external web lookups
RATE_LIMITED = "rate limited: too many investigations, retry in a minute"


async def check_investigation_rate(session: AsyncSession, user_id: uuid.UUID,
                                   web: bool) -> str | None:
    """Return an error message if this request would exceed the limits, else None.

    At most MAX_PER_MINUTE investigations per operator per minute, and at most
    MAX_WEB_PER_MINUTE of them with web lookups (``query.web`` true, or a
    web-only card). The web limit is only checked when ``web`` is True.
    """
    since = datetime.now(timezone.utc) - timedelta(seconds=WINDOW_SECONDS)
    base = select(func.count()).select_from(AuditLog).where(
        AuditLog.action == ACTION, AuditLog.actor_id == user_id, AuditLog.created_at >= since)
    total = int((await session.execute(base)).scalar() or 0)
    if total >= MAX_PER_MINUTE:
        return RATE_LIMITED
    if web:
        q = AuditLog.detail["query"]
        web_rows = int((await session.execute(base.where(or_(
            q["web"].astext == "true", q["web_only"].astext == "true")))).scalar() or 0)
        if web_rows >= MAX_WEB_PER_MINUTE:
            return RATE_LIMITED
    return None
