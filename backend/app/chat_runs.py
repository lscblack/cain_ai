"""Server-side chat runs, decoupled from the HTTP connection.

A chat turn used to live and die with the SSE request: switching pages or
closing the tab dropped the connection and the turn was cancelled. A ``ChatRun``
instead runs as a background task and records every SSE frame; any number of
clients can tail it (and re-attach after navigating away or reloading), and the
finished assistant message is always persisted by the task itself.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

_KEEP_FINISHED_SECONDS = 300


@dataclass
class ChatRun:
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    frames: list[str] = field(default_factory=list)
    activity: str = "thinking"
    task: asyncio.Task | None = None
    _cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    # Operator approval gate (see /chat/conversations/{id}/approve): at most one
    # tool call is ever awaiting a decision at a time, since a turn runs tool
    # calls one at a time.
    pending_approval: dict | None = None
    _approval: asyncio.Future | None = None

    @property
    def running(self) -> bool:
        return self.finished_at is None

    async def publish(self, frame: str) -> None:
        async with self._cond:
            self.frames.append(frame)
            self._cond.notify_all()

    async def finish(self) -> None:
        async with self._cond:
            self.finished_at = time.time()
            self._cond.notify_all()
        if self._approval is not None and not self._approval.done():
            self._approval.set_result(False)  # don't leave a waiter hanging

    def request_approval(self, payload: dict) -> asyncio.Future:
        """Called by the orchestrator before running a tool. Returns a future the
        caller awaits; resolve it via :meth:`decide` (POST .../approve)."""
        fut = asyncio.get_event_loop().create_future()
        self.pending_approval = payload
        self._approval = fut
        return fut

    def decide(self, approved: bool) -> bool:
        """The operator's click. Returns False if nothing was actually pending
        (already decided, or the turn moved on / finished)."""
        if self._approval is None or self._approval.done():
            return False
        self._approval.set_result(approved)
        self.pending_approval = None
        return True

    async def tail(self, start: int = 0) -> AsyncIterator[str]:
        """Replay recorded frames from ``start`` then follow live until done."""
        i = max(0, start)
        while True:
            async with self._cond:
                while i >= len(self.frames) and self.running:
                    await self._cond.wait()
                batch = self.frames[i:]
                i = len(self.frames)
                finished = not self.running
            for f in batch:
                yield f
            if finished and i >= len(self.frames):
                return


_RUNS: dict[uuid.UUID, ChatRun] = {}


def _purge() -> None:
    now = time.time()
    for k, r in list(_RUNS.items()):
        if r.finished_at and now - r.finished_at > _KEEP_FINISHED_SECONDS:
            _RUNS.pop(k, None)


def get_run(conversation_id: uuid.UUID) -> ChatRun | None:
    _purge()
    return _RUNS.get(conversation_id)


def start_run(conversation_id: uuid.UUID, user_id: uuid.UUID) -> ChatRun | None:
    """Register a new run; None if this conversation is already generating."""
    _purge()
    cur = _RUNS.get(conversation_id)
    if cur is not None and cur.running:
        return None
    run = ChatRun(conversation_id=conversation_id, user_id=user_id)
    _RUNS[conversation_id] = run
    return run


def active_runs(user_id: uuid.UUID) -> list[ChatRun]:
    _purge()
    return [r for r in _RUNS.values() if r.user_id == user_id and r.running]
