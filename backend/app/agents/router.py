"""Deterministic agent router and investigation runner."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analyst_agent import AnalystAgent
from app.agents.base import Agent, AgentResult, Ctx, Request, new_fact_id
from app.agents.db_agent import DbAgent
from app.agents.ratelimit import WEB_SKIPPED_NOTE, web_budget_exhausted
from app.agents.relations_agent import RelationsAgent
from app.agents.web_agent import WebAgent
from app.database.models.enrich import Person
from app.database.repositories.audit_repo import AuditRepository

log = logging.getLogger(__name__)

PER_AGENT_TIMEOUT = 25.0
MAX_PEOPLE = 5  # candidate cards returned; candidate_count keeps the true total
# Agents that legitimately need longer than PER_AGENT_TIMEOUT: the analyst runs
# a local (often CPU-only) model. The SSE heartbeat keeps the stream alive.
AGENT_TIMEOUTS: dict[str, float] = {"analyst": 180.0}

Emit = Callable[[str, dict], Awaitable[None]]


def select_agents(req: Request, person_found: bool) -> list[str]:
    """Full ordered agent list for a given state (db always first)."""
    if not (req.nid or req.phone or req.name or req.image):
        return []
    names = ["db"]
    web = bool(req.web) or not person_found
    if web:
        names.append("web")
    if person_found:
        names.append("relations")
    if req.analyse and (person_found or web):
        names.append("analyst")
    return names


def _default_agents() -> dict[str, Agent]:
    return {a.name: a for a in (DbAgent(), WebAgent(), RelationsAgent(), AnalystAgent())}


def _timeout_for(name: str) -> float:
    return AGENT_TIMEOUTS.get(name, PER_AGENT_TIMEOUT)


async def _rollback(ctx: Ctx) -> None:
    """Reset the shared session after a failed/cancelled agent.

    A cancelled or failed query leaves the AsyncSession needing a rollback,
    which would break later agents and the audit write. Cost: anything
    flushed but not yet committed earlier in this run (e.g. a newly fetched
    record persisted by resolve_identity) can be rolled back when a LATER
    agent fails.
    """
    try:
        await ctx.session.rollback()
    except Exception:  # noqa: BLE001 - never propagate
        log.exception("session rollback after agent failure failed")


async def _reload_subject(ctx: Ctx) -> None:
    """Re-load the subject after a rollback.

    ``session.rollback()`` expires every ORM instance, so the next attribute
    access on ``ctx.person`` would lazy-load outside the async greenlet
    (MissingGreenlet) and kill the relations agent. Costs one query.
    """
    db = ctx.results.get("db")
    nid = (db.data or {}).get("person_nid") if db is not None else None
    if not nid:
        return
    try:
        ctx.person = (await ctx.session.execute(
            select(Person).where(Person.nid == nid))).scalars().first()
    except Exception:  # noqa: BLE001 - never propagate
        log.exception("re-loading the subject after rollback failed")
        ctx.person = None


async def _web_budget_spent(ctx: Ctx) -> bool:
    """True if the operator's web budget is spent (checked before EVERY web step,
    explicit or automatic). Fails open: a failed check never blocks the run."""
    try:
        return await web_budget_exhausted(ctx.session, ctx.user_id)
    except Exception:  # noqa: BLE001
        log.exception("web budget check failed")
        await _rollback(ctx)
        await _reload_subject(ctx)
        return False


async def _run_one(agent: Agent, name: str, ctx: Ctx, emit: Emit,
                   notes: list[str]) -> AgentResult:
    await emit("agent_start", {"agent": name})
    try:
        timeout = _timeout_for(name)
        res = await asyncio.wait_for(agent.run(ctx), timeout)
    except asyncio.TimeoutError:
        # Note: an agent's own internal TimeoutError is indistinguishable here
        # from the wait_for timeout; both are reported as a timeout.
        res = AgentResult(agent=name, ok=False, facts=[], data={},
                          error=f"timed out after {timeout:g}s")
        await _rollback(ctx)
        await _reload_subject(ctx)
    except Exception as e:  # noqa: BLE001 - agents must never break the run
        res = AgentResult(agent=name, ok=False, facts=[], data={},
                          error=str(e) or type(e).__name__)
        await _rollback(ctx)
        await _reload_subject(ctx)
    if not res.ok:
        notes.append(f"{name}: {res.error}")
        await emit("agent_error", {"agent": name})
    else:
        await emit("agent_done", {"agent": name})
    return res


async def run_investigation(session: AsyncSession, user_id: uuid.UUID, req: Request,
                            emit: Emit, *, agents: dict[str, Agent] | None = None) -> dict:
    """Run db -> web -> relations -> analyst and return the combined result.

    The audit entry is only flushed; the caller owns the commit. A streaming
    caller must use its own session (not a request-scoped dependency session)
    and commit explicitly after this returns.
    """
    agents = agents or _default_agents()
    ctx = Ctx(session=session, user_id=user_id, request=req, person=None,
              results={}, emit=emit)
    notes: list[str] = []
    run: list[str] = []
    all_facts: list = []
    counter = 0

    async def step(name: str) -> AgentResult | None:
        nonlocal counter
        agent = agents.get(name)
        if agent is None:
            notes.append(f"{name}: agent unavailable")
            await emit("agent_error", {"agent": name})
            return None
        res = await _run_one(agent, name, ctx, emit, notes)
        renum = []
        for f in res.facts:
            counter += 1
            renum.append(dataclasses.replace(f, id=new_fact_id(counter)))
        res.facts = renum
        all_facts.extend(renum)
        ctx.results[name] = res
        run.append(name)
        return res

    people: list[dict] = []
    found = False
    if select_agents(req, False):
        db_res = await step("db")
        if db_res is not None:
            people = list(db_res.data.get("people") or []) if db_res.ok else []
            found = bool(people)
        if not found and db_res is not None and db_res.ok:
            notes.append("no matching person found in the saved database")
        for name in select_agents(req, found)[1:]:
            if name == "web" and await _web_budget_spent(ctx):
                # degrade, don't fail: the rest of the investigation still runs
                notes.append(WEB_SKIPPED_NOTE)
                await emit("agent_error", {"agent": name})
                continue
            await step(name)

    def data(name: str) -> dict | None:
        r = ctx.results.get(name)
        return r.data if r is not None and r.ok else None

    web = data("web") or {}
    analyst = data("analyst") or {}
    db = data("db") or {}
    out = {
        "person": people[0] if people else None,
        "people": people[:MAX_PEOPLE],
        "candidate_count": len(people),
        "ambiguous": bool(db.get("ambiguous")),
        "relations": data("relations"),
        "web_findings": list(web.get("findings") or []),
        "spouse_candidates": list(web.get("spouse_names") or []),
        "analysis": analyst.get("analysis"),
        # only the COUNT of removed sentences: the sentences themselves are
        # ungrounded model text and must never reach the client
        "analysis_dropped_count": len(analyst.get("dropped") or []),
        "omitted_facts": int(analyst.get("omitted_facts") or 0),
        "name_collision_warning": bool(web.get("name_collision_warning")),
        "facts": [dataclasses.asdict(f) for f in all_facts],
        "notes": notes,
        "agents_run": run,
    }

    try:
        await AuditRepository(session).record(
            "people.investigate", actor_id=user_id,
            detail={"query": {"nid": req.nid, "phone": req.phone, "name": req.name,
                              "has_image": bool(req.image), "web": bool(req.web),
                              "analyse": bool(req.analyse)},
                    "agents": list(run), "found": found})
    except Exception:  # noqa: BLE001 - audit must not break the investigation
        log.exception("people.investigate audit failed")
        notes.append("audit failed")
    return out


async def _noop(event: str, payload: dict) -> None:
    return None


async def investigate_nid(session: AsyncSession, user_id: uuid.UUID, nid: str,
                          emit: Emit | None = None) -> dict:
    """One-hop click-through: DB card + relations, no web, no analyst."""
    return await run_investigation(session, user_id,
                                   Request(nid=nid, web=False, analyse=False),
                                   emit or _noop)
