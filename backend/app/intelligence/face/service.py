"""Face engine accessor (lazy singleton) + non-blocking inference helper."""
from __future__ import annotations

import asyncio
import os
import threading

import anyio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.intelligence.face.engine import DetectedFace, FaceEngine
from app.intelligence.face.insightface_engine import InsightFaceEngine, cuda_is_usable

logger = get_logger("kai.face")

_engine: FaceEngine | None = None

# ONNX CPU inference is heavy and not thread-safe to run concurrently; serialize
# it so interactive searches and background crawls don't thrash the CPU, and run
# it in a worker thread so the async event loop (SSE progress, other requests)
# stays responsive.
_infer_lock = asyncio.Semaphore(1)
_niced_threads: set[int] = set()


def get_face_engine() -> FaceEngine:
    global _engine
    if _engine is None:
        _engine = InsightFaceEngine()
    return _engine


def _detect_niced(engine: FaceEngine, image_bytes: bytes) -> list[DetectedFace]:
    """Run detection on the worker thread, de-prioritised (CPU only).

    Lowering the inference thread's nice value keeps interactive API requests and
    other processes responsive while heavy CPU embedding runs in the background.
    GPU runs don't burn CPU, so skip the nice there.
    """
    nice = get_settings().face_infer_nice
    if nice and not cuda_is_usable():
        tid = threading.get_native_id()
        if tid not in _niced_threads:
            try:
                os.setpriority(os.PRIO_PROCESS, tid, nice)
                _niced_threads.add(tid)
            except (OSError, AttributeError, PermissionError) as exc:
                logger.debug("could not lower inference thread priority: %s", exc)
    return engine.detect_and_embed(image_bytes)


async def detect_and_embed_async(engine: FaceEngine, image_bytes: bytes) -> list[DetectedFace]:
    """Run face detection/embedding off the event loop, serialized and de-prioritised."""
    async with _infer_lock:
        return await anyio.to_thread.run_sync(_detect_niced, engine, image_bytes)
