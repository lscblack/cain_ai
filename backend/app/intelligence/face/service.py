"""Face engine accessor (lazy singleton) + non-blocking inference helper."""
from __future__ import annotations

import asyncio

import anyio

from app.intelligence.face.engine import DetectedFace, FaceEngine
from app.intelligence.face.insightface_engine import InsightFaceEngine

_engine: FaceEngine | None = None

# ONNX CPU inference is heavy and not thread-safe to run concurrently; serialize
# it so interactive searches and background crawls don't thrash the CPU, and run
# it in a worker thread so the async event loop (SSE progress, other requests)
# stays responsive.
_infer_lock = asyncio.Semaphore(1)


def get_face_engine() -> FaceEngine:
    global _engine
    if _engine is None:
        _engine = InsightFaceEngine()
    return _engine


async def detect_and_embed_async(engine: FaceEngine, image_bytes: bytes) -> list[DetectedFace]:
    """Run face detection/embedding off the event loop, serialized."""
    async with _infer_lock:
        return await anyio.to_thread.run_sync(engine.detect_and_embed, image_bytes)
