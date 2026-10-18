"""Chat API: conversations, messages, model status, and streaming turns.

Streaming uses Server-Sent Events (same ``event:``/``data:`` framing as the face
search stream). A turn can either be a plain streamed completion or a tool-using
orchestration (the default), chosen per message via ``use_tools``.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ollama import GenParams, OllamaError, OllamaProvider, get_ollama_provider
from app.ai.router import AIMessage
from app.api.deps import get_current_operator
from app.database.models.conversation import Conversation, Message
from app.database.models.user import User
from app.database.session import get_session
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


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    use_tools: bool = True


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
    return (await provider.status()).to_dict()


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


@router.post("/conversations/{conv_id}/messages")
async def post_message(
    conv_id: uuid.UUID,
    body: NewMessage,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    provider: OllamaProvider = Depends(get_chat_provider),
) -> StreamingResponse:
    conv = await _get_conv_or_404(conv_id, operator.id, session)

    user_msg = Message(conversation_id=conv.id, role="user", content=body.content)
    session.add(user_msg)
    # Name the conversation from the first user turn.
    if conv.title in ("New conversation", "", None):
        conv.title = body.content.strip().splitlines()[0][:80]
        session.add(conv)
    await session.flush()
    history = await _history(session, conv.id)
    await session.commit()

    async def gen() -> AsyncGenerator[str, None]:
        answer_parts: list[str] = []
        tool_calls: list[dict] = []
        findings: list[dict] = []
        cancelled = False
        errored: str | None = None
        yield _sse("start", {"conversation_id": str(conv.id), "use_tools": body.use_tools})
        try:
            if body.use_tools:
                turn = orchestrator.run_turn(
                    session, user_id=operator.id, conversation_id=conv.id,
                    history=history, provider=provider,
                )
                async for kind, ev in _with_heartbeat(turn):
                    if kind == "ping":
                        yield _HEARTBEAT
                        continue
                    if ev["type"] == "final":
                        answer_parts = [ev["answer"]]
                        tool_calls = ev.get("tool_calls", [])
                        findings = ev.get("findings", [])
                        yield _sse("message", {"content": ev["answer"]})
                    elif ev["type"] == "error":
                        errored = ev.get("message")
                    yield _sse(ev["type"], ev)
            else:
                async for kind, chunk in _with_heartbeat(provider.chat_stream(history, params=GenParams())):
                    if kind == "ping":
                        yield _HEARTBEAT
                        continue
                    answer_parts.append(chunk)
                    yield _sse("token", {"text": chunk})
        except OllamaError as exc:
            errored = f"{getattr(exc, 'code', 'ollama_error')}: {exc}"
            yield _sse("error", {"code": getattr(exc, "code", "ollama_error"), "message": str(exc)})
        except Exception as exc:  # noqa: BLE001  (client disconnect etc.)
            cancelled = True
            errored = str(exc) or "cancelled"
        finally:
            content = "".join(answer_parts).strip()
            if content or errored:
                asst = Message(
                    conversation_id=conv.id,
                    role="assistant",
                    content=content or f"[no output: {errored}]",
                    tool_calls=tool_calls or None,
                    tool_results=None,
                    meta={"cancelled": cancelled, "error": errored,
                          "findings": findings, "model": provider.model},
                )
                session.add(asst)
                session.add(conv)  # bump updated_at
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
            if not cancelled:
                yield _sse("done", {"ok": errored is None})

    return StreamingResponse(gen(), media_type="text/event-stream")
