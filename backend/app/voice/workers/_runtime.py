"""Request loop shared by the model workers. Standard library only.

Requests are read on a thread so ``cancel`` is seen while an operation is running;
operations themselves run one at a time on the main thread, because a model is not
safe to call concurrently. stdout carries frames only: anything a library prints is
sent to stderr so it can never corrupt the protocol.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
from typing import Callable

import _frames


class Cancelled(Exception):
    pass


class WorkerError(Exception):
    """An expected failure, reported to the backend with a stable code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class Context:
    def __init__(self, emit: Callable[[dict, bytes], None]) -> None:
        self._emit = emit
        self.request_id = 0
        self.cancel = threading.Event()

    def event(self, **fields) -> None:
        self._emit({"id": self.request_id, "event": True, **fields}, b"")

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


def serve(ops: dict[str, Callable[[Context, dict, bytes], tuple[dict, bytes] | dict]]) -> None:
    # Keep the real stdout for frames, then point fd 1 at stderr for everyone else.
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    stdin = os.fdopen(os.dup(0), "rb", buffering=1024 * 1024)

    lock = threading.Lock()

    def emit(header: dict, payload: bytes = b"") -> None:
        data = _frames.encode(header, payload)
        with lock:
            out.write(data)

    requests: queue.Queue = queue.Queue()
    ctx = Context(emit)

    def reader() -> None:
        try:
            while True:
                frame = _frames.read_blocking(stdin)
                if frame is None:
                    break
                if frame[0].get("op") == "cancel":
                    # Only cancels the named request, so a late cancel cannot hit the next one.
                    if frame[0].get("target") == ctx.request_id:
                        ctx.cancel.set()
                    continue
                requests.put(frame)
        finally:
            requests.put(None)  # backend went away: exit rather than linger holding memory

    threading.Thread(target=reader, daemon=True).start()
    emit({"id": 0, "event": True, "ready": True, "pid": os.getpid()})

    while True:
        frame = requests.get()
        if frame is None:
            return
        header, payload = frame
        ctx.request_id = header.get("id", 0)
        ctx.cancel.clear()
        response: dict
        body = b""
        try:
            fn = ops.get(header.get("op", ""))
            if fn is None:
                raise WorkerError("unknown_op", str(header.get("op")))
            result = fn(ctx, header.get("args") or {}, payload)
            response, body = result if isinstance(result, tuple) else (result, b"")
            response = {"ok": True, "result": response}
        except Cancelled:
            response = {"ok": False, "code": "cancelled", "error": "cancelled"}
        except WorkerError as exc:
            response = {"ok": False, "code": exc.code, "error": str(exc)}
        except MemoryError as exc:
            response = {"ok": False, "code": "out_of_memory", "error": str(exc) or "out of memory"}
        except Exception as exc:  # noqa: BLE001 — must report, never kill the loop
            traceback.print_exc()
            low = str(exc).lower()
            code = "out_of_memory" if "out of memory" in low else "inference_failed"
            response = {"ok": False, "code": code, "error": f"{type(exc).__name__}: {exc}"[:2000]}
        emit({"id": ctx.request_id, **response}, body)
