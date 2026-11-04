"""Per-operator throttles for person investigations (people.investigate).

Two mechanisms:

* **Budgets** from the audit log: every investigation (POST stream, chat op,
  click-through, web-only card) writes one ``people.investigate`` row, so the
  operator's rows in the last minute are the rate counter. Web usage is
  counted by what actually RAN (``detail.agents`` contains "web"), not only by
  what was asked (``query.web``), because the web agent also runs
  automatically when no person is found.
* An in-process **concurrency cap** (``investigation_slot``): the audit row is
  written only when a run finishes, so without it parallel requests would all
  pass the budget check. Single-process only: with several workers each has
  its own counters.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.audit import AuditLog

TOTAL_PER_MIN = 30  # all investigations (click-through browsing included)
WEB_PER_MIN = 5  # investigations in which the web agent ran
MAX_CONCURRENT = 2  # investigations running at once, per operator

ACTION = "people.investigate"
WINDOW_SECONDS = 60
RATE_LIMITED = "rate limited: too many investigations, retry in a minute"
BUSY = "an investigation is already running — wait for it to finish"
WEB_SKIPPED_NOTE = "web search skipped: rate limited (try again in a minute)"


class RateLimited(Exception):
    """Raised when an operator already holds MAX_CONCURRENT investigation slots."""


def _recent(user_id: uuid.UUID):
    since = datetime.now(timezone.utc) - timedelta(seconds=WINDOW_SECONDS)
    return select(func.count()).select_from(AuditLog).where(
        AuditLog.action == ACTION, AuditLog.actor_id == user_id, AuditLog.created_at >= since)


def _web_ran():
    d = AuditLog.detail
    return or_(d["agents"].contains(["web"]),
               d["query"]["web"].astext == "true",
               d["query"]["web_only"].astext == "true")


async def _count(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar() or 0)


async def web_budget_exhausted(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """True if WEB_PER_MIN investigations with web lookups ran in the last minute."""
    return await _count(session, _recent(user_id).where(_web_ran())) >= WEB_PER_MIN


async def check_investigation_rate(session: AsyncSession, user_id: uuid.UUID,
                                   web: bool) -> str | None:
    """Error message if this request would exceed a budget, else None.

    At most TOTAL_PER_MIN investigations per operator per minute; a request that
    explicitly asks for the web (``web`` True) is also refused once the web
    budget is spent. Requests that do not ask for the web are not refused here:
    the router skips an automatic web step instead (see router.run_investigation).
    """
    if await _count(session, _recent(user_id)) >= TOTAL_PER_MIN:
        return RATE_LIMITED
    if web and await web_budget_exhausted(session, user_id):
        return RATE_LIMITED
    return None


# ---- concurrency ---------------------------------------------------------- #

_active: dict[uuid.UUID, int] = {}


class Slot:
    """A held concurrency slot. ``release`` is idempotent."""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        left = _active.get(self.user_id, 1) - 1
        if left <= 0:
            _active.pop(self.user_id, None)
        else:
            _active[self.user_id] = left


def acquire_slot(user_id: uuid.UUID) -> Slot:
    """Take a slot or raise RateLimited (a rejected attempt holds nothing)."""
    n = _active.get(user_id, 0)
    if n >= MAX_CONCURRENT:
        raise RateLimited(BUSY)
    _active[user_id] = n + 1
    return Slot(user_id)


@asynccontextmanager
async def investigation_slot(user_id: uuid.UUID) -> AsyncIterator[Slot]:
    slot = acquire_slot(user_id)
    try:
        yield slot
    finally:
        slot.release()
