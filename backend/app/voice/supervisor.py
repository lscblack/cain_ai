"""Starts and talks to model worker processes.

One worker per environment, started on demand and stopped when idle, so large models
are never held in memory simultaneously without a reason.
"""
from __future__ import annotations

import asyncio
import itertools
import os
import time
from pathlib import Path
from typing import Awaitable, Callable

from app.core.logging import get_logger
from app.voice.workers import _frames

log = get_logger("kai.voice.worker")

WORKERS_DIR = Path(__file__).resolve().parent / "workers"
_STREAM_LIMIT = 64 * 1024 * 1024


class WorkerFailure(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


EventHandler = Callable[[dict], Awaitable[None] | None]


class WorkerProcess:
    def __init__(self, name: str, python: Path, script: str, *, env: dict[str, str] | None = None,
                 args: list[str] | None = None, cwd: Path | None = None) -> None:
        self.name = name
        self.python = python
        self.script = WORKERS_DIR / script
        self.env = env or {}
        self.args = args or []
        self.cwd = cwd
        self._proc: asyncio.subprocess.Process | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: dict[int, EventHandler] = {}
        self._start_lock = asyncio.Lock()
        self._reader: asyncio.Task | None = None
        self._stderr: asyncio.Task | None = None
        self._tail: list[str] = []
        self.last_used = time.monotonic()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self, timeout: float = 120.0) -> None:
        async with self._start_lock:
            if self.running:
                return
            if not self.python.exists():
                raise WorkerFailure("environment_missing", f"{self.python} does not exist")
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false",
                   "HF_HUB_DISABLE_TELEMETRY": "1", **self.env}
            self._proc = await asyncio.create_subprocess_exec(
                str(self.python), "-u", str(self.script), *self.args,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env, limit=_STREAM_LIMIT,
                cwd=str(self.cwd) if self.cwd else None,
            )
            ready: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[0] = ready
            self._reader = asyncio.create_task(self._read_loop(self._proc))
            self._stderr = asyncio.create_task(self._drain_stderr(self._proc))
            try:
                await asyncio.wait_for(ready, timeout)
            except asyncio.TimeoutError as exc:
                await self.stop()
                raise WorkerFailure("worker_start_timeout", f"{self.name} did not start") from exc
            log.info("voice worker %s started pid=%s", self.name, self._proc.pid)

    async def request(self, op: str, args: dict | None = None, payload: bytes = b"", *,
                      on_event: EventHandler | None = None, timeout: float | None = None,
                      request_id: int | None = None) -> tuple[dict, bytes]:
        await self.start()
        assert self._proc is not None and self._proc.stdin is not None
        rid = request_id if request_id is not None else next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        if on_event:
            self._handlers[rid] = on_event
        self.last_used = time.monotonic()
        try:
            self._proc.stdin.write(_frames.encode({"id": rid, "op": op, "args": args or {}}, payload))
            await self._proc.stdin.drain()
            return await asyncio.wait_for(fut, timeout)
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise WorkerFailure("worker_crashed", self._failure_text()) from exc
        finally:
            self._pending.pop(rid, None)
            self._handlers.pop(rid, None)
            self.last_used = time.monotonic()

    def new_request_id(self) -> int:
        return next(self._ids)

    def cancel(self, request_id: int) -> None:
        if self.running and self._proc and self._proc.stdin:
            self._proc.stdin.write(_frames.encode({"op": "cancel", "target": request_id}))

    @property
    def busy(self) -> bool:
        return any(rid != 0 for rid in self._pending)

    async def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        if proc.returncode is None:
            if proc.stdin:
                proc.stdin.close()  # EOF: the worker's reader ends its loop
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        log.info("voice worker %s stopped", self.name)

    def _failure_text(self) -> str:
        return " | ".join(self._tail[-5:])[-1500:] or "worker exited"

    async def _read_loop(self, proc: asyncio.subprocess.Process) -> None:
        stream = proc.stdout
        assert stream is not None
        try:
            while True:
                prefix = await stream.readexactly(_frames.PREFIX_SIZE)
                header_len, payload_len = _frames.parse_prefix(prefix)
                raw = await stream.readexactly(header_len)
                payload = await stream.readexactly(payload_len) if payload_len else b""
                import json

                header = json.loads(raw)
                rid = header.get("id", 0)
                if header.get("event"):
                    if header.get("ready"):
                        fut = self._pending.pop(0, None)
                        if fut and not fut.done():
                            fut.set_result(True)
                        continue
                    handler = self._handlers.get(rid)
                    if handler:
                        res = handler(header)
                        if asyncio.iscoroutine(res):
                            asyncio.create_task(res)
                    continue
                fut = self._pending.get(rid)
                if fut is None or fut.done():
                    continue
                if header.get("ok"):
                    fut.set_result((header.get("result") or {}, payload))
                else:
                    fut.set_exception(WorkerFailure(header.get("code", "inference_failed"),
                                                    header.get("error", "")))
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("voice worker %s protocol failure", self.name)
        finally:
            await proc.wait()
            await asyncio.sleep(0.05)  # let the stderr drain record why it died
            err = WorkerFailure("worker_crashed", self._failure_text())
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(err)
            self._pending.clear()
            self._handlers.clear()
            if self._proc is proc:
                self._proc = None
            log.info("voice worker %s exited rc=%s", self.name, proc.returncode)

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            text = line.decode(errors="replace").rstrip()
            if text:
                self._tail = (self._tail + [text])[-40:]
                log.debug("[%s] %s", self.name, text[:400])
