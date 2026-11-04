"""Deterministic agent router and investigation runner."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analyst_agent import AnalystAgent
from app.agents.base import Agent, AgentResult, Ctx, Request, new_fact_id
from app.agents.db_agent import DbAgent
from app.agents.relations_agent import RelationsAgent
from app.agents.web_agent import WebAgent
from app.database.repositories.audit_repo import AuditRepository

log = logging.getLogger(__name__)

PER_AGENT_TIMEOUT = 25.0

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


def _timeout_label() -> str:
    t = PER_AGENT_TIMEOUT
    return f"{t:g}s"


async def _run_one(agent: Agent, name: str, ctx: Ctx, emit: Emit,
                   notes: list[str]) -> AgentResult:
    await emit("agent_start", {"agent": name})
    try:
        res = await asyncio.wait_for(agent.run(ctx), PER_AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        res = AgentResult(agent=name, ok=False, facts=[], data={},
                          error=f"timed out after {_timeout_label()}")
    except Exception as e:  # noqa: BLE001 - agents must never break the run
        res = AgentResult(agent=name, ok=False, facts=[], data={},
                          error=str(e) or type(e).__name__)
    if not res.ok:
        notes.append(f"{name}: {res.error}")
        await emit("agent_error", {"agent": name})
    else:
        await emit("agent_done", {"agent": name})
    return res


async def run_investigation(session: AsyncSession, user_id: uuid.UUID, req: Request,
                            emit: Emit, *, agents: dict[str, Agent] | None = None) -> dict:
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
            await step(name)

    def data(name: str) -> dict | None:
        r = ctx.results.get(name)
        return r.data if r is not None and r.ok else None

    web = data("web") or {}
    analyst = data("analyst") or {}
    out = {
        "person": people[0] if people else None,
        "people": people,
        "relations": data("relations"),
        "web_findings": list(web.get("findings") or []),
        "spouse_candidates": list(web.get("spouse_names") or []),
        "analysis": analyst.get("analysis"),
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
