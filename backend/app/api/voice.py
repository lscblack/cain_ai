"""Voice Intelligence API: profiles, cloned TTS, live conversion and model management.

Voice recordings are biometric data, so every route here requires an authenticated
operator, checks ownership, and refuses requests arriving through a proxy or tunnel
unless KAI_VOICE_ALLOW_REMOTE is set (see ``require_local_voice``).
"""
from __future__ import annotations

import hmac
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, WebSocket,
    WebSocketDisconnect, status,
)
from fastapi.responses import FileResponse
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.core.config import get_settings
from app.core.ratelimit import check_rate_limit
from app.core.redis import get_redis
from app.core.security import TokenError, decode_token
from app.database.models.user import User
from app.database.models.voice import (
    ASSET_GENERATION, ASSET_REFERENCE, ASSET_SOURCE, GEN_FAILED, GEN_COMPLETED, GEN_CANCELED,
    GEN_QUEUED, PROFILE_PROCESSING, PROFILE_READY, VoiceAsset, VoiceConversionSession,
    VoiceGeneration, VoiceProfile,
)
from app.database.repositories.audit_repo import AuditRepository
from app.database.repositories.user_repo import UserRepository
from app.database.session import async_session_maker, get_session
from app.voice import catalog
from app.voice.audio import AudioValidationError, validate_upload
from app.voice.manager import ManagerError, get_manager
from app.voice.realtime import RealtimeAudioService, get_realtime
from app.voice.schemas import CloneRequest, ModelAction, ProfilePatch, TtsRequest, VirtualMicAction
from app.voice.services import (
    ProfileNotFound, VoiceCloningService, VoiceProfileService, active_asset, get_tts_queue, tts_limits,
)
from app.voice.storage import VoiceStorageService, get_storage
from app.voice.virtual_mic import VirtualMicError, get_virtual_mic

# Headers added by Cloudflare, Tailscale Serve and reverse proxies.
_PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-real-ip", "forwarded", "tailscale-user-login")
_NAME_RE = re.compile(r"^[^\x00-\x1f]{1,120}$")
_CONSENT_BASES = {"own_voice", "permission"}


def _is_proxied(headers) -> bool:
    return any(headers.get(h) for h in _PROXY_HEADERS)


async def require_local_voice(request: Request) -> None:
    if _is_proxied(request.headers) and not get_settings().voice_allow_remote:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="voice_local_only")


router = APIRouter(prefix="/voice", tags=["voice"], dependencies=[Depends(require_local_voice)])
ws_router = APIRouter(prefix="/voice", tags=["voice"])


async def _limit(redis: Redis, operator: User, bucket: str) -> None:
    await check_rate_limit(
        redis, f"rl:voice:{bucket}:{operator.id}",
        limit=get_settings().voice_rate_limit_per_min, window_seconds=60,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _profile_out(p: VoiceProfile) -> dict:
    return {
        "id": str(p.id), "name": p.name, "description": p.description, "language": p.language,
        "transcript": p.transcript, "status": p.status, "status_detail": p.status_detail,
        "is_default": p.is_default, "model_id": p.model_id, "model_version": p.model_version,
        "consent_confirmed": p.consent_confirmed, "consent_basis": p.consent_basis,
        "consent_subject": p.consent_subject, "consent_at": _iso(p.consent_at),
        "duration_s": p.duration_s, "meta": p.meta or {},
        "created_at": _iso(p.created_at), "updated_at": _iso(p.updated_at),
    }


def _generation_out(g: VoiceGeneration, profile_name: str | None = None) -> dict:
    return {
        "id": str(g.id), "profile_id": str(g.profile_id), "profile_name": profile_name,
        "text": g.text, "language": g.language, "params": g.params or {}, "status": g.status,
        "progress": g.progress, "error": g.error, "engine_id": g.engine_id,
        "engine_version": g.engine_version, "device": g.device, "duration_s": g.duration_s,
        "inference_s": g.inference_s, "created_at": _iso(g.created_at), "finished_at": _iso(g.finished_at),
    }


async def _receive_upload(upload: UploadFile, storage: VoiceStorageService, folder: Path) -> tuple[Path, str]:
    """Stream to a temp file, enforcing the size limit and checking the real format."""
    limit = get_settings().voice_upload_max_mb * 1024 * 1024
    head = await upload.read(4096)
    if not head:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="empty_audio_file")
    try:
        container = validate_upload(upload.filename, head)
    except AudioValidationError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=exc.code) from exc
    target = folder / f"upload.{container}"
    size = len(head)
    with target.open("wb") as fh:
        fh.write(head)
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="audio_file_too_large")
            fh.write(chunk)
    return target, container


def _check_consent(confirmed: bool, basis: str, subject: str) -> None:
    if not confirmed or basis not in _CONSENT_BASES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="consent_required")
    if basis == "permission" and not subject.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="consent_subject_required")


async def _owned(service: VoiceProfileService, operator: User, profile_id: uuid.UUID) -> VoiceProfile:
    try:
        return await service.get_owned(operator.id, profile_id)
    except ProfileNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="voice_not_found") from exc


def _default_tts_model() -> str:
    return get_settings().voice_tts_model


# ── Profiles ─────────────────────────────────────────────────────────────────


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=120),
    description: str = Form(default="", max_length=2000),
    language: str = Form(default="auto", max_length=32),
    transcript: str = Form(default="", max_length=5000),
    consent_confirmed: bool = Form(default=False),
    consent_basis: str = Form(default=""),
    consent_subject: str = Form(default="", max_length=200),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    await _limit(redis, operator, "clone")
    name = name.strip()
    if not _NAME_RE.match(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_name")
    _check_consent(consent_confirmed, consent_basis, consent_subject)

    storage = get_storage()
    service = VoiceProfileService(session, storage)
    if await service.name_taken(operator.id, name):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="voice_name_taken")

    with storage.temp_dir() as tmp:
        upload, container = await _receive_upload(file, storage, tmp)
        has_any = (await session.execute(
            select(func.count()).select_from(VoiceProfile).where(VoiceProfile.user_id == operator.id)
        )).scalar_one()
        profile = VoiceProfile(
            user_id=operator.id, name=name, description=description, language=language,
            transcript=transcript.strip(), status=PROFILE_PROCESSING, status_detail="Queued",
            is_default=has_any == 0, consent_confirmed=True, consent_basis=consent_basis,
            consent_subject=consent_subject.strip(), consent_at=datetime.now(timezone.utc),
        )
        session.add(profile)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="voice_name_taken") from exc
        await service.add_source(profile, upload, container)

    await AuditRepository(session).record(
        "voice.profile_created", actor_id=operator.id, ip=_ip(request),
        detail={"profile_id": str(profile.id), "consent_basis": consent_basis,
                "consent_subject": consent_subject.strip()},
    )
    out = _profile_out(profile)
    await session.commit()  # the background task reads it from another session
    VoiceCloningService.schedule(profile.id, _default_tts_model())
    return out


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/profiles")
async def list_profiles(
    q: str = Query(default="", max_length=120),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    profiles = await VoiceProfileService(session).list_owned(operator.id, q.strip())
    return {"profiles": [_profile_out(p) for p in profiles], "limits": tts_limits()}


@router.get("/profiles/{profile_id}")
async def get_profile(
    profile_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return _profile_out(await _owned(VoiceProfileService(session), operator, profile_id))


@router.patch("/profiles/{profile_id}")
async def patch_profile(
    profile_id: uuid.UUID,
    body: ProfilePatch,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    service = VoiceProfileService(session)
    profile = await _owned(service, operator, profile_id)
    if body.name is not None:
        name = body.name.strip()
        if not _NAME_RE.match(name):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_name")
        if await service.name_taken(operator.id, name, exclude=profile.id):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="voice_name_taken")
        profile.name = name
    if body.description is not None:
        profile.description = body.description
    if body.language is not None:
        profile.language = body.language
    if body.transcript is not None:
        profile.transcript = body.transcript.strip()
    if body.is_default is True:
        await service.set_default(profile)
    elif body.is_default is False:
        profile.is_default = False
    await session.flush()
    await session.refresh(profile)  # updated_at is set by the database
    return _profile_out(profile)


@router.delete("/profiles/{profile_id}")
async def delete_profile(
    profile_id: uuid.UUID,
    request: Request,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    service = VoiceProfileService(session)
    profile = await _owned(service, operator, profile_id)
    realtime = get_realtime()
    if realtime.active_profile_id == profile.id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="voice_in_use_by_live_conversion")
    result = await service.delete(profile)
    await AuditRepository(session).record(
        "voice.profile_deleted", actor_id=operator.id, ip=_ip(request),
        detail={"profile_id": str(profile_id), **result},
    )
    return {"deleted": True, **result}


@router.put("/profiles/{profile_id}/reference")
async def replace_reference(
    profile_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    transcript: str = Form(default="", max_length=5000),
    consent_confirmed: bool = Form(default=False),
    consent_basis: str = Form(default=""),
    consent_subject: str = Form(default="", max_length=200),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    """A new recording may be a different person, so consent is attested again."""
    await _limit(redis, operator, "clone")
    _check_consent(consent_confirmed, consent_basis, consent_subject)
    storage = get_storage()
    service = VoiceProfileService(session, storage)
    profile = await _owned(service, operator, profile_id)
    with storage.temp_dir() as tmp:
        upload, container = await _receive_upload(file, storage, tmp)
        await service.add_source(profile, upload, container)
    profile.transcript = transcript.strip()
    profile.status = PROFILE_PROCESSING
    profile.status_detail = "Queued"
    profile.consent_basis = consent_basis
    profile.consent_subject = consent_subject.strip()
    profile.consent_at = datetime.now(timezone.utc)
    await AuditRepository(session).record(
        "voice.reference_replaced", actor_id=operator.id, ip=_ip(request),
        detail={"profile_id": str(profile.id), "consent_basis": consent_basis},
    )
    await session.flush()
    await session.refresh(profile)
    out = _profile_out(profile)
    await session.commit()
    VoiceCloningService.schedule(profile.id, profile.model_id or _default_tts_model())
    return out


@router.post("/profiles/{profile_id}/clone")
async def clone_profile(
    profile_id: uuid.UUID,
    body: CloneRequest | None = None,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    """(Re)build the voice representation, e.g. after a failure or for another model."""
    await _limit(redis, operator, "clone")
    profile = await _owned(VoiceProfileService(session), operator, profile_id)
    model_id = (body.model_id if body else None) or profile.model_id or _default_tts_model()
    spec = catalog.find(model_id)
    if spec is None or spec.kind != "tts":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown_model")
    profile.status = PROFILE_PROCESSING
    profile.status_detail = "Queued"
    await session.flush()
    await session.refresh(profile)
    out = _profile_out(profile)
    await session.commit()
    VoiceCloningService.schedule(profile.id, model_id)
    return out


@router.get("/profiles/{profile_id}/reference/audio")
async def reference_audio(
    profile_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    await _owned(VoiceProfileService(session), operator, profile_id)
    asset = await active_asset(session, profile_id, ASSET_REFERENCE) or await active_asset(
        session, profile_id, ASSET_SOURCE
    )
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="reference_missing")
    path = get_storage().resolve(asset.rel_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="reference_missing")
    return FileResponse(path, media_type=asset.mime, headers={"Cache-Control": "no-store"})


# ── Text to speech ───────────────────────────────────────────────────────────


@router.post("/tts/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_speech(
    body: TtsRequest,
    request: Request,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    await _limit(redis, operator, "tts")
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="text_required")
    if len(text) > get_settings().voice_tts_max_chars:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="text_too_long")
    profile = await _owned(VoiceProfileService(session), operator, body.profile_id)
    if profile.status != PROFILE_READY:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="voice_not_ready")
    if get_realtime().active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="live_conversion_active")
    generation = VoiceGeneration(
        user_id=operator.id, profile_id=profile.id, text=text, language=body.language,
        status=GEN_QUEUED,
        params={"speed": body.speed, "pitch_semitones": body.pitch_semitones,
                "temperature": body.temperature, "top_p": body.top_p, "seed": body.seed},
    )
    session.add(generation)
    await session.flush()
    await AuditRepository(session).record(
        "voice.tts_generated", actor_id=operator.id, ip=_ip(request),
        detail={"generation_id": str(generation.id), "profile_id": str(profile.id), "chars": len(text)},
    )
    out = _generation_out(generation, profile.name)
    await session.commit()
    get_tts_queue().submit(generation.id)
    return out


async def _owned_generation(session: AsyncSession, operator: User, generation_id: uuid.UUID) -> VoiceGeneration:
    generation = await session.get(VoiceGeneration, generation_id)
    if generation is None or generation.user_id != operator.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="generation_not_found")
    return generation


@router.get("/generations")
async def list_generations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    profile_id: uuid.UUID | None = Query(default=None),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = (
        select(VoiceGeneration, VoiceProfile.name)
        .join(VoiceProfile, VoiceProfile.id == VoiceGeneration.profile_id)
        .where(VoiceGeneration.user_id == operator.id)
    )
    if profile_id:
        stmt = stmt.where(VoiceGeneration.profile_id == profile_id)
    rows = (await session.execute(
        stmt.order_by(VoiceGeneration.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return {"generations": [_generation_out(g, name) for g, name in rows]}


@router.get("/generations/{generation_id}")
async def get_generation(
    generation_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    generation = await _owned_generation(session, operator, generation_id)
    profile = await session.get(VoiceProfile, generation.profile_id)
    return _generation_out(generation, profile.name if profile else None)


@router.post("/generations/{generation_id}/cancel")
async def cancel_generation(
    generation_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    generation = await _owned_generation(session, operator, generation_id)
    if generation.status in (GEN_COMPLETED, GEN_FAILED, GEN_CANCELED):
        return {"status": generation.status}
    await get_tts_queue().cancel(generation_id)
    return {"status": "canceling"}


@router.delete("/generations/{generation_id}")
async def delete_generation(
    generation_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    generation = await _owned_generation(session, operator, generation_id)
    if generation.status not in (GEN_COMPLETED, GEN_FAILED, GEN_CANCELED):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="generation_still_running")
    get_storage().delete_generation_tree(operator.id, generation_id)
    await session.execute(VoiceAsset.__table__.delete().where(VoiceAsset.generation_id == generation_id))
    await session.delete(generation)
    return {"deleted": True}


@router.get("/generations/{generation_id}/audio")
async def generation_audio(
    generation_id: uuid.UUID,
    format: str = Query(default="wav", pattern="^(wav|mp3)$"),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    generation = await _owned_generation(session, operator, generation_id)
    mime = "audio/wav" if format == "wav" else "audio/mpeg"
    asset = (await session.execute(
        select(VoiceAsset).where(
            VoiceAsset.generation_id == generation.id, VoiceAsset.kind == ASSET_GENERATION,
            VoiceAsset.mime == mime,
        )
    )).scalars().first()
    path = get_storage().resolve(asset.rel_path) if asset else None
    if path is None or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="audio_not_available")
    return FileResponse(
        path, media_type=mime, filename=f"kai-speech-{str(generation.id)[:8]}.{format}",
        headers={"Cache-Control": "no-store"},
    )


# ── Live conversion ──────────────────────────────────────────────────────────


@router.get("/conversion/status")
async def conversion_status(operator: User = Depends(get_current_operator)) -> dict:
    return {**get_realtime().status(), "virtual_mic": await get_virtual_mic().status()}


@router.post("/conversion/stop")
async def conversion_stop(operator: User = Depends(get_current_operator)) -> dict:
    """Ends the operator's live session from outside the WebSocket that runs it."""
    await get_realtime().request_stop(operator.id)
    return {"stopped": True}


@router.get("/conversion/sessions")
async def conversion_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = (await session.execute(
        select(VoiceConversionSession).where(VoiceConversionSession.user_id == operator.id)
        .order_by(VoiceConversionSession.created_at.desc()).limit(limit)
    )).scalars().all()
    return {"sessions": [{
        "id": str(s.id), "profile_id": str(s.profile_id) if s.profile_id else None, "status": s.status,
        "engine_id": s.engine_id, "device": s.device, "virtual_mic": s.virtual_mic,
        "stats": s.stats, "error": s.error, "created_at": _iso(s.created_at), "ended_at": _iso(s.ended_at),
    } for s in rows]}


@router.put("/conversion/virtual-mic")
async def set_virtual_mic(
    body: VirtualMicAction,
    request: Request,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    vmic = get_virtual_mic()
    try:
        if body.enabled:
            result = await vmic.enable()
        else:
            await vmic.disable()
            result = await vmic.status()
    except VirtualMicError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.code) from exc
    await AuditRepository(session).record(
        "voice.virtual_mic", actor_id=operator.id, ip=_ip(request), detail={"enabled": body.enabled},
    )
    return result


async def _ws_operator(token: str) -> User | None:
    try:
        sub = decode_token(token).get("sub")
        user_id = uuid.UUID(str(sub))
    except (TokenError, ValueError):
        return None
    async with async_session_maker() as session:
        return await UserRepository(session).get(user_id)


def _origin_allowed(origin: str | None) -> bool:
    """A page on another site must not be able to open a socket with a stolen context."""
    if not origin:
        return True  # non-browser client; it still has to authenticate
    from urllib.parse import urlsplit

    host = urlsplit(origin).hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    return any(hmac.compare_digest(origin, allowed) for allowed in get_settings().cors_origins)


@ws_router.websocket("/conversion/ws")
async def conversion_ws(ws: WebSocket) -> None:
    """Continuous audio stream. Authentication arrives in the first message so the
    token is never written to a URL or an access log. Protocol: app/voice/realtime.py."""
    await ws.accept()
    if (_is_proxied(ws.headers) and not get_settings().voice_allow_remote) or not _origin_allowed(
        ws.headers.get("origin")
    ):
        await ws.send_json({"type": "error", "code": "voice_local_only"})
        await ws.close(code=4403)
        return
    service: RealtimeAudioService = get_realtime()
    try:
        hello = await ws.receive_json()
    except (WebSocketDisconnect, ValueError):
        return
    operator = await _ws_operator(str(hello.get("token", ""))) if isinstance(hello, dict) else None
    if operator is None:
        await ws.send_json({"type": "error", "code": "not_authenticated"})
        await ws.close(code=4401)
        return
    await service.run_socket(ws, operator, hello)


# ── Models and hardware ──────────────────────────────────────────────────────


@router.get("/models")
async def list_models(operator: User = Depends(get_current_operator)) -> dict:
    return {"models": await get_manager().list_models()}


@router.get("/hardware")
async def hardware(
    probe: bool = Query(default=False),
    operator: User = Depends(get_current_operator),
) -> dict:
    return await get_manager().hardware(probe=probe)


@router.post("/models/{model_id}")
async def model_action(
    model_id: str,
    body: ModelAction,
    request: Request,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    await _limit(redis, operator, "models")
    if catalog.find(model_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown_model")
    manager = get_manager()
    try:
        if body.action == "install":
            result = manager.start_install(model_id)
            await AuditRepository(session).record(
                "voice.model_install", actor_id=operator.id, ip=_ip(request), detail={"model_id": model_id},
            )
            return result
        if body.action == "load":
            return await manager.load(model_id)
        if body.action == "unload":
            return await manager.unload(model_id)
        return await manager.health_check(model_id)
    except ManagerError as exc:
        raise HTTPException(exc.status, detail=exc.code) from exc
