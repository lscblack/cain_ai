"""Face intelligence endpoints: status, detect, compare, 1:N search.

Uses the InsightFace engine when available; otherwise returns 503
'face_engine_unavailable' rather than inventing results.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.database.models.face import Face
from app.database.models.user import User
from app.database.repositories.face_repo import FaceRepository
from app.database.session import get_session
from app.intelligence.face.engine import FaceEngine
from app.intelligence.face.crops import crop_path, has_crop, save_crop
from app.intelligence.face.service import detect_and_embed_async, get_face_engine
from app.intelligence.face.similarity import (
    POSSIBLE,
    band_for_similarity,
    cosine_similarity,
    is_match,
)
from app.intelligence.face.vector_index import rank_by_cosine

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
    faces = await detect_and_embed_async(engine, data)

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
            await session.flush()
            save_crop(data, f.bbox, str(rec.id))  # thumbnail for the UI scanner/results
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
    a = await detect_and_embed_async(engine, await _read_image(file_a))
    b = await detect_and_embed_async(engine, await _read_image(file_b))
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
    faces = await detect_and_embed_async(engine, await _read_image(file))
    if not faces:
        return {"query_face": None, "matches": [], "detail": "no_face_detected_in_query"}

    query = faces[0].embedding
    corpus = await FaceRepository(session).list_with_embeddings(investigation_id=investigation_id)
    by_id = {str(rec.id): rec for rec in corpus}

    ranked = rank_by_cosine(
        query, [(str(rec.id), rec.embedding) for rec in corpus], floor=POSSIBLE
    )
    scored = []
    for face_id, score in ranked:
        rec = by_id[face_id]
        band = band_for_similarity(score)
        scored.append(
            {
                "face_id": face_id,
                "investigation_id": str(rec.investigation_id) if rec.investigation_id else None,
                "source_url": rec.source_url,
                "image_hash": rec.image_hash,
                "bbox": rec.bbox,
                "quality": rec.quality,
                "similarity": round(score, 4),
                "similarity_pct": round(score * 100, 1),
                "band": band.value if band else "no_match",
                "crop_url": f"/intelligence/face/crop/{face_id}" if has_crop(face_id) else None,
                "page_title": (rec.extra or {}).get("page_title"),
                "caption": (rec.extra or {}).get("caption"),
                "names": (rec.extra or {}).get("names") or [],
                "image_url": (rec.extra or {}).get("image_url"),
            }
        )
    return {
        "query_face": faces[0].to_dict(),
        "indexed_faces": len(corpus),
        "matches": scored[: max(1, min(top_k, 100))],
        "note": (
            "Ranked by facial similarity to the query. A high score is a potential match "
            "to observe, never a confirmed identity."
        ),
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/search/stream")
async def search_stream(
    file: UploadFile = File(...),
    investigation_id: uuid.UUID | None = Form(default=None),
    top_k: int = Form(default=20),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    engine: FaceEngine = Depends(engine_dep),
) -> StreamingResponse:
    """Stream face-search progress as Server-Sent Events."""
    if not engine.available():
        raise HTTPException(status_code=503, detail="face_engine_unavailable")
    data = await _read_image(file)

    async def gen() -> AsyncGenerator[str, None]:
        yield _sse("stage", {"name": "image_received", "bytes": len(data)})
        try:
            faces = await detect_and_embed_async(engine, data)
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"detail": str(exc)})
            return
        yield _sse("stage", {"name": "faces_detected", "count": len(faces)})
        if not faces:
            yield _sse("result", {"query_face": None, "matches": [], "detail": "no_face_detected"})
            return
        query = faces[0].embedding
        yield _sse("stage", {"name": "embedding_ready", "dim": len(query)})

        corpus = await FaceRepository(session).list_with_embeddings(
            investigation_id=investigation_id
        )
        yield _sse("stage", {"name": "comparing", "indexed": len(corpus)})

        scored = []
        for i, rec in enumerate(corpus):
            score = cosine_similarity(query, rec.embedding)
            if is_match(score):
                band = band_for_similarity(score)
                scored.append(
                    {
                        "face_id": str(rec.id),
                        "investigation_id": str(rec.investigation_id) if rec.investigation_id else None,
                        "source_url": rec.source_url,
                        "image_hash": rec.image_hash,
                        "similarity": round(score, 4),
                        "similarity_pct": round(score * 100, 1),
                        "band": band.value if band else "no_match",
                        "crop_url": f"/intelligence/face/crop/{rec.id}" if has_crop(str(rec.id)) else None,
                        "page_title": (rec.extra or {}).get("page_title"),
                        "caption": (rec.extra or {}).get("caption"),
                        "names": (rec.extra or {}).get("names") or [],
                        "image_url": (rec.extra or {}).get("image_url"),
                    }
                )
            if corpus and i % 50 == 0:
                yield _sse("progress", {"scanned": i + 1, "total": len(corpus)})
        yield _sse("stage", {"name": "ranking", "candidates": len(scored)})
        scored.sort(key=lambda m: m["similarity"], reverse=True)
        yield _sse(
            "result",
            {
                "query_face": faces[0].to_dict(),
                "indexed_faces": len(corpus),
                "matches": scored[: max(1, min(top_k, 100))],
            },
        )

    return StreamingResponse(gen(), media_type="text/event-stream")


async def _download_image(url: str) -> bytes | None:
    """SSRF-guarded image download for discovery (size/type capped)."""
    import httpx
    from app.core.net import UnsafeUrlError, validate_public_url

    try:
        validate_public_url(url)
    except UnsafeUrlError:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "KAI-OSINT/0.1"})
            if resp.status_code != 200:
                return None
            ctype = resp.headers.get("content-type", "").split(";")[0].strip()
            if ctype not in _ALLOWED:
                return None
            data = resp.content
            if not data or len(data) > _MAX_BYTES:
                return None
            return data
    except Exception:
        return None


@router.post("/discover")
async def discover(
    file: UploadFile = File(...),
    query_image_url: str | None = Form(default=None),
    operator: User = Depends(get_current_operator),
    engine: FaceEngine = Depends(engine_dep),
) -> dict:
    """Global discovery (Mode A): query configured reverse-image providers, then
    download + verify + dedupe + rank candidates locally. Returns UNAVAILABLE
    when no reverse-image provider is configured."""
    _require_engine(engine)
    from app.intelligence.face.discover import discover_faces
    from app.providers.registry import registry

    providers = [p for p in registry.by_type("reverse_image") if getattr(p, "enabled", False)]
    if not providers:
        return {
            "available": False,
            "detail": "no_reverse_image_providers_configured",
            "hint": "Set SERPAPI_API_KEY (or add another adapter) and enable it in Power Up.",
        }

    data = await _read_image(file)
    candidates: list[dict] = []
    for p in providers:
        try:
            candidates.extend(await p.search({"image_url": query_image_url}))
        except Exception:
            continue

    result = await discover_faces(data, candidates, engine=engine, image_fetch=_download_image)
    return {"available": True, **result.to_dict()}


@router.get("/crop/{face_id}")
async def face_crop(
    face_id: str,
    operator: User = Depends(get_current_operator),
):
    """Serve a stored face-crop thumbnail."""
    from fastapi.responses import FileResponse

    path = crop_path(face_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="crop_not_found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/index-sample")
async def index_sample(
    limit: int = 48,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Recent indexed faces that have a crop — fuels the UI scanning animation."""
    from sqlalchemy import desc, select as _select
    from app.database.models.face import Face as _Face

    rows = (
        await session.execute(_select(_Face).order_by(desc(_Face.created_at)).limit(max(1, min(limit, 200))))
    ).scalars().all()
    samples = [
        {"face_id": str(r.id), "crop_url": f"/intelligence/face/crop/{r.id}", "source_url": r.source_url}
        for r in rows
        if has_crop(str(r.id))
    ]
    return {"samples": samples, "count": len(samples)}


@router.get("/index-list")
async def index_list(
    limit: int = 60,
    offset: int = 0,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Browse all indexed faces (available faces) with crop thumbnails + provenance."""
    from sqlalchemy import desc, func, select as _select
    from app.database.models.face import Face as _Face

    total = int((await session.execute(_select(func.count()).select_from(_Face))).scalar_one())
    rows = (
        await session.execute(
            _select(_Face).order_by(desc(_Face.created_at)).limit(max(1, min(limit, 200))).offset(max(0, offset))
        )
    ).scalars().all()
    faces = [
        {
            "face_id": str(r.id),
            "crop_url": f"/intelligence/face/crop/{r.id}" if has_crop(str(r.id)) else None,
            "source_url": r.source_url,
            "investigation_id": str(r.investigation_id) if r.investigation_id else None,
            "quality": r.quality,
            "model": r.model,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "platform": (r.extra or {}).get("platform"),
            "page_title": (r.extra or {}).get("page_title"),
            "caption": (r.extra or {}).get("caption"),
            "names": (r.extra or {}).get("names") or [],
            "image_url": (r.extra or {}).get("image_url"),
        }
        for r in rows
    ]
    return {"total": total, "limit": limit, "offset": offset, "faces": faces}


@router.post("/dedupe")
async def dedupe_faces(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Remove near-identical faces within the same source (keeps highest quality).
    New crawls dedupe automatically; this cleans an index built before that."""
    from urllib.parse import urlsplit
    from sqlalchemy import delete as _delete, desc, select as _select
    from app.database.models.face import Face as _Face
    from app.intelligence.face.similarity import DEDUP_THRESHOLD
    from app.intelligence.face.vector_index import max_similarity

    rows = (await session.execute(_select(_Face).order_by(desc(_Face.quality)))).scalars().all()

    def _host(url: str | None) -> str:
        if not url:
            return "none"
        try:
            return urlsplit(url).hostname or url
        except Exception:
            return url

    kept: dict[str, list[list[float]]] = {}
    remove_ids: list = []
    removed_crops: list[str] = []
    for r in rows:
        if not r.embedding:
            continue
        h = _host(r.source_url)
        bucket = kept.setdefault(h, [])
        if max_similarity(list(r.embedding), bucket) >= DEDUP_THRESHOLD:
            remove_ids.append(r.id)
            removed_crops.append(str(r.id))
        else:
            bucket.append(list(r.embedding))

    if remove_ids:
        await session.execute(_delete(_Face).where(_Face.id.in_(remove_ids)))
        await session.flush()
        for fid in removed_crops:
            try:
                p = crop_path(fid)
                if p.exists():
                    p.unlink()
            except Exception:
                pass
    return {"removed": len(remove_ids), "remaining": len(rows) - len(remove_ids)}
