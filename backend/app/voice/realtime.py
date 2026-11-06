"""RealtimeAudioService and VoiceConversionService: live conversion over a WebSocket.

    client → server  text   {"type": "hello", "token", "profile_id", "virtual_mic"}
                     binary u32 seq, u32 flags, f64 capture_ms, Int16 PCM (little endian)
                     text   {"type": "set_target" | "set_virtual_mic" | "client_stats" | "stop"}
    server → client  text   {"type": "status" | "ready" | "target_changed" | "stats" | "error" | "stopped"}
                     binary u32 seq, u32 flags, f64 capture_ms, f32 proc_ms, f32 queue_ms, Int16 PCM

Each session times real inference first. If this machine cannot keep up, the session is
refused with the measured numbers (``too_slow_for_realtime``) rather than presented as
live, unless the client explicitly asks for ``mode: "delayed"``, which keeps every word
but is labelled as not real time.

Live audio always moves forward: a block that falls behind is dropped and counted rather
than letting latency grow, and missing blocks are not waited for. The numbers reported
are measurements of this session.
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.logging import get_logger
from app.database import session as db_session
from app.database.models.audit import AuditLog
from app.database.models.user import User
from app.database.models.voice import (
    ASSET_REFERENCE, PROFILE_READY, VoiceConversionSession, VoiceProfile,
)
from app.voice.manager import get_manager
from app.voice.storage import get_storage
from app.voice.supervisor import WorkerFailure, WorkerProcess
from app.voice.virtual_mic import VirtualMicError, get_virtual_mic

log = get_logger("kai.voice.realtime")

_UP = struct.Struct("<IId")
_DOWN = struct.Struct("<IIdff")
_FLAG_SILENCE = 1
_MAX_BACKLOG_BLOCKS = 3
_MAX_DELAYED_BACKLOG_S = 180
_MIN_LONG_BLOCK_S = 0.5
_MAX_LONG_BLOCK_S = 4.0
_MAX_LONG_START_S = 2.0
_LONG_BLOCK_MARGIN = 0.92
_LONG_BLOCK_CONTEXT_S = 0.3
# Inference has to fit inside a block with a margin, or the queue eventually grows.
_REALTIME_MARGIN = 0.9
_STATS_EVERY_S = 1.0
_LATENCY_WINDOW = 400


def block_for_speed(realtime_cost: float, fixed_s: float, margin: float = _REALTIME_MARGIN) -> float | None:
    """The shortest block this machine can keep up with.

    Inference costs ``realtime_cost`` seconds per second of audio in its window, and the window
    is the block plus ``fixed_s``. Keeping up needs cost * (block + fixed) <= margin * block.
    """
    if realtime_cost >= margin:
        return None
    return max(_MIN_LONG_BLOCK_S, math.ceil(realtime_cost * fixed_s / (margin - realtime_cost) * 10) / 10)


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))] if ordered else 0.0


class SessionMetrics:
    def __init__(self, block_ms: float) -> None:
        self.block_ms = block_ms
        self.received = 0
        self.converted = 0
        self.silent = 0
        self.dropped = 0
        self.lost = 0
        self.expected_seq: int | None = None
        self.proc: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        self.server: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        self.client_latency_p50: float | None = None
        self.client_latency_p95: float | None = None
        self.underruns = 0
        self.started = time.monotonic()

    def note_seq(self, seq: int) -> None:
        if self.expected_seq is not None and seq > self.expected_seq:
            self.lost += seq - self.expected_seq
        self.expected_seq = seq + 1

    def realtime_factor(self) -> float | None:
        """Audio duration per second of compute, over speech blocks only. Below 1 can't keep up."""
        if not self.proc:
            return None
        return round(self.block_ms / _percentile(list(self.proc), 0.5), 2)

    def as_dict(self) -> dict:
        proc = list(self.proc)
        return {
            "blocks_received": self.received, "blocks_converted": self.converted, "blocks_silent": self.silent,
            "dropped": self.dropped, "lost": self.lost, "block_ms": round(self.block_ms, 1),
            "proc_ms_avg": round(sum(proc) / len(proc), 1) if proc else None,
            "proc_ms_p95": round(_percentile(proc, 0.95), 1) if proc else None,
            "server_ms_p95": round(_percentile(list(self.server), 0.95), 1) if self.server else None,
            "realtime_factor": self.realtime_factor(),
            "client_latency_ms_p50": self.client_latency_p50, "client_latency_ms_p95": self.client_latency_p95,
            "client_underruns": self.underruns, "duration_s": round(time.monotonic() - self.started, 1),
        }


class RealtimeAudioService:
    """One live session at a time: a second would just make both miss their deadlines."""

    def __init__(self) -> None:
        self._owner: uuid.UUID | None = None
        self.active_profile_id: uuid.UUID | None = None
        self._stop_requested = False
        self._engine_info: dict | None = None
        self._claim = asyncio.Lock()

    @property
    def active(self) -> bool:
        return self._owner is not None

    def status(self) -> dict:
        return {"active": self.active, "profile_id": str(self.active_profile_id) if self.active_profile_id else None,
                "engine": self._engine_info}

    async def request_stop(self, user_id: uuid.UUID) -> None:
        if self._owner == user_id:
            self._stop_requested = True

    async def _reference_for(self, user_id: uuid.UUID, profile_id: uuid.UUID) -> Path | None:
        from sqlalchemy import select

        from app.database.models.voice import VoiceAsset

        async with db_session.async_session_maker() as session:
            profile = await session.get(VoiceProfile, profile_id)
            if profile is None or profile.user_id != user_id or profile.status != PROFILE_READY:
                return None
            asset = (await session.execute(
                select(VoiceAsset).where(
                    VoiceAsset.profile_id == profile_id, VoiceAsset.kind == ASSET_REFERENCE,
                    VoiceAsset.active.is_(True),
                ).order_by(VoiceAsset.created_at.desc())
            )).scalars().first()
        if asset is None:
            return None
        path = get_storage().resolve(asset.rel_path)
        return path if path.exists() else None

    async def run_socket(self, ws: WebSocket, operator: User, hello: dict) -> None:
        try:
            profile_id = uuid.UUID(str(hello.get("profile_id")))
        except ValueError:
            await _send_error(ws, "voice_not_found")
            return
        async with self._claim:
            if self._owner is not None:
                await _send_error(ws, "session_already_active")
                return
            self._owner = operator.id
            self.active_profile_id = profile_id
            self._stop_requested = False
        try:
            await self._session(ws, operator, profile_id, bool(hello.get("virtual_mic")),
                                hello.get("mode") == "delayed")
        except WebSocketDisconnect:
            # Normal: the operator pressed Stop or closed the page while we were talking to them.
            log.info("live session client disconnected")
        finally:
            self._owner = None
            self.active_profile_id = None
            self._engine_info = None

    async def _session(self, ws: WebSocket, operator: User, profile_id: uuid.UUID, want_vmic: bool,
                       delayed: bool) -> None:
        manager = get_manager()
        from app.voice.services import VoiceCloningService, get_tts_queue

        if get_tts_queue().busy or VoiceCloningService.busy():
            await _send_error(ws, "tts_in_progress")
            return
        spec = await manager.choose_vc_spec()
        if spec is None:
            await _send_error(ws, "no_realtime_engine")
            return
        reference = await self._reference_for(operator.id, profile_id)
        if reference is None:
            await _send_error(ws, "voice_not_ready")
            return

        await ws.send_json({"type": "status", "stage": f"Loading {spec.name}"})
        vmic = get_virtual_mic()
        try:
            worker, _ = await manager.vc_worker(spec)
            await ws.send_json({"type": "status", "stage": "Preparing the target voice"})
            await worker.request("set_target", {"reference": str(reference)}, timeout=120)
            info, _ = await worker.request("start", {}, timeout=30)
            await ws.send_json({"type": "status", "stage": "Measuring this machine's speed"})
            speed, _ = await worker.request("calibrate", {}, timeout=120)
            log.info("realtime calibration %s on %s: %s", spec.id, info["device"], speed)
            near_live = False
            if speed["proc_ms"] > speed["block_ms"] * _REALTIME_MARGIN and not delayed:
                if spec.extra.get("long_blocks"):
                    info, speed, near_live = await self._fit_block(ws, worker, info, speed)
                if not near_live:
                    manager.record_realtime(spec.id, {
                        "summary": f"Too slow for live use on {info['device']}: {speed['proc_ms']:.0f} ms to convert "
                                   f"a {speed['block_ms']:.0f} ms block.", **speed})
                    await ws.send_json({
                        "type": "too_slow", "engine": spec.name, "device": info["device"], **speed,
                    })
                    await ws.close(code=4409)
                    return
            if want_vmic and not vmic.enabled:
                await vmic.enable()
        except WorkerFailure as exc:
            await _send_error(ws, exc.code, str(exc))
            return
        except VirtualMicError as exc:
            await _send_error(ws, exc.code, str(exc))
            return

        rate, block = info["sample_rate"], info["block_samples"]
        self._engine_info = {"id": spec.id, "device": info["device"], "sample_rate": rate, "block_samples": block}
        session_id = await self._open_record(operator.id, profile_id, spec, info["device"], want_vmic)
        metrics = SessionMetrics(block / rate * 1000)
        error: str | None = None
        try:
            await ws.send_json({
                "type": "ready", "session_id": str(session_id), "engine": spec.name, "device": info["device"],
                "sample_rate": rate, "block_samples": block, "lookahead_ms": info["lookahead_ms"],
                "delayed": delayed, "near_live": near_live, "calibration": speed,
            })
            error = await self._pump(ws, worker, operator, metrics, rate, block, want_vmic, delayed)
        finally:
            manager.record_realtime(spec.id, _realtime_summary(metrics, info["device"]))
            await vmic.release_stream()
            try:
                await worker.request("stop", timeout=10)
            except WorkerFailure:
                pass
            await self._close_record(session_id, metrics, error)
        if ws.client_state == WebSocketState.CONNECTED:
            if error:
                await _send_error(ws, error)
            else:
                await ws.send_json({"type": "stopped", "stats": metrics.as_dict()})
                await ws.close()

    @staticmethod
    async def _fit_block(ws: WebSocket, worker: WorkerProcess, info: dict, speed: dict) -> tuple[dict, dict, bool]:
        """Trade latency for continuity: longer blocks cost less per second of speech."""
        cost = speed["proc_ms"] / 1000 / info["window_s"]
        fixed = _LONG_BLOCK_CONTEXT_S + info["fixed_overhead_s"]
        # One timing on a busy machine is only a hint of where to start, never a reason to give
        # up. Each size is timed for real; a short backlog absorbs what the margin doesn't.
        block_s = min(block_for_speed(cost, fixed, _LONG_BLOCK_MARGIN) or _MAX_LONG_START_S, _MAX_LONG_START_S)
        while block_s <= _MAX_LONG_BLOCK_S:
            await ws.send_json({"type": "status", "stage": f"Trying {block_s:.1f} s blocks on this hardware"})
            info, _ = await worker.request("start", {"block_s": block_s, "context_s": _LONG_BLOCK_CONTEXT_S}, timeout=30)
            speed, _ = await worker.request("calibrate", {}, timeout=120)
            if speed["proc_ms"] <= speed["block_ms"] * _LONG_BLOCK_MARGIN:
                return info, speed, True
            block_s = round(block_s + 0.5, 1)
        return info, speed, False

    async def _pump(self, ws: WebSocket, worker: WorkerProcess, operator: User, metrics: SessionMetrics,
                    rate: int, block: int, want_vmic: bool, delayed: bool) -> str | None:
        vmic = get_virtual_mic()
        max_backlog = int(_MAX_DELAYED_BACKLOG_S * rate / block) if delayed else _MAX_BACKLOG_BLOCKS
        queue: deque[tuple[int, float, bytes]] = deque()
        wake = asyncio.Event()
        done = asyncio.Event()
        send_vmic = {"on": want_vmic}
        phrase: list[bytes] = []
        vmic_queue: asyncio.Queue[bytes] = asyncio.Queue()
        failure: list[str] = []
        block_bytes = block * 2

        async def converter() -> None:
            while not done.is_set():
                if not queue:
                    wake.clear()
                    if not queue:
                        await wake.wait()
                    continue
                seq, capture_ms, pcm = queue.popleft()
                arrived = time.perf_counter()
                try:
                    result, audio = await worker.request("push", {}, pcm, timeout=30)
                except WorkerFailure as exc:
                    log.warning("conversion failed: %s %s", exc.code, exc)
                    failure.append(exc.code)
                    done.set()
                    return
                silent = bool(result["silent"])
                proc_ms = float(result["proc_ms"])
                if silent:
                    metrics.silent += 1
                else:
                    metrics.converted += 1
                    metrics.proc.append(proc_ms)
                metrics.server.append((time.perf_counter() - arrived) * 1000)
                if send_vmic["on"]:
                    if delayed:
                        # Much slower than real time, blocks would play as bursts between long gaps.
                        # Hold each phrase and release it whole, so what comes out is continuous.
                        phrase.append(audio)
                        if silent:
                            vmic_queue.put_nowait(b"".join(phrase))
                            phrase.clear()
                    else:
                        vmic_queue.put_nowait(audio)
                queue_ms = len(queue) * metrics.block_ms
                header = _DOWN.pack(seq, _FLAG_SILENCE if silent else 0, capture_ms, proc_ms, queue_ms)
                try:
                    await ws.send_bytes(header + audio)
                except (WebSocketDisconnect, RuntimeError):
                    done.set()
                    return

        async def vmic_writer() -> None:
            # A long block can take longer to write than PipeWire's pipe holds at once, and
            # waiting for that must never delay the next conversion.
            while True:
                await vmic.write(await vmic_queue.get(), rate)
                vmic_queue.task_done()

        async def stats_loop() -> None:
            while not done.is_set():
                await asyncio.sleep(_STATS_EVERY_S)
                if self._stop_requested:
                    done.set()
                    try:
                        await ws.close()
                    except RuntimeError:
                        pass
                    return
                try:
                    await ws.send_json({"type": "stats", **metrics.as_dict()})
                except (WebSocketDisconnect, RuntimeError):
                    done.set()
                    return

        tasks = [asyncio.create_task(converter()), asyncio.create_task(stats_loop())]
        writer_task = asyncio.create_task(vmic_writer())
        try:
            while not done.is_set():
                receive = asyncio.create_task(ws.receive())
                finished = asyncio.create_task(done.wait())
                await asyncio.wait({receive, finished}, return_when=asyncio.FIRST_COMPLETED)
                finished.cancel()
                if not receive.done():
                    receive.cancel()
                    break
                message = receive.result()
                if message["type"] == "websocket.disconnect":
                    break
                raw = message.get("bytes")
                if raw is not None:
                    if len(raw) != _UP.size + block_bytes:
                        continue  # malformed block: drop it rather than feed the model garbage
                    seq, _flags, capture_ms = _UP.unpack_from(raw)
                    metrics.received += 1
                    metrics.note_seq(seq)
                    queue.append((seq, capture_ms, raw[_UP.size:]))
                    while len(queue) > max_backlog:
                        queue.popleft()
                        metrics.dropped += 1
                    wake.set()
                    continue
                text = message.get("text")
                if not text:
                    continue
                try:
                    control = json.loads(text)
                except ValueError:
                    continue
                kind = control.get("type")
                if kind == "stop":
                    break
                if kind == "client_stats":
                    metrics.client_latency_p50 = _number(control.get("latency_ms_p50"))
                    metrics.client_latency_p95 = _number(control.get("latency_ms_p95"))
                    metrics.underruns = int(_number(control.get("underruns")) or 0)
                elif kind == "set_virtual_mic":
                    send_vmic["on"] = bool(control.get("enabled"))
                    if send_vmic["on"] and not vmic.enabled:
                        try:
                            await vmic.enable()
                        except VirtualMicError as exc:
                            send_vmic["on"] = False
                            await ws.send_json({"type": "status", "stage": f"Virtual microphone unavailable: {exc.code}"})
                    elif not send_vmic["on"]:
                        await vmic.release_stream()
                elif kind == "set_target":
                    await self._switch_target(ws, worker, operator, control.get("profile_id"), queue, delayed)
        except WebSocketDisconnect:
            pass
        finally:
            done.set()
            wake.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if phrase and send_vmic["on"]:  # speech that ended with the session, not with a pause
                vmic_queue.put_nowait(b"".join(phrase))
                phrase.clear()
            try:
                await asyncio.wait_for(vmic_queue.join(), 15)
            except asyncio.TimeoutError:
                pass
            writer_task.cancel()
            await asyncio.gather(writer_task, return_exceptions=True)
        return failure[0] if failure else None

    async def _switch_target(self, ws: WebSocket, worker: WorkerProcess, operator: User, raw_id: object,
                             queue: deque, delayed: bool) -> None:
        try:
            profile_id = uuid.UUID(str(raw_id))
        except ValueError:
            return
        reference = await self._reference_for(operator.id, profile_id)
        if reference is None:
            await ws.send_json({"type": "status", "stage": "That voice isn't ready, so the current voice stays on."})
            return
        if not delayed:
            queue.clear()  # live: audio still waiting is stale. Delayed mode promises every word.
        try:
            await worker.request("set_target", {"reference": str(reference)}, timeout=60)
        except WorkerFailure as exc:
            await ws.send_json({"type": "status", "stage": f"Couldn't switch voice: {exc.code}"})
            return
        self.active_profile_id = profile_id
        await ws.send_json({"type": "target_changed", "profile_id": str(profile_id)})

    @staticmethod
    async def _open_record(user_id: uuid.UUID, profile_id: uuid.UUID, spec, device: str, vmic: bool) -> uuid.UUID:
        async with db_session.async_session_maker() as session:
            record = VoiceConversionSession(
                user_id=user_id, profile_id=profile_id, engine_id=spec.id, engine_version=spec.revision,
                device=device, virtual_mic=vmic,
            )
            session.add(record)
            session.add(AuditLog(actor_id=user_id, action="voice.conversion_started",
                                 detail={"profile_id": str(profile_id), "engine": spec.id, "virtual_mic": vmic}))
            await session.commit()
            return record.id

    @staticmethod
    async def _close_record(session_id: uuid.UUID, metrics: SessionMetrics, error: str | None) -> None:
        async with db_session.async_session_maker() as session:
            record = await session.get(VoiceConversionSession, session_id)
            if record:
                record.status = "failed" if error else "stopped"
                record.error = error or ""
                record.stats = metrics.as_dict()
                record.ended_at = datetime.now(timezone.utc)
                await session.commit()


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _realtime_summary(metrics: SessionMetrics, device: str) -> dict:
    data = metrics.as_dict()
    factor = data["realtime_factor"]
    if factor is None:
        return {"summary": f"No speech converted yet on {device}."}
    return {"summary": f"{factor}× real time on {device}, {data['proc_ms_avg']} ms per {data['block_ms']} ms block, "
                       f"{data['dropped']} blocks dropped", **data}


async def _send_error(ws: WebSocket, code: str, message: str = "") -> None:
    try:
        await ws.send_json({"type": "error", "code": code, "message": message[:500]})
        await ws.close(code=4400)
    except (RuntimeError, WebSocketDisconnect):
        pass


_realtime: RealtimeAudioService | None = None


def get_realtime() -> RealtimeAudioService:
    global _realtime
    if _realtime is None:
        _realtime = RealtimeAudioService()
    return _realtime
