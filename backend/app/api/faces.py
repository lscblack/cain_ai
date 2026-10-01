"""Face intelligence endpoints: status, detect, compare, 1:N search.

Uses the InsightFace engine when available; otherwise returns 503
'face_engine_unavailable' rather than inventing results.
"""
from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.database.models.face import Face
from app.database.models.user import User
from app.database.repositories.face_repo import FaceRepository
from app.database.session import get_session
from app.intelligence.face.engine import FaceEngine
from app.intelligence.face.service import get_face_engine
from app.intelligence.face.similarity import band_for_similarity, cosine_similarity, is_match

router = APIRouter(prefix="/intelligence/face", tags=["face"])

_MAX_BYTES = 12 * 1024 * 1024  # 12 MB upload cap
_ALLOWED = {"image/jpeg", "image/png", "image/webp", "image/bmp"}


def engine_dep() -> FaceEngine:
    return get_face_engine()


def _require_engine(engine: FaceEngine) -> None:
    if not engine.available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="face_engine_unavailable"
        )


async def _read_image(file: UploadFile) -> bytes:
    if file.content_type not in _ALLOWED:
        raise HTTPException(status_code=415, detail="unsupported_image_type")
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="empty_file")
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="image_too_large")
    return data


@router.get("/status")
async def face_status(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    engine: FaceEngine = Depends(engine_dep),
) -> dict:
    available = engine.available()
    return {
        "available": available,
        "model": engine.model_name,
        "model_version": engine.model_version,
        "embedding_dim": engine.embedding_dim,
        "indexed_faces": await FaceRepository(session).count(),
    }


@router.post("/detect")
async def detect(
    file: UploadFile = File(...),
    investigation_id: uuid.UUID | None = Form(default=None),
    source_url: str | None = Form(default=None),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    engine: FaceEngine = Depends(engine_dep),
) -> dict:
    _require_engine(engine)
    data = await _read_image(file)
    image_hash = hashlib.sha256(data).hexdigest()
    faces = engine.detect_and_embed(data)

    stored_ids: list[str] = []
    repo = FaceRepository(session)
    if investigation_id is not None:
        for f in faces:
            crop_hash = hashlib.sha256(
                (image_hash + ":" + ",".join(str(b) for b in f.bbox)).encode()
            ).hexdigest()
            rec = await repo.add(
                Face(
                    investigation_id=investigation_id,
                    source_url=source_url,
                    image_hash=image_hash,
                    face_crop_hash=crop_hash,
                    bbox=f.bbox,
                    det_score=f.det_score,
                    quality=f.quality,
                    model=engine.model_name,
                    model_version=engine.model_version,
                    embedding_dim=len(f.embedding),
                    embedding=f.embedding,
                    extra=f.extra,
                )
            )
            stored_ids.append(str(rec.id))
        await session.flush()

    return {
        "image_hash": image_hash,
        "faces_detected": len(faces),
        "faces": [f.to_dict() for f in faces],
        "stored_face_ids": stored_ids,
    }


@router.post("/compare")
async def compare(
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    operator: User = Depends(get_current_operator),
    engine: FaceEngine = Depends(engine_dep),
) -> dict:
    _require_engine(engine)
    a = engine.detect_and_embed(await _read_image(file_a))
    b = engine.detect_and_embed(await _read_image(file_b))
    if not a or not b:
        return {
            "comparable": False,
            "detail": "no_face_detected_in_one_or_both",
            "faces_a": len(a),
            "faces_b": len(b),
        }
    score = cosine_similarity(a[0].embedding, b[0].embedding)
    band = band_for_similarity(score)
    return {
        "comparable": True,
        "similarity": round(score, 4),
        "similarity_pct": round(max(score, 0.0) * 100, 1),
        "band": band.value if band else "no_match",
        "note": "Similarity between two faces. Not an identity determination.",
    }


@router.post("/search")
async def search(
    file: UploadFile = File(...),
    investigation_id: uuid.UUID | None = Form(default=None),
    top_k: int = Form(default=20),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    engine: FaceEngine = Depends(engine_dep),
) -> dict:
    _require_engine(engine)
    faces = engine.detect_and_embed(await _read_image(file))
    if not faces:
        return {"query_face": None, "matches": [], "detail": "no_face_detected_in_query"}

    query = faces[0].embedding
    corpus = await FaceRepository(session).list_with_embeddings(investigation_id=investigation_id)

    scored = []
    for rec in corpus:
        score = cosine_similarity(query, rec.embedding)
        if not is_match(score):
            continue
        band = band_for_similarity(score)
        scored.append(
            {
                "face_id": str(rec.id),
                "investigation_id": str(rec.investigation_id) if rec.investigation_id else None,
                "source_url": rec.source_url,
                "image_hash": rec.image_hash,
                "bbox": rec.bbox,
                "quality": rec.quality,
                "similarity": round(score, 4),
                "similarity_pct": round(score * 100, 1),
                "band": band.value if band else "no_match",
            }
        )
    scored.sort(key=lambda m: m["similarity"], reverse=True)
    return {
        "query_face": faces[0].to_dict(),
        "indexed_faces": len(corpus),
        "matches": scored[: max(1, min(top_k, 100))],
        "note": (
            "Ranked by facial similarity to the query. A high score is a potential match "
            "to observe, never a confirmed identity."
        ),
    }
