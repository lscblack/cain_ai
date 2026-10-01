"""Face engine accessor (lazy singleton)."""
from __future__ import annotations

from app.intelligence.face.engine import FaceEngine
from app.intelligence.face.insightface_engine import InsightFaceEngine

_engine: FaceEngine | None = None


def get_face_engine() -> FaceEngine:
    global _engine
    if _engine is None:
        _engine = InsightFaceEngine()
    return _engine
