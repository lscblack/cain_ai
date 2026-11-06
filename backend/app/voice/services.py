"""VoiceProfileService, VoiceCloningService and TextToSpeechService.

Long operations are background tasks with their own DB sessions; their state lives in
PostgreSQL so it is visible across requests and honest after a restart.
"""
from __future__ import annotations

import asyncio
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database import session as db_session
from app.database.models.voice import (
    ASSET_GENERATION, ASSET_REFERENCE, ASSET_REPRESENTATION, ASSET_SOURCE, GEN_CANCELED,
    GEN_COMPLETED, GEN_FAILED, GEN_QUEUED, GEN_RUNNING, PROFILE_FAILED, PROFILE_PROCESSING,
    PROFILE_READY, VoiceAsset, VoiceGeneration, VoiceProfile,
)
from app.voice import catalog
from app.voice.manager import get_manager
from app.voice.storage import VoiceStorageService, get_storage
from app.voice.supervisor import WorkerFailure
from app.voice.workers._text import reconcile_transcript

log = get_logger("kai.voice")

REFERENCE_MIN_S = 3.0
REFERENCE_MIN_SPEECH_S = 2.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sessions():
    # Looked up at call time so tests can point background work at their own database.
    return db_session.async_session_maker


class ProfileNotFound(Exception):
    pass


class VoiceProfileService:
    def __init__(self, session: AsyncSession, storage: VoiceStorageService | None = None) -> None:
        self.session = session
        self.storage = storage or get_storage()

    async def get_owned(self, user_id: uuid.UUID, profile_id: uuid.UUID) -> VoiceProfile:
        """Someone else's profile is indistinguishable from one that does not exist."""
        profile = await self.session.get(VoiceProfile, profile_id)
        if profile is None or profile.user_id != user_id:
            raise ProfileNotFound()
        return profile

    async def list_owned(self, user_id: uuid.UUID, q: str = "") -> list[VoiceProfile]:
        stmt = select(VoiceProfile).where(VoiceProfile.user_id == user_id)
        if q:
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.where(
                VoiceProfile.name.ilike(like, escape="\\") | VoiceProfile.description.ilike(like, escape="\\")
            )
        stmt = stmt.order_by(VoiceProfile.is_default.desc(), VoiceProfile.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def name_taken(self, user_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> bool:
        stmt = select(VoiceProfile.id).where(VoiceProfile.user_id == user_id, VoiceProfile.name == name)
        if exclude:
            stmt = stmt.where(VoiceProfile.id != exclude)
        return (await self.session.execute(stmt)).first() is not None

    async def set_default(self, profile: VoiceProfile) -> None:
        await self.session.execute(
            update(VoiceProfile)
            .where(VoiceProfile.user_id == profile.user_id, VoiceProfile.is_default.is_(True))
            .values(is_default=False)
        )
        await self.session.flush()
        profile.is_default = True

    async def add_source(self, profile: VoiceProfile, temp_file: Path, container: str) -> VoiceAsset:
        folder = self.storage.profile_dir(profile.user_id, profile.id)
        target = folder / self.storage.new_name("source", f".{container}")
        shutil.move(str(temp_file), target)
        target.chmod(0o600)
        await self.session.execute(
            update(VoiceAsset)
            .where(VoiceAsset.profile_id == profile.id, VoiceAsset.kind == ASSET_SOURCE)
            .values(active=False)
        )
        asset = VoiceAsset(
            user_id=profile.user_id, profile_id=profile.id, kind=ASSET_SOURCE,
            rel_path=self.storage.rel(target), mime=f"audio/{container}",
            size_bytes=target.stat().st_size, sha256=self.storage.sha256(target),
        )
        self.session.add(asset)
        await self.session.flush()
        return asset

    async def delete(self, profile: VoiceProfile) -> dict:
        """Removes the recording and everything derived from it, generated audio included."""
        generations = (await self.session.execute(
            select(VoiceGeneration.id).where(VoiceGeneration.profile_id == profile.id)
        )).scalars().all()
        for generation_id in generations:
            await get_tts_queue().cancel(generation_id)
            self.storage.delete_generation_tree(profile.user_id, generation_id)
        await self.session.execute(
            VoiceAsset.__table__.delete().where(
                VoiceAsset.generation_id.in_(generations) if generations else VoiceAsset.id.is_(None)
            )
        )
        self.storage.delete_profile_tree(profile.user_id, profile.id)
        await self.session.delete(profile)  # assets and generations cascade in the database
        await self.session.flush()
        return {"generations_deleted": len(generations)}


async def active_asset(session: AsyncSession, profile_id: uuid.UUID, kind: str,
                       engine_id: str | None = None) -> VoiceAsset | None:
    stmt = select(VoiceAsset).where(
        VoiceAsset.profile_id == profile_id, VoiceAsset.kind == kind, VoiceAsset.active.is_(True)
    )
    if engine_id is not None:
        stmt = stmt.where(VoiceAsset.engine_id == engine_id)
    return (await session.execute(stmt.order_by(VoiceAsset.created_at.desc()))).scalars().first()


async def _fail_profile(profile_id: uuid.UUID, detail: str) -> None:
    async with _sessions()() as session:
        profile = await session.get(VoiceProfile, profile_id)
        if profile:
            profile.status = PROFILE_FAILED
            profile.status_detail = detail[:1000]
            await session.commit()


class VoiceCloningService:
    """Source recording → normalized reference → (optional) transcript → voice representation."""

    _tasks: dict[uuid.UUID, asyncio.Task] = {}

    @classmethod
    def busy(cls) -> bool:
        return any(not task.done() for task in cls._tasks.values())

    @classmethod
    def schedule(cls, profile_id: uuid.UUID, model_id: str) -> None:
        running = cls._tasks.get(profile_id)
        if running and not running.done():
            return
        cls._tasks[profile_id] = asyncio.create_task(cls.run(profile_id, model_id))

    @classmethod
    async def run(cls, profile_id: uuid.UUID, model_id: str) -> None:
        storage = get_storage()
        try:
            from app.voice.realtime import get_realtime

            if get_realtime().active:
                # The hardware is reserved for the live session, and loading a model would end it.
                raise WorkerFailure("live_conversion_active", "Stop live conversion, then retry the analysis.")
            async with _sessions()() as session:
                profile = await session.get(VoiceProfile, profile_id)
                if profile is None:
                    return
                source = await active_asset(session, profile_id, ASSET_SOURCE)
                if source is None:
                    raise WorkerFailure("reference_missing", "no reference recording")
                user_id, language, transcript = profile.user_id, profile.language, profile.transcript
                source_path = storage.resolve(source.rel_path)
                source_id = source.id

            manager = get_manager()
            worker = await manager.tts_worker(model_id)
            folder = storage.profile_dir(user_id, profile_id)

            await _set_detail(profile_id, "Analyzing the recording")
            reference = folder / storage.new_name("reference", ".wav")
            info, _ = await worker.request(
                "normalize", {"src": str(source_path), "dst": str(reference), "rate": 24000, "max_s": 30},
                timeout=300,
            )
            if info["duration_s"] < REFERENCE_MIN_S or info["speech_s"] < REFERENCE_MIN_SPEECH_S:
                reference.unlink(missing_ok=True)
                raise WorkerFailure(
                    "reference_too_short",
                    f"Found {info['speech_s']:.1f}s of speech in {info['duration_s']:.1f}s of audio. "
                    "Record at least 5 seconds of clear speech.",
                )

            # Always checked against the audio that was kept: a transcript that says more than
            # the reference makes the model read the difference aloud in every generation.
            await _set_detail(profile_id, "Checking the transcript against the recording")
            result, _ = await worker.request(
                "transcribe", {"path": str(reference), "language": language}, timeout=900,
            )
            transcript = reconcile_transcript(transcript, result["text"])

            await _set_detail(profile_id, "Creating the voice representation")
            spec = catalog.get(model_id)
            representation = folder / storage.new_name(f"repr-{model_id}", ".pt")
            result, _ = await worker.request(
                "create_prompt",
                {"model_id": model_id, "ref": str(reference), "transcript": transcript, "out": str(representation)},
                timeout=900,
            )

            async with _sessions()() as session:
                profile = await session.get(VoiceProfile, profile_id)
                if profile is None:  # deleted while processing
                    return
                await session.execute(
                    update(VoiceAsset)
                    .where(
                        VoiceAsset.profile_id == profile_id,
                        VoiceAsset.kind.in_([ASSET_REFERENCE, ASSET_REPRESENTATION]),
                        (VoiceAsset.engine_id == model_id) | (VoiceAsset.kind == ASSET_REFERENCE),
                    )
                    .values(active=False)
                )
                session.add(VoiceAsset(
                    user_id=user_id, profile_id=profile_id, kind=ASSET_REFERENCE,
                    rel_path=storage.rel(reference), mime="audio/wav",
                    size_bytes=reference.stat().st_size, sha256=storage.sha256(reference),
                    meta={"from_asset": str(source_id), **info},
                ))
                session.add(VoiceAsset(
                    user_id=user_id, profile_id=profile_id, kind=ASSET_REPRESENTATION,
                    rel_path=storage.rel(representation), size_bytes=representation.stat().st_size,
                    sha256=storage.sha256(representation), engine_id=model_id,
                    engine_version=spec.revision, format_version=spec.format_version,
                    meta={"mode": result.get("mode"), "device": result.get("device")},
                ))
                profile.status = PROFILE_READY
                profile.status_detail = ""
                profile.transcript = transcript
                profile.duration_s = info["duration_s"]
                profile.model_id = model_id
                profile.model_version = spec.revision
                profile.meta = {**(profile.meta or {}), "analysis": info, "clone_mode": result.get("mode")}
                await session.commit()
            log.info("voice profile %s ready (%s)", profile_id, model_id)
        except WorkerFailure as exc:
            log.warning("voice profile %s failed: %s %s", profile_id, exc.code, exc)
            await _fail_profile(profile_id, str(exc) if exc.code in ("reference_too_short", "live_conversion_active") else f"{exc.code}: {exc}")
        except Exception as exc:  # noqa: BLE001 — a background task must record its failure
            log.exception("voice profile %s failed", profile_id)
            await _fail_profile(profile_id, f"internal_error: {type(exc).__name__}")


async def _set_detail(profile_id: uuid.UUID, detail: str) -> None:
    async with _sessions()() as session:
        profile = await session.get(VoiceProfile, profile_id)
        if profile:
            profile.status = PROFILE_PROCESSING
            profile.status_detail = detail
            await session.commit()


class TtsQueue:
    """Runs generations one at a time, because one model instance can only do one."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._canceled: set[uuid.UUID] = set()
        self._running: tuple[uuid.UUID, object, int] | None = None

    @property
    def busy(self) -> bool:
        return self._running is not None or not self._queue.empty()

    def submit(self, generation_id: uuid.UUID) -> None:
        self._queue.put_nowait(generation_id)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def cancel(self, generation_id: uuid.UUID) -> None:
        self._canceled.add(generation_id)
        if self._running and self._running[0] == generation_id:
            _, worker, request_id = self._running
            worker.cancel(request_id)  # type: ignore[attr-defined]

    async def _loop(self) -> None:
        while not self._queue.empty():
            generation_id = await self._queue.get()
            try:
                await self._run(generation_id)
            except Exception:  # noqa: BLE001 — one failed job must not stop the queue
                log.exception("generation %s crashed", generation_id)
                await _finish(generation_id, GEN_FAILED, error="internal_error")

    async def _run(self, generation_id: uuid.UUID) -> None:
        storage = get_storage()
        if generation_id in self._canceled:
            self._canceled.discard(generation_id)
            await _finish(generation_id, GEN_CANCELED)
            return
        async with _sessions()() as session:
            gen = await session.get(VoiceGeneration, generation_id)
            if gen is None:
                return
            profile = await session.get(VoiceProfile, gen.profile_id)
            if profile is None or profile.status != PROFILE_READY:
                await _finish(generation_id, GEN_FAILED, error="voice_not_ready")
                return
            model_id = profile.model_id
            representation = await active_asset(session, profile.id, ASSET_REPRESENTATION, model_id)
            if representation is None:
                await _finish(generation_id, GEN_FAILED, error="voice_not_ready")
                return
            spec = catalog.get(model_id)
            if representation.format_version != spec.format_version:
                await _finish(generation_id, GEN_FAILED, error="representation_outdated_reclone_required")
                return
            repr_path = storage.resolve(representation.rel_path)
            user_id, text, language, params = gen.user_id, gen.text, gen.language, dict(gen.params)
            gen.status = GEN_RUNNING
            gen.engine_id, gen.engine_version = model_id, spec.revision
            await session.commit()

        folder = storage.generation_dir(user_id, generation_id)
        wav = folder / "speech.wav"
        mp3 = folder / "speech.mp3"
        started = time.monotonic()
        try:
            worker = await get_manager().tts_worker(model_id)
            request_id = worker.new_request_id()
            self._running = (generation_id, worker, request_id)
            if generation_id in self._canceled:
                worker.cancel(request_id)

            async def on_event(event: dict) -> None:
                if "progress" in event:
                    async with _sessions()() as session:
                        await session.execute(
                            update(VoiceGeneration).where(VoiceGeneration.id == generation_id)
                            .values(progress=float(event["progress"]))
                        )
                        await session.commit()

            result, _ = await worker.request(
                "generate",
                {"model_id": model_id, "prompt": str(repr_path), "text": text, "language": language,
                 "out_wav": str(wav), "out_mp3": str(mp3), **params},
                on_event=on_event, request_id=request_id,
            )
        except WorkerFailure as exc:
            storage.delete_generation_tree(user_id, generation_id)
            if exc.code == "cancelled":
                await _finish(generation_id, GEN_CANCELED)
            else:
                log.warning("generation %s failed: %s %s", generation_id, exc.code, exc)
                await _finish(generation_id, GEN_FAILED, error=f"{exc.code}: {exc}")
            return
        finally:
            self._running = None
            self._canceled.discard(generation_id)

        async with _sessions()() as session:
            gen = await session.get(VoiceGeneration, generation_id)
            if gen is None:  # voice deleted while generating
                storage.delete_generation_tree(user_id, generation_id)
                return
            for path, mime in ((wav, "audio/wav"), (mp3, "audio/mpeg")):
                if path.exists():
                    session.add(VoiceAsset(
                        user_id=user_id, generation_id=generation_id, kind=ASSET_GENERATION,
                        rel_path=storage.rel(path), mime=mime, size_bytes=path.stat().st_size,
                        sha256=storage.sha256(path), engine_id=model_id, engine_version=spec.revision,
                    ))
            gen.status = GEN_COMPLETED
            gen.progress = 1.0
            gen.duration_s = result["duration_s"]
            gen.inference_s = time.monotonic() - started
            gen.device = result.get("device", "")
            gen.finished_at = _now()
            await session.commit()


async def _finish(generation_id: uuid.UUID, status: str, error: str = "") -> None:
    async with _sessions()() as session:
        gen = await session.get(VoiceGeneration, generation_id)
        if gen:
            gen.status = status
            gen.error = error[:2000]
            gen.finished_at = _now()
            await session.commit()


_tts_queue: TtsQueue | None = None


def get_tts_queue() -> TtsQueue:
    global _tts_queue
    if _tts_queue is None:
        _tts_queue = TtsQueue()
    return _tts_queue


async def reset_interrupted() -> None:
    """Work that was running when the process died cannot resume; say so."""
    async with _sessions()() as session:
        await session.execute(
            update(VoiceProfile).where(VoiceProfile.status == PROFILE_PROCESSING)
            .values(status=PROFILE_FAILED, status_detail="Interrupted by a restart. Retry the analysis.")
        )
        await session.execute(
            update(VoiceGeneration).where(VoiceGeneration.status.in_([GEN_QUEUED, GEN_RUNNING]))
            .values(status=GEN_FAILED, error="interrupted_by_restart", finished_at=_now())
        )
        from app.database.models.voice import VoiceConversionSession

        await session.execute(
            update(VoiceConversionSession).where(VoiceConversionSession.status == "active")
            .values(status="interrupted", ended_at=_now())
        )
        await session.commit()
    get_storage().sweep_temp()


def tts_limits() -> dict:
    settings = get_settings()
    return {"max_chars": settings.voice_tts_max_chars, "max_upload_mb": settings.voice_upload_max_mb}
