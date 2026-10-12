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
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.database.models.face import Face
from app.database.models.user import User
from app.database.repositories.face_repo import FaceRepository
from app.database.session import get_session
from app.intelligence.face.engine import FaceEngine
from app.intelligence.face.crops import crop_path, has_crop, save_crop
from app.intelligence.face.describe import describe_face
from app.intelligence.face.service import detect_and_embed_async, get_face_engine
from app.intelligence.face.similarity import (
    DEDUP_THRESHOLD,
    POSSIBLE,
    POTENTIAL_MATCH,
    STRONG,
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


def _match_record(rec: Face, score: float) -> dict:
    """Build the public match dict for one indexed face at a given similarity."""
    band = band_for_similarity(score)
    extra = rec.extra or {}
    return {
        "face_id": str(rec.id),
        "investigation_id": str(rec.investigation_id) if rec.investigation_id else None,
        "source_url": rec.source_url,
        "image_hash": rec.image_hash,
        "bbox": rec.bbox,
        "quality": rec.quality,
        "similarity": round(score, 4),
        "similarity_pct": round(score * 100, 1),
        "band": band.value if band else "no_match",
        "crop_url": f"/intelligence/face/crop/{rec.id}" if has_crop(str(rec.id)) else None,
        "page_title": extra.get("page_title"),
        "caption": extra.get("caption"),
        "context": extra.get("context"),
        "names": extra.get("names") or [],
        "emails": extra.get("emails") or [],
        "phones": extra.get("phones") or [],
        "usernames": extra.get("usernames") or [],
        "titles": extra.get("titles") or [],
        "orgs": extra.get("orgs") or [],
        "locations": extra.get("locations") or [],
        "image_url": extra.get("image_url"),
        "age": extra.get("age"),
        "sex": extra.get("sex"),
        "description": describe_face(rec.extra, rec.source_url),
    }


# One person photographed in different places still scores high against each
# other; group ranked matches whose embeddings are this close into one person.
GROUP_SAME_PERSON = 0.50  # cosine (== 50% in the UI); tunable


def _group_people(ranked: list, by_id: dict, *, top_k: int = 20) -> list[dict]:
    """Collapse ranked matches into distinct people so the same person seen on
    several pages shows once, with all their appearances (place/event) attached.
    """
    clusters: list[dict] = []
    for face_id, score in ranked:
        rec = by_id.get(face_id)
        if rec is None or not rec.embedding:
            continue
        placed = False
        for cl in clusters:
            if cosine_similarity(rec.embedding, cl["emb"]) >= GROUP_SAME_PERSON:
                cl["members"].append((rec, score))
                placed = True
                break
        if not placed:
            clusters.append({"emb": rec.embedding, "rep": rec, "rep_score": score,
                             "members": [(rec, score)]})

    fields = ("names", "emails", "phones", "usernames", "titles", "orgs", "locations")
    people: list[dict] = []
    for cl in clusters[:top_k]:
        rep, rep_score = cl["rep"], cl["rep_score"]  # first member = highest score
        agg: dict[str, list[str]] = {k: [] for k in fields}
        seen: dict[str, set] = {k: set() for k in fields}
        appearances = []
        for rec, score in cl["members"]:
            ex = rec.extra or {}
            for k in fields:
                for v in ex.get(k) or []:
                    s = str(v).strip()
                    if s and s.lower() not in seen[k]:
                        seen[k].add(s.lower())
                        agg[k].append(s)
            rid = str(rec.id)
            b = band_for_similarity(score)
            appearances.append({
                "face_id": rid,
                "crop_url": f"/intelligence/face/crop/{rid}" if has_crop(rid) else None,
                "image_url": ex.get("image_url"),
                "source_url": rec.source_url,
                "page_title": ex.get("page_title"),
                "caption": ex.get("caption"),
                "context": ex.get("context"),
                "similarity_pct": round(score * 100, 1),
                "band": b.value if b else "no_match",
            })
        rep_ex = rep.extra or {}
        rb = band_for_similarity(rep_score)
        people.append({
            "person_id": str(rep.id),
            "name": agg["names"][0] if agg["names"] else (rep_ex.get("page_title") or None),
            **agg,
            "age": rep_ex.get("age"),
            "sex": rep_ex.get("sex"),
            "similarity_pct": round(rep_score * 100, 1),
            "band": rb.value if rb else "no_match",
            "crop_url": f"/intelligence/face/crop/{rep.id}" if has_crop(str(rep.id)) else None,
            "appearance_count": len(appearances),
            "appearances": appearances,
            "contexts": list(dict.fromkeys(
                a["context"] for a in appearances if a.get("context")
            ))[:5],
            "description": describe_face(rep.extra, rep.source_url),
        })
    return people


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
        "faces": [f.to_dict(include_extra=True) for f in faces],
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
    face_index: int = Form(default=0),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    engine: FaceEngine = Depends(engine_dep),
) -> dict:
    _require_engine(engine)
    faces = await detect_and_embed_async(engine, await _read_image(file))
    if not faces:
        return {"query_face": None, "matches": [], "detail": "no_face_detected_in_query"}
    if face_index < 0 or face_index >= len(faces):
        return {
            "query_face": None,
            "matches": [],
            "faces_detected": len(faces),
            "detail": "face_index_out_of_range",
        }

    chosen = faces[face_index]
    corpus = await FaceRepository(session).list_with_embeddings(investigation_id=investigation_id)
    by_id = {str(rec.id): rec for rec in corpus}

    ranked = rank_by_cosine(
        chosen.embedding, [(str(rec.id), rec.embedding) for rec in corpus], floor=POSSIBLE
    )
    scored = [_match_record(by_id[face_id], score) for face_id, score in ranked]
    return {
        "query_face": chosen.to_dict(include_extra=True),
        "faces_detected": len(faces),
        "indexed_faces": len(corpus),
        "matches": scored[: max(1, min(top_k, 100))],
        # Grouped: same person across pages collapsed into one, with all their
        # appearances (place/event) attached — avoids duplicate people in results.
        "people": _group_people(ranked, by_id, top_k=max(1, min(top_k, 100))),
        "note": (
            "Ranked by facial similarity to the query. A high score is a potential match "
            "to observe, never a confirmed identity."
        ),
    }


class _BioRequest(BaseModel):
    name: str | None = None
    names: list[str] = []
    titles: list[str] = []
    orgs: list[str] = []
    locations: list[str] = []
    captions: list[str] = []
    contexts: list[str] = []
    sources: list[str] = []
    age: int | None = None
    sex: str | None = None


def _compose_bio_fallback(b: "_BioRequest") -> str:
    parts: list[str] = []
    who = b.name or (b.names[0] if b.names else "This subject")
    demo = " · ".join(x for x in [b.sex, f"~{b.age}y" if (b.age or 0) > 0 else None] if x)
    parts.append(f"{who}{(' (' + demo + ')') if demo else ''} — potential match, not a confirmed identity.")
    if b.titles or b.orgs:
        parts.append("Role: " + " / ".join([*b.titles[:2], *b.orgs[:2]]) + ".")
    if b.locations:
        parts.append("Seen in: " + ", ".join(b.locations[:4]) + ".")
    if len(b.sources) > 0:
        parts.append(f"Observed across {len(b.sources)} public source(s).")
    if b.captions:
        parts.append("Context: " + " ".join(b.captions[:2]))
    return " ".join(parts)


@router.post("/bio")
async def face_bio(body: _BioRequest, operator: User = Depends(get_current_operator)) -> dict:
    """AI-summarized bio for a grouped person, from public OSINT context only.
    Falls back to a composed summary when no AI provider is configured."""
    from app.ai.router import AIMessage, get_ai_provider

    provider = get_ai_provider()
    if provider is None or not provider.available():
        return {"available": False, "bio": _compose_bio_fallback(body), "model": None}

    context = {
        "name": body.name, "names": body.names, "titles": body.titles, "orgs": body.orgs,
        "locations": body.locations, "captions": body.captions,
        "what_sources_say": body.contexts, "sources": body.sources,
        "age": body.age, "sex": body.sex,
    }
    system = (
        "You are an OSINT analyst. Write a concise (3-5 sentence) neutral bio of a person "
        "from the PUBLIC data provided only. Do NOT invent facts not present. This is a "
        "potential facial-recognition match, so hedge: say 'appears to be' / 'potential', "
        "never assert a confirmed identity. No disclaimers beyond that hedging."
    )
    try:
        summary = await provider.chat(
            [AIMessage(role="system", content=system),
             AIMessage(role="user", content=json.dumps(context))]
        )
        return {"available": True, "bio": summary.strip(), "model": provider.name}
    except Exception:
        return {"available": False, "bio": _compose_bio_fallback(body), "model": None}


_VIDEO_ALLOWED = {"video/mp4", "video/webm", "video/quicktime"}
_VIDEO_MAX_BYTES = 50 * 1024 * 1024  # 50 MB upload cap
_VIDEO_FRAME_CAP = 30  # sample at most this many frames
_VIDEO_SAME_PERSON = 0.92  # cosine >= this = same person across frames (dedup)


@router.post("/search/video")
async def search_video(
    file: UploadFile = File(...),
    top_k: int = Form(default=5),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    engine: FaceEngine = Depends(engine_dep),
) -> dict:
    """1:N face search over a short uploaded video.

    Samples frames at ~1 fps (up to a cap), detects faces in each, dedupes the
    same person across frames, then searches each distinct person against the
    local index. Everything is ephemeral: the video is written to a temp file
    that is deleted before returning. Matches are potential leads, never a
    confirmed identity.
    """
    _require_engine(engine)
    # Accept by declared content-type OR by a known video file extension — some
    # mobile/multipart clients mislabel the part's content-type.
    _ext = (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    _video_ext = {"mp4", "webm", "mov", "qt", "m4v", "mkv"}
    if file.content_type not in _VIDEO_ALLOWED and _ext not in _video_ext:
        raise HTTPException(status_code=415, detail="unsupported_video_type")
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="empty_file")
    if len(data) > _VIDEO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="video_too_large")

    import os
    import tempfile

    import cv2

    suffix = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
    }.get(file.content_type, ".mp4")

    tmp_path: str | None = None
    detected = []  # all DetectedFace across sampled frames
    frames_sampled = 0
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)

        cap = cv2.VideoCapture(tmp_path)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            # sample ~1 frame per second; fall back to every frame if fps unknown
            step = int(round(fps)) if fps and fps >= 1.0 else 1
            frame_idx = 0
            while frames_sampled < _VIDEO_FRAME_CAP:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % step == 0:
                    ok_enc, buf = cv2.imencode(".jpg", frame)
                    if ok_enc:
                        detected.extend(
                            await detect_and_embed_async(engine, buf.tobytes())
                        )
                    frames_sampled += 1
                frame_idx += 1
        finally:
            cap.release()
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # Dedup faces across frames: one cluster per distinct person, keep the
    # highest-quality instance as the cluster representative.
    clusters: list[dict] = []
    for f in detected:
        placed = False
        for c in clusters:
            if cosine_similarity(f.embedding, c["rep"].embedding) >= _VIDEO_SAME_PERSON:
                c["frames_seen"] += 1
                if f.quality > c["rep"].quality:
                    c["rep"] = f
                placed = True
                break
        if not placed:
            clusters.append({"rep": f, "frames_seen": 1})

    corpus = await FaceRepository(session).list_with_embeddings(investigation_id=None)
    by_id = {str(rec.id): rec for rec in corpus}
    corpus_pairs = [(str(rec.id), rec.embedding) for rec in corpus]
    cap_k = max(1, min(top_k, 50))

    people = []
    for c in sorted(clusters, key=lambda x: x["rep"].quality, reverse=True):
        rep = c["rep"]
        ranked = rank_by_cosine(rep.embedding, corpus_pairs, floor=POSSIBLE)
        matches = [_match_record(by_id[fid], score) for fid, score in ranked[:cap_k]]
        people.append(
            {
                "age": (rep.extra or {}).get("age"),
                "sex": (rep.extra or {}).get("sex"),
                "quality": round(rep.quality, 4),
                "frames_seen": c["frames_seen"],
                "matches": matches,
            }
        )

    return {
        "frames_sampled": frames_sampled,
        "faces_found": len(people),
        "indexed_faces": len(corpus),
        "people": people,
        "note": (
            "Faces sampled from the video and ranked against the local index. A high "
            "score is a potential match to observe, never a confirmed identity."
        ),
    }


@router.post("/frame")
async def frame(
    file: UploadFile = File(...),
    investigation_id: uuid.UUID | None = Form(default=None),
    match: bool = Form(default=True),
    top_k: int = Form(default=3),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    engine: FaceEngine = Depends(engine_dep),
) -> dict:
    """Live single-frame analysis for the webcam view.

    Detects every face in the frame and returns per-face bbox/age/sex/quality.
    When ``match`` is set, each face's best hedged gallery match is attached.
    The frame itself is processed in memory and never persisted — only the
    explicit capture flow (``/detect`` with an investigation_id) stores faces.
    """
    _require_engine(engine)
    faces = await detect_and_embed_async(engine, await _read_image(file))

    corpus: list[Face] = []
    by_id: dict[str, Face] = {}
    if match and faces:
        corpus = await FaceRepository(session).list_with_embeddings(
            investigation_id=investigation_id
        )
        by_id = {str(rec.id): rec for rec in corpus}

    out = []
    for f in faces:
        entry = f.to_dict(include_extra=True)
        best = None
        if match and corpus:
            ranked = rank_by_cosine(
                f.embedding, [(str(rec.id), rec.embedding) for rec in corpus], floor=POSSIBLE
            )
            if ranked:
                top_id, top_score = ranked[0]
                best = _match_record(by_id[top_id], top_score)
        entry["match"] = best
        out.append(entry)

    return {
        "faces_detected": len(faces),
        "indexed_faces": len(corpus),
        "faces": out,
        "note": (
            "Live detection. Matches are potential, never confirmed identity. "
            "Frames are not stored."
        ),
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _search_stream_response(
    data: bytes,
    top_k: int,
    session: AsyncSession,
    engine: FaceEngine,
    investigation_id: uuid.UUID | None = None,
    face_index: int = 0,
) -> StreamingResponse:
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
        if face_index < 0 or face_index >= len(faces):
            yield _sse(
                "result",
                {"query_face": None, "matches": [], "detail": "face_index_out_of_range"},
            )
            return
        chosen = faces[face_index]
        query = chosen.embedding
        yield _sse("stage", {"name": "embedding_ready", "dim": len(query)})

        corpus = await FaceRepository(session).list_with_embeddings(
            investigation_id=investigation_id
        )
        yield _sse("stage", {"name": "comparing", "indexed": len(corpus)})

        scored = []
        for i, rec in enumerate(corpus):
            score = cosine_similarity(query, rec.embedding)
            if is_match(score):
                scored.append(_match_record(rec, score))
            if corpus and i % 50 == 0:
                yield _sse("progress", {"scanned": i + 1, "total": len(corpus)})
        yield _sse("stage", {"name": "ranking", "candidates": len(scored)})
        scored.sort(key=lambda m: m["similarity"], reverse=True)
        by_id = {str(r.id): r for r in corpus}
        ranked = [(m["face_id"], m["similarity"]) for m in scored]
        people = _group_people(ranked, by_id, top_k=max(1, min(top_k, 100)))
        yield _sse(
            "result",
            {
                "query_face": chosen.to_dict(include_extra=True),
                "faces_detected": len(faces),
                "indexed_faces": len(corpus),
                "matches": scored[: max(1, min(top_k, 100))],
                "people": people,
            },
        )

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/search/stream")
async def search_stream(
    file: UploadFile = File(...),
    investigation_id: uuid.UUID | None = Form(default=None),
    top_k: int = Form(default=20),
    face_index: int = Form(default=0),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    engine: FaceEngine = Depends(engine_dep),
) -> StreamingResponse:
    """Stream face-search progress for authenticated operators."""
    if not engine.available():
        raise HTTPException(status_code=503, detail="face_engine_unavailable")
    return await _search_stream_response(
        await _read_image(file), top_k, session, engine, investigation_id, face_index
    )


@router.post("/public/search/stream")
async def public_search_stream(
    file: UploadFile = File(...),
    top_k: int = Form(default=20),
    session: AsyncSession = Depends(get_session),
    engine: FaceEngine = Depends(engine_dep),
) -> StreamingResponse:
    """Public read-only face search used by the landing page."""
    if not engine.available():
        raise HTTPException(status_code=503, detail="face_engine_unavailable")
    return await _search_stream_response(await _read_image(file), top_k, session, engine)


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
            "emails": (r.extra or {}).get("emails") or [],
            "phones": (r.extra or {}).get("phones") or [],
            "usernames": (r.extra or {}).get("usernames") or [],
            "image_url": (r.extra or {}).get("image_url"),
            "age": (r.extra or {}).get("age"),
            "sex": (r.extra or {}).get("sex"),
            "description": describe_face(r.extra, r.source_url),
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
    Runs automatically in the background too; this is the on-demand trigger."""
    from app.intelligence.face.dedupe import run_dedupe

    return await run_dedupe(session)


@router.get("/public/crop/{face_id}")
async def public_face_crop(face_id: str):
    """Public crop thumbnail (landing page). Faces come from public sources."""
    from fastapi.responses import FileResponse

    path = crop_path(face_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="crop_not_found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/public/index-sample")
async def public_index_sample(limit: int = 48, session: AsyncSession = Depends(get_session)) -> dict:
    """Public sample of indexed face crops — powers the landing-page scanner."""
    from sqlalchemy import desc, select as _select
    from app.database.models.face import Face as _Face

    rows = (
        await session.execute(_select(_Face).order_by(desc(_Face.created_at)).limit(max(1, min(limit, 120))))
    ).scalars().all()
    samples = [
        {"face_id": str(r.id), "crop_url": f"/intelligence/face/public/crop/{r.id}"}
        for r in rows
        if has_crop(str(r.id))
    ]
    return {"samples": samples, "count": len(samples)}


@router.post("/public/compare")
async def public_compare(
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    engine: FaceEngine = Depends(engine_dep),
) -> dict:
    """Public 1:1 face comparison used by the landing page (no account)."""
    _require_engine(engine)
    a = await detect_and_embed_async(engine, await _read_image(file_a))
    b = await detect_and_embed_async(engine, await _read_image(file_b))
    if not a or not b:
        return {"comparable": False, "detail": "no_face_detected_in_one_or_both",
                "faces_a": len(a), "faces_b": len(b)}
    score = cosine_similarity(a[0].embedding, b[0].embedding)
    band = band_for_similarity(score)
    return {
        "comparable": True,
        "similarity": round(score, 4),
        "similarity_pct": round(max(score, 0.0) * 100, 1),
        "band": band.value if band else "no_match",
        "note": "Similarity between two faces. Not an identity determination.",
    }


async def _related_faces(face_id: str, session: AsyncSession, *, limit: int = 24) -> dict:
    """Other indexed faces likely the same person (across sources), with contacts."""
    from sqlalchemy import select as _select
    from app.database.models.face import Face as _Face

    target = (await session.execute(_select(_Face).where(_Face.id == face_id))).scalar_one_or_none()
    if target is None or not target.embedding:
        raise HTTPException(status_code=404, detail="face_not_found")
    corpus = await FaceRepository(session).list_with_embeddings()
    by_id = {str(r.id): r for r in corpus}
    ranked = rank_by_cosine(
        list(target.embedding), [(str(r.id), r.embedding) for r in corpus], floor=STRONG
    )
    out = []
    seen_hash = {target.image_hash}
    for fid, score in ranked:
        if fid == face_id:
            continue
        rec = by_id[fid]
        if rec.image_hash in seen_hash:  # skip identical image dupes
            continue
        seen_hash.add(rec.image_hash)
        ex = rec.extra or {}
        band = band_for_similarity(score)
        out.append({
            "face_id": fid,
            "crop_url": f"/intelligence/face/public/crop/{fid}" if has_crop(fid) else None,
            "similarity_pct": round(score * 100, 1),
            "band": band.value if band else "no_match",
            "source_url": rec.source_url,
            "page_title": ex.get("page_title"),
            "names": ex.get("names") or [],
            "emails": ex.get("emails") or [],
            "phones": ex.get("phones") or [],
            "usernames": ex.get("usernames") or [],
        })
        if len(out) >= limit:
            break
    return {"face_id": face_id, "related": out, "count": len(out),
            "note": "Faces with strong similarity across sources — likely the same person, not confirmed."}


@router.get("/{face_id}/related")
async def related_faces(
    face_id: str,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await _related_faces(face_id, session)


@router.get("/public/{face_id}/related")
async def public_related_faces(face_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    return await _related_faces(face_id, session)


def _identifiers(extra: dict | None) -> set[str]:
    """Lowercased public identifiers extracted for a face (for connection links)."""
    ex = extra or {}
    out: set[str] = set()
    for key in ("names", "emails", "phones", "usernames"):
        for v in ex.get(key) or []:
            s = str(v).strip().lower()
            if s:
                out.add(s)
    return out


async def _connections(face_id: str, session: AsyncSession, *, limit: int = 24) -> dict:
    """DIFFERENT people connected to this face — co-located on the same source
    page, or sharing an extracted identifier (name/email/phone/username).

    This is the "find one person, surface their associates" view. Connections
    are public-data co-occurrences, not confirmed relationships.
    """
    from sqlalchemy import select as _select
    from app.database.models.face import Face as _Face

    target = (await session.execute(_select(_Face).where(_Face.id == face_id))).scalar_one_or_none()
    if target is None or not target.embedding:
        raise HTTPException(status_code=404, detail="face_not_found")

    corpus = await FaceRepository(session).list_with_embeddings()
    tgt_ids = _identifiers(target.extra)
    tgt_src = (target.source_url or "").strip()

    # Candidate people keyed by a representative face; dedup same-person faces.
    picked: list[dict] = []
    for rec in corpus:
        rid = str(rec.id)
        if rid == face_id or not rec.embedding:
            continue
        sim = cosine_similarity(list(target.embedding), rec.embedding)
        if sim >= POTENTIAL_MATCH:
            continue  # this is (likely) the target person again, not a connection

        reasons: list[str] = []
        if tgt_src and (rec.source_url or "").strip() == tgt_src:
            reasons.append("co_located")
        shared = tgt_ids & _identifiers(rec.extra)
        reasons.extend(f"shares:{s}" for s in sorted(shared)[:5])
        if not reasons:
            continue

        # Dedup against already-picked people (same face across pages).
        dup = None
        for p in picked:
            if cosine_similarity(rec.embedding, p["_emb"]) >= DEDUP_THRESHOLD:
                dup = p
                break
        if dup is not None:
            dup["reasons"] = sorted(set(dup["reasons"]) | set(reasons))
            if rec.quality > dup["_quality"]:
                continue  # keep the higher-quality representative
            continue

        ex = rec.extra or {}
        picked.append({
            "face_id": rid,
            "_emb": rec.embedding,
            "_quality": rec.quality,
            "reasons": reasons,
            "connection": "co_location" if "co_located" in reasons else "shared_identifier",
            "crop_url": f"/intelligence/face/crop/{rid}" if has_crop(rid) else None,
            "source_url": rec.source_url,
            "page_title": ex.get("page_title"),
            "quality": rec.quality,
            "names": ex.get("names") or [],
            "emails": ex.get("emails") or [],
            "phones": ex.get("phones") or [],
            "usernames": ex.get("usernames") or [],
            "titles": ex.get("titles") or [],
            "orgs": ex.get("orgs") or [],
            "locations": ex.get("locations") or [],
            "age": ex.get("age"),
            "sex": ex.get("sex"),
            "description": describe_face(rec.extra, rec.source_url),
        })

    # Co-located first, then by quality.
    picked.sort(key=lambda p: (0 if p["connection"] == "co_location" else 1, -p["_quality"]))
    for p in picked:
        p.pop("_emb", None)
        p.pop("_quality", None)
    out = picked[:limit]
    return {
        "face_id": face_id,
        "connections": out,
        "count": len(out),
        "note": (
            "People connected to this face via public co-occurrence (same page) or shared "
            "identifiers. Associations to observe, not confirmed relationships."
        ),
    }


@router.get("/{face_id}/connections")
async def face_connections(
    face_id: str,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await _connections(face_id, session)


@router.get("/public/{face_id}/connections")
async def public_face_connections(
    face_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    res = await _connections(face_id, session)
    # Public crops use the public crop route.
    for c in res["connections"]:
        if c.get("crop_url"):
            c["crop_url"] = c["crop_url"].replace("/intelligence/face/crop/", "/intelligence/face/public/crop/")
    return res
