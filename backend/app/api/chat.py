"""Chat API: conversations, messages, model status, and streaming turns.

Streaming uses Server-Sent Events (same ``event:``/``data:`` framing as the face
search stream). A turn can either be a plain streamed completion or a tool-using
orchestration (the default), chosen per message via ``use_tools``.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ollama import (
    GenParams,
    OllamaError,
    OllamaProvider,
    get_ollama_provider,
    provider_for_model,
    resolve_provider_for_model,
)
from app.ai.router import AIMessage
from app.api.deps import get_current_operator
from app.database.models.conversation import Conversation, Message
from app.database.models.user import User
from app import chat_runs
from app.database.session import async_session_maker, get_session
from app.security import orchestrator

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_provider() -> OllamaProvider:
    return get_ollama_provider()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# SSE comment line — ignored by the client, keeps the connection from going
# idle while the (slow, CPU-only) model generates with no events to emit.
_HEARTBEAT = ": keepalive\n\n"
_HEARTBEAT_INTERVAL = 15.0


async def _with_heartbeat(aiter: AsyncIterator, interval: float = _HEARTBEAT_INTERVAL):
    """Yield ("data", item) from aiter, injecting ("ping", None) whenever no
    item arrives within `interval` seconds — WITHOUT cancelling the in-flight
    await (so the model keeps generating). Exceptions from aiter propagate."""
    it = aiter.__aiter__()
    pending: asyncio.Task | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(it.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ("ping", None)
                continue
            task, pending = pending, None
            try:
                item = task.result()
            except StopAsyncIteration:
                return
            yield ("data", item)
    finally:
        if pending is not None:
            pending.cancel()


# ───────────────────────── schemas ──────────────────────────────────── #
class NewConversation(BaseModel):
    title: str | None = None
    model: str | None = None


class PatchConversation(BaseModel):
    title: str | None = None
    archived: bool | None = None
    model: str | None = None


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    use_tools: bool = True
    # When False (the default) every tool call KAI proposes pauses for the
    # operator to approve in chat, showing the real command it would run.
    auto_approve: bool = False
    # Enable Qwen3-style reasoning for this turn (slower on CPU, more accurate).
    # The <think> block is stripped before display and tool-protocol detection.
    think: bool = False
    # "auto" = one agent turn (default). "multi" = decompose into subtasks and
    # run a focused sub-agent per subtask (sequential), then synthesize.
    mode: str = Field(default="auto", pattern="^(auto|multi)$")


def _conv_out(c: Conversation) -> dict:
    return {
        "id": str(c.id), "title": c.title, "model": c.model, "archived": c.archived,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _msg_out(m: Message) -> dict:
    return {
        "id": str(m.id), "role": m.role, "content": m.content,
        "tool_calls": m.tool_calls, "tool_results": m.tool_results, "meta": m.meta,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# ───────────────────────── status / models ──────────────────────────── #
@router.get("/status")
async def model_status(
    operator: User = Depends(get_current_operator),
    provider: OllamaProvider = Depends(get_chat_provider),
) -> dict:
    from app.ai.ollama import list_all_models

    st = (await provider.status()).to_dict()
    # Offer models from BOTH backends in the dropdown (llama.cpp + Ollama), so
    # the operator can pick a model added on either. The selected model is then
    # routed to whichever backend actually serves it.
    detail = await list_all_models()
    names = [m["name"] for m in detail]
    st["models_available"] = list(dict.fromkeys((st.get("models_available") or []) + names))
    st["models_detail"] = detail
    return st


@router.get("/models")
async def list_models(
    operator: User = Depends(get_current_operator),
    provider: OllamaProvider = Depends(get_chat_provider),
) -> dict:
    try:
        models = await provider.list_models()
    except OllamaError as exc:
        return {"models": [], "configured": provider.model, "error": f"{exc.code}: {exc}"}
    return {"models": models, "configured": provider.model}


# ───────────────────────── files KAI produced ───────────────────────── #
@router.get("/files")
async def list_files(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """All files KAI has written to the operator's workspace (newest first)."""
    from sqlalchemy import select

    from app.database.models.security import KaiFile
    from app.security import workspace as ws

    rows = (
        await session.execute(
            select(KaiFile).where(KaiFile.user_id == operator.id).order_by(KaiFile.created_at.desc())
        )
    ).scalars().all()
    return {"files": [ws.file_out(r) for r in rows]}


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Stream a workspace file as a download. The path is validated to stay
    inside the operator's workspace before serving."""
    from app.security import workspace as ws

    found = await ws.resolve_download(session, user_id=operator.id, file_id=file_id)
    if found is None:
        raise HTTPException(status_code=404, detail="file_not_found")
    path, row = found
    return FileResponse(path, filename=row.name, media_type=row.content_type)


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete an asset (the file on disk + its record)."""
    from app.database.models.security import KaiFile
    from app.security import workspace as ws

    found = await ws.resolve_download(session, user_id=operator.id, file_id=file_id)
    if found is not None:
        path, _ = found
        try:
            path.unlink()
        except OSError:
            pass
    row = await session.get(KaiFile, file_id)
    if row is not None and row.user_id == operator.id:
        await session.delete(row)
        await session.flush()


# ───────────────────────── conversations ────────────────────────────── #
@router.post("/conversations", status_code=201)
async def create_conversation(
    body: NewConversation,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    provider: OllamaProvider = Depends(get_chat_provider),
) -> dict:
    conv = Conversation(
        user_id=operator.id,
        title=(body.title or "New conversation")[:200],
        model=body.model or provider.model,
    )
    session.add(conv)
    await session.flush()
    await session.refresh(conv)
    return _conv_out(conv)


@router.get("/conversations")
async def list_conversations(
    archived: bool = False,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.execute(
            select(Conversation)
            .where(Conversation.user_id == operator.id, Conversation.archived == archived)
            .order_by(Conversation.updated_at.desc())
        )
    ).scalars().all()
    return [_conv_out(c) for c in rows]


async def _get_conv_or_404(conv_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession) -> Conversation:
    conv = await session.get(Conversation, conv_id)
    if conv is None or conv.user_id != user_id:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    return conv


@router.get("/conversations/{conv_id}")
async def get_conversation(
    conv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _get_conv_or_404(conv_id, operator.id, session)
    msgs = (
        await session.execute(
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.asc())
        )
    ).scalars().all()
    return {**_conv_out(conv), "messages": [_msg_out(m) for m in msgs]}


def _strip_think(text: str) -> str:
    """Remove any <think>…</think> reasoning a hybrid model may emit."""
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()


@router.post("/conversations/{conv_id}/summary")
async def summarize_conversation(
    conv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    provider: OllamaProvider = Depends(get_chat_provider),
) -> dict:
    """Generate an operator-facing summary of the whole session: what was asked,
    what KAI did (tools/commands), key findings, and recommended follow-ups.
    Computed on demand and returned — not persisted, so no schema change."""
    conv = await _get_conv_or_404(conv_id, operator.id, session)
    rows = (
        await session.execute(
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.asc())
        )
    ).scalars().all()

    lines: list[str] = []
    for m in rows:
        if m.role == "user" and m.content:
            lines.append(f"OPERATOR: {m.content.strip()[:1500]}")
        elif m.role == "assistant":
            ops = ", ".join(
                c.get("operation", "") for c in (m.tool_calls or []) if isinstance(c, dict)
            ).strip(", ")
            if ops:
                lines.append(f"KAI[ran: {ops}]: {(m.content or '').strip()[:1500]}")
            elif m.content:
                lines.append(f"KAI: {m.content.strip()[:1500]}")
    if not lines:
        return {"summary": "Nothing to summarize yet — this session has no messages."}

    transcript = "\n".join(lines)
    if len(transcript) > 12000:
        transcript = "…(earlier turns omitted)…\n" + transcript[-12000:]

    # Bind to the conversation's selected model, routed to its backend.
    if conv.model and conv.model != provider.model:
        try:
            provider = await resolve_provider_for_model(conv.model)
        except OllamaError:
            pass

    msgs = [
        AIMessage(role="system", content=(
            "You are KAI. Summarize the following security/OSINT session for the operator. "
            "Be concise and technical. Use these markdown sections, omitting any that have no "
            "content: **Objective**, **Actions taken** (tools/commands run), **Key findings**, "
            "**Artifacts** (files produced), **Recommended next steps**. Do not invent anything "
            "not supported by the transcript."
        )),
        AIMessage(role="user", content=f"SESSION TRANSCRIPT:\n\n{transcript}\n\nWrite the summary now."),
    ]
    try:
        text = await provider.chat(msgs, params=GenParams())
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=f"{getattr(exc, 'code', 'ollama_error')}: {exc}")
    return {"summary": _strip_think(text) or "No summary produced."}


_PROFILE_MAX_CHARS = 8000


async def _get_or_make_profile(session: AsyncSession, user_id: uuid.UUID):
    from app.database.models.security import KaiProfile
    row = (
        await session.execute(select(KaiProfile).where(KaiProfile.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = KaiProfile(user_id=user_id, content_text="", char_count=0)
        session.add(row)
        await session.flush()
    return row


def _profile_out(row) -> dict:
    return {
        "content_text": row.content_text, "char_count": row.char_count,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class ProfileBody(BaseModel):
    content: str = Field(default="", max_length=_PROFILE_MAX_CHARS)


class LearnBody(BaseModel):
    conversation_id: uuid.UUID


@router.get("/profile")
async def get_profile(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The operator profile KAI has learned/been given — how this operator works."""
    return _profile_out(await _get_or_make_profile(session, operator.id))


@router.put("/profile")
async def set_profile(
    body: ProfileBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await _get_or_make_profile(session, operator.id)
    row.content_text = (body.content or "")[:_PROFILE_MAX_CHARS]
    row.char_count = len(row.content_text)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _profile_out(row)


@router.post("/profile/learn")
async def learn_profile(
    body: LearnBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    provider: OllamaProvider = Depends(get_chat_provider),
) -> dict:
    """Use the model to extract durable facts about how the operator works from a
    conversation, MERGE them into the existing profile, and persist. This is how
    KAI 'learns to act like you' over time — grounded in real sessions."""
    conv = await _get_conv_or_404(body.conversation_id, operator.id, session)
    rows = (
        await session.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
        )
    ).scalars().all()
    lines = [f"{m.role.upper()}: {m.content.strip()[:1200]}" for m in rows if m.role in ("user", "assistant") and m.content]
    if not lines:
        return _profile_out(await _get_or_make_profile(session, operator.id))
    transcript = "\n".join(lines)
    if len(transcript) > 10000:
        transcript = transcript[-10000:]

    prof = await _get_or_make_profile(session, operator.id)
    if conv.model and conv.model != provider.model:
        try:
            provider = await resolve_provider_for_model(conv.model)
        except OllamaError:
            pass

    msgs = [
        AIMessage(role="system", content=(
            "You maintain an OPERATOR PROFILE: a concise, durable description of how a "
            "specific operator works and prefers things done — their recurring goals, "
            "targets/scope, preferred tools and workflow, tone, and explicit do's/don'ts. "
            "Given the EXISTING profile and a new session transcript, output an UPDATED "
            "profile that merges any durable new preferences. Rules: keep it short bullet "
            "points under ~1500 chars; only include stable preferences, NOT one-off task "
            "details; never include secrets, passwords, tokens, or PII of third parties; "
            "if nothing durable is new, return the existing profile unchanged. Output ONLY "
            "the profile text."
        )),
        AIMessage(role="user", content=(
            f"EXISTING PROFILE:\n{prof.content_text or '(empty)'}\n\n"
            f"NEW SESSION TRANSCRIPT:\n{transcript}\n\nReturn the updated profile."
        )),
    ]
    try:
        text = await provider.chat(msgs, params=GenParams())
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=f"{getattr(exc, 'code', 'ollama_error')}: {exc}")
    updated = _strip_think(text)[:_PROFILE_MAX_CHARS]
    if updated:
        prof.content_text = updated
        prof.char_count = len(updated)
        session.add(prof)
        await session.flush()
        await session.refresh(prof)
    return _profile_out(prof)


@router.patch("/conversations/{conv_id}")
async def patch_conversation(
    conv_id: uuid.UUID,
    body: PatchConversation,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _get_conv_or_404(conv_id, operator.id, session)
    if body.title is not None:
        conv.title = body.title[:200]
    if body.archived is not None:
        conv.archived = body.archived
    if body.model is not None and body.model.strip():
        conv.model = body.model.strip()[:200]
    session.add(conv)
    await session.flush()
    await session.refresh(conv)
    return _conv_out(conv)


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> None:
    conv = await _get_conv_or_404(conv_id, operator.id, session)
    await session.execute(delete(Message).where(Message.conversation_id == conv.id))
    await session.delete(conv)
    await session.flush()


# ───────────────────────── messages (streaming) ─────────────────────── #
async def _history(session: AsyncSession, conv_id: uuid.UUID) -> list[AIMessage]:
    rows = (
        await session.execute(
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.asc())
        )
    ).scalars().all()
    out: list[AIMessage] = []
    for m in rows:
        if m.role in ("user", "assistant") and m.content:
            out.append(AIMessage(role=m.role, content=m.content))
    return out


async def _drive_turn(
    run: chat_runs.ChatRun, *, operator_id: uuid.UUID, conv_id: uuid.UUID,
    history: list[AIMessage], use_tools: bool, auto_approve: bool, provider: OllamaProvider,
    requested_model: str | None = None, think: bool = False, mode: str = "auto",
) -> None:
    """Runs one turn to completion in the background, independent of any client.
    Frames are recorded on ``run``; the assistant message is always persisted.

    ``requested_model`` (the conversation's selected model) overrides the default
    provider's model for this turn when it differs — the turn then generates with
    exactly the model the operator picked, validated against what's installed."""
    answer_parts: list[str] = []
    tool_calls: list[dict] = []
    findings: list[dict] = []
    cancelled = False
    errored: str | None = None
    async with async_session_maker() as session:
        await run.publish(_sse("start", {"conversation_id": str(conv_id), "use_tools": use_tools}))

        # Bind this turn to the selected model, routed to whichever backend
        # (llama.cpp or Ollama) actually serves it.
        if requested_model and requested_model != provider.model:
            candidate = await resolve_provider_for_model(requested_model)
            try:
                installed = await candidate.list_models()
            except OllamaError:
                installed = []  # server unreachable now — let generation surface it
            if installed and not candidate._model_present(installed):
                msg = (f"Model '{requested_model}' is not available on the "
                       f"{candidate.name} backend. Installed: {', '.join(installed) or 'none'}.")
                await run.publish(_sse("error", {"code": "model_not_installed", "message": msg}))
                await run.publish(_sse("done", {"ok": False, "cancelled": False}))
                await run.finish()
                return
            provider = candidate

        async def approve_cb(proposal: dict) -> bool:
            # One pending approval at a time (tool calls run one per step).
            fut = run.request_approval(proposal)
            run.activity = f"awaiting approval: {proposal.get('operation', 'tool')}"
            return await fut

        try:
            if use_tools:
                driver = orchestrator.run_multi if mode == "multi" else orchestrator.run_turn
                turn = driver(
                    session, user_id=operator_id, conversation_id=conv_id,
                    history=history, provider=provider,
                    approve=None if auto_approve else approve_cb,
                    # confirm is ALWAYS available (even in auto-run) so pip/go/github
                    # installs can prompt the operator to confirm now-vs-later.
                    confirm=approve_cb,
                    think=think,
                )
                async for kind, ev in _with_heartbeat(turn):
                    if kind == "ping":
                        await run.publish(_HEARTBEAT)
                        continue
                    if ev["type"] == "thinking":
                        run.activity = "thinking"
                    elif ev["type"] == "tool_call":
                        run.activity = f"running {ev.get('operation', 'tool')}"
                    elif ev["type"] == "token":
                        run.activity = "writing"
                    if ev["type"] == "final":
                        answer_parts = [ev["answer"]]
                        tool_calls = ev.get("tool_calls", [])
                        findings = ev.get("findings", [])
                        await run.publish(_sse("message", {"content": ev["answer"]}))
                    elif ev["type"] == "error":
                        errored = ev.get("message")
                    await run.publish(_sse(ev["type"], ev))
            else:
                async for kind, chunk in _with_heartbeat(provider.chat_stream(history, params=GenParams())):
                    if kind == "ping":
                        await run.publish(_HEARTBEAT)
                        continue
                    run.activity = "writing"
                    answer_parts.append(chunk)
                    await run.publish(_sse("token", {"text": chunk}))
        except asyncio.CancelledError:
            cancelled = True
            errored = "stopped by operator"
        except OllamaError as exc:
            errored = f"{getattr(exc, 'code', 'ollama_error')}: {exc}"
            await run.publish(_sse("error", {"code": getattr(exc, "code", "ollama_error"), "message": str(exc)}))
        except Exception as exc:  # noqa: BLE001
            errored = str(exc) or "failed"
            await run.publish(_sse("error", {"code": "internal", "message": errored}))
        finally:
            content = "".join(answer_parts).strip()
            if content or errored:
                asst = Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=content or f"[no output: {errored}]",
                    tool_calls=tool_calls or None,
                    tool_results=None,
                    meta={"cancelled": cancelled, "error": errored,
                          "findings": findings, "model": provider.model},
                )
                session.add(asst)
                conv = await session.get(Conversation, conv_id)
                if conv is not None:
                    session.add(conv)  # bump updated_at
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
            await run.publish(_sse("done", {"ok": errored is None, "cancelled": cancelled}))
            await run.finish()


@router.post("/conversations/{conv_id}/messages")
async def post_message(
    conv_id: uuid.UUID,
    body: NewMessage,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    provider: OllamaProvider = Depends(get_chat_provider),
) -> StreamingResponse:
    conv = await _get_conv_or_404(conv_id, operator.id, session)
    run = chat_runs.start_run(conv.id, operator.id)
    if run is None:
        raise HTTPException(status_code=409, detail="KAI is already working on this conversation")

    user_msg = Message(conversation_id=conv.id, role="user", content=body.content)
    session.add(user_msg)
    # Name the conversation from the first user turn.
    if conv.title in ("New conversation", "", None):
        conv.title = body.content.strip().splitlines()[0][:80]
        session.add(conv)
    await session.flush()
    history = await _history(session, conv.id)
    await session.commit()

    # The turn runs server-side; the client connection only tails its frames.
    run.task = asyncio.create_task(_drive_turn(
        run, operator_id=operator.id, conv_id=conv.id, history=history,
        use_tools=body.use_tools, auto_approve=body.auto_approve, provider=provider,
        requested_model=conv.model, think=body.think, mode=body.mode,
    ))
    return StreamingResponse(run.tail(0), media_type="text/event-stream")


@router.get("/conversations/{conv_id}/stream")
async def attach_stream(
    conv_id: uuid.UUID,
    start: int = 0,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
):
    """Re-attach to a running (or just-finished) turn after navigating away."""
    await _get_conv_or_404(conv_id, operator.id, session)
    run = chat_runs.get_run(conv_id)
    if run is None or run.user_id != operator.id:
        return Response(status_code=204)
    return StreamingResponse(run.tail(start), media_type="text/event-stream")


class ApprovalBody(BaseModel):
    approved: bool


@router.post("/conversations/{conv_id}/approve")
async def approve_tool_call(
    conv_id: uuid.UUID,
    body: ApprovalBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The operator's Run/Skip click on a proposed tool call."""
    await _get_conv_or_404(conv_id, operator.id, session)
    run = chat_runs.get_run(conv_id)
    if run is None or run.user_id != operator.id:
        raise HTTPException(status_code=404, detail="no_active_turn")
    ok = run.decide(body.approved)
    if not ok:
        raise HTTPException(status_code=409, detail="nothing_awaiting_approval")
    return {"ok": True, "approved": body.approved}


@router.post("/conversations/{conv_id}/cancel")
async def cancel_run(
    conv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Cancel by the run's ownership alone — do NOT require the conversation to
    # still exist in the DB, so a zombie/hung run (deleted conversation, or a
    # task that won't unwind) can always be stopped.
    run = chat_runs.get_run(conv_id)
    if run is None or run.user_id != operator.id or not run.running:
        return {"cancelled": False}
    if run.task is not None:
        run.task.cancel()
    # Mark it finished even if the task is stuck/dead, so it leaves the active
    # list immediately and the operator sees it stopped.
    await run.finish()
    return {"cancelled": True}


@router.get("/active")
async def active(operator: User = Depends(get_current_operator)) -> list[dict]:
    """Turns KAI is working on right now (drives the global activity indicator)."""
    return [
        {"conversation_id": str(r.conversation_id), "activity": r.activity,
         "started_at": r.started_at, "seconds": int(time.time() - r.started_at)}
        for r in chat_runs.active_runs(operator.id)
    ]
