"""Person-investigation API: streaming multi-agent run and one-hop click-through."""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import router as agent_router
from app.agents.base import Ctx, Request
from app.agents.ratelimit import RateLimited, Slot, acquire_slot, check_investigation_rate
from app.agents.router import investigate_nid, run_investigation
from app.agents.web_agent import WebAgent
from app.api.deps import get_current_operator
from app.database.models.user import User
from app.database.repositories.audit_repo import AuditRepository
from app.database.session import async_session_maker, get_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/enrich", tags=["investigate"])

_HEARTBEAT = ": keepalive\n\n"
_HEARTBEAT_INTERVAL = 15.0
_DONE = object()


class InvestigateBody(BaseModel):
    nid: str | None = None
    phone: str | None = None
    name: str | None = None
    web: bool = False
    analyse: bool = False


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


async def _stream(user_id: uuid.UUID, req: Request,
                  slot: Slot | None = None) -> AsyncGenerator[str, None]:
    """Run the investigation in a background task on its OWN session and relay events.

    The audit row is committed BEFORE the result event is yielded, so a client
    that disconnects right after `result` cannot lose it. ``slot`` (the
    operator's concurrency slot) is released when the generator ends, however
    it ends (result, error, client disconnect / aclose, cancellation).
    """
    queue: asyncio.Queue = asyncio.Queue()
    task: asyncio.Task | None = None
    getter: asyncio.Task | None = None
    committed = False
    async with async_session_maker() as session:
        try:
            async def emit(event: str, payload: dict) -> None:
                await queue.put((event, payload))

            async def work() -> dict:
                try:
                    return await run_investigation(session, user_id, req, emit)
                finally:
                    queue.put_nowait(_DONE)

            task = asyncio.ensure_future(work())
            while True:
                if getter is None:
                    getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter}, timeout=_HEARTBEAT_INTERVAL)
                if not done:
                    yield _HEARTBEAT
                    continue
                item = getter.result()
                getter = None
                if item is _DONE:
                    break
                yield _sse(item[0], item[1])
            if task.cancelled():
                raise RuntimeError("investigation run was cancelled")
            result = task.result()
            json.dumps(result, default=str)  # serialisable before we commit
            await asyncio.shield(session.commit())
            committed = True
            yield _sse("result", result)
        except Exception:  # noqa: BLE001
            log.exception("investigation stream failed")
            yield _sse("error", {"detail": "investigation failed"})
        finally:
            for t in (getter, task):
                if t is not None and not t.done():
                    t.cancel()
            for t in (getter, task):
                if t is not None:
                    with contextlib.suppress(BaseException):
                        await t
            if not committed:
                with contextlib.suppress(Exception):
                    await session.rollback()
            if slot is not None:
                slot.release()


@router.post("/people/investigate")
async def investigate(body: InvestigateBody, operator: User = Depends(get_current_operator)):
    nid, phone, name = _clean(body.nid), _clean(body.phone), _clean(body.name)
    if not (nid or phone or name):
        raise HTTPException(status_code=400, detail="provide a nid, phone, or name")
    req = Request(nid=nid, phone=phone, name=name, web=body.web, analyse=body.analyse)
    # throttle BEFORE streaming starts, so the client gets a real HTTP 429
    async with async_session_maker() as s:
        limited = await check_investigation_rate(s, operator.id, web=bool(body.web))
    if limited:
        raise HTTPException(status_code=429, detail=limited)
    try:
        slot = acquire_slot(operator.id)
    except RateLimited as e:
        raise HTTPException(status_code=429, detail=str(e)) from None
    # Released by the generator's finally; the background task is a backstop
    # for a body that is never iterated (release is idempotent).
    return StreamingResponse(
        _stream(operator.id, req, slot),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(slot.release),
    )


async def investigate_web_only(session: AsyncSession, user_id: uuid.UUID, name: str) -> dict:
    """Card for a person seen only on the web: run just the WebAgent."""
    notes: list[str] = []
    facts: list[dict] = []
    data: dict = {}

    async def _noop(event: str, payload: dict) -> None:
        return None

    req = Request(name=name, web=True)
    ctx = Ctx(session=session, user_id=user_id, request=req, person=None,
              results={}, emit=_noop)
    try:
        timeout = agent_router._timeout_for("web")
        res = await asyncio.wait_for(WebAgent().run(ctx), timeout)
        if res.ok:
            data = res.data
            facts = [dataclasses.asdict(dataclasses.replace(f, id=f"F{i}"))
                     for i, f in enumerate(res.facts, 1)]
        else:
            notes.append(f"web: {res.error}")
    except asyncio.TimeoutError:
        notes.append(f"web: timed out after {timeout:g}s")
        await agent_router._rollback(ctx)
    except Exception as e:  # noqa: BLE001
        notes.append(f"web: {str(e) or type(e).__name__}")
        await agent_router._rollback(ctx)
    try:
        await AuditRepository(session).record(
            "people.investigate", actor_id=user_id,
            detail={"query": {"name": name, "web_only": True}, "agents": ["web"],
                    "found": False})
    except Exception:  # noqa: BLE001 - audit must not break the card
        log.exception("people.investigate audit failed")
        notes.append("audit failed")
    return {
        "person": None,
        "web_only": True,
        "name": name,
        "findings": list(data.get("findings") or []),
        "spouse_candidates": list(data.get("spouse_names") or []),
        "name_collision_warning": bool(data.get("name_collision_warning")),
        "facts": facts,
        "notes": notes,
        "lookup_hint": "search this name in the system",
    }


@router.get("/people/{nid:path}/investigate")
async def investigate_click(nid: str, operator: User = Depends(get_current_operator),
                            session: AsyncSession = Depends(get_session)):
    web_only = nid.startswith("web:")
    if web_only:
        name = nid[4:].strip()
        if not name:
            raise HTTPException(status_code=400, detail="empty name")
        if len(name) > 200:
            raise HTTPException(status_code=400, detail="name too long")
    # a web-only card runs web lookups, so it counts against the web limit too
    limited = await check_investigation_rate(session, operator.id, web=web_only)
    if limited:
        raise HTTPException(status_code=429, detail=limited)
    try:
        slot = acquire_slot(operator.id)
    except RateLimited as e:
        raise HTTPException(status_code=429, detail=str(e)) from None
    try:
        if web_only:
            return await investigate_web_only(session, operator.id, name)
        out = await investigate_nid(session, operator.id, nid)
    finally:
        slot.release()
    if not out.get("person"):
        # commit the audit row first: the request session rolls back on the
        # HTTPException, and an unknown-NID probe must still be audited
        await session.commit()
        raise HTTPException(status_code=404, detail="person_not_found")
    return {
        "person": out["person"],
        "ambiguous": out.get("ambiguous", False),
        "candidate_count": out.get("candidate_count", 1),
        "relations": out["relations"],
        "facts": out["facts"],
        "notes": out["notes"],
        "agents_run": out["agents_run"],
    }
