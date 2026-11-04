"""Person-investigation API: streaming multi-agent run and one-hop click-through."""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import router as agent_router
from app.agents.base import Ctx, Request
from app.agents.router import investigate_nid, run_investigation
from app.agents.web_agent import WebAgent
from app.api.deps import get_current_operator
from app.database.models.user import User
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


async def _stream(user_id: uuid.UUID, req: Request) -> AsyncGenerator[str, None]:
    """Run the investigation in a background task on its OWN session and relay events."""
    queue: asyncio.Queue = asyncio.Queue()
    task: asyncio.Task | None = None
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
                try:
                    item = await asyncio.wait_for(queue.get(), _HEARTBEAT_INTERVAL)
                except asyncio.TimeoutError:
                    yield _HEARTBEAT
                    continue
                if item is _DONE:
                    break
                yield _sse(item[0], item[1])
            result = task.result()
            yield _sse("result", result)
            await session.commit()
            committed = True
        except Exception as e:  # noqa: BLE001
            log.exception("investigation stream failed")
            yield _sse("error", {"detail": str(e)})
        finally:
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                with contextlib.suppress(BaseException):
                    await task
            if not committed:
                with contextlib.suppress(Exception):
                    await session.rollback()


@router.post("/people/investigate")
async def investigate(body: InvestigateBody, operator: User = Depends(get_current_operator)):
    nid, phone, name = _clean(body.nid), _clean(body.phone), _clean(body.name)
    if not (nid or phone or name):
        raise HTTPException(status_code=400, detail="provide a nid, phone, or name")
    req = Request(nid=nid, phone=phone, name=name, web=body.web, analyse=body.analyse)
    return StreamingResponse(
        _stream(operator.id, req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
        res = await asyncio.wait_for(WebAgent().run(ctx), agent_router.PER_AGENT_TIMEOUT)
        if res.ok:
            data = res.data
            facts = [dataclasses.asdict(dataclasses.replace(f, id=f"F{i}"))
                     for i, f in enumerate(res.facts, 1)]
        else:
            notes.append(f"web: {res.error}")
    except asyncio.TimeoutError:
        notes.append(f"web: timed out after {agent_router.PER_AGENT_TIMEOUT:g}s")
        await agent_router._rollback(ctx)
    except Exception as e:  # noqa: BLE001
        notes.append(f"web: {str(e) or type(e).__name__}")
        await agent_router._rollback(ctx)
    return {
        "person": None,
        "web_only": True,
        "name": name,
        "findings": list(data.get("findings") or []),
        "spouse_candidates": list(data.get("spouse_names") or []),
        "facts": facts,
        "notes": notes,
        "lookup_hint": "search this name in the system",
    }


@router.get("/people/{nid:path}/investigate")
async def investigate_click(nid: str, operator: User = Depends(get_current_operator),
                            session: AsyncSession = Depends(get_session)):
    if nid.startswith("web:"):
        name = unquote(nid[4:]).strip()
        return await investigate_web_only(session, operator.id, name)
    out = await investigate_nid(session, operator.id, nid)
    if not out.get("person"):
        raise HTTPException(status_code=404, detail="person_not_found")
    return {
        "person": out["person"],
        "relations": out["relations"],
        "facts": out["facts"],
        "notes": out["notes"],
        "agents_run": out["agents_run"],
    }
