#!/usr/bin/env python3
"""End-to-end check of Voice Intelligence against a running KAI backend, with real models.

Run with the backend's environment. Nothing is faked: a stage passes only if audio really
came back and was decoded. Latency and speed are measured here, on this run.

    kai_voice_verify.py clone  --reference a.wav [--transcript "..."] --name "Test A"
    kai_voice_verify.py tts    --name "Test A" --text "Hello there." --out out.wav
    kai_voice_verify.py live   --name "Test A" --source speech.wav --out converted.wav [--switch-to "Test B"]
                               [--delayed] [--virtual-mic captured.wav]
    kai_voice_verify.py delete --name "Test A"
"""
from __future__ import annotations

import argparse
import asyncio
import atexit
import json
import os
import struct
import subprocess
import sys
import time

import httpx
import numpy as np
import soundfile as sf
import websockets

UP = struct.Struct("<IId")
DOWN = struct.Struct("<IIdff")
OK = "PASS"
BAD = "FAIL"


def report(ok: bool, message: str) -> None:
    print(f"[{OK if ok else BAD}] {message}", flush=True)
    if not ok:
        sys.exit(1)


class Kai:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(base_url=self.base, timeout=120)
        token = os.environ.get("KAI_TOKEN")
        if not token:
            response = self.http.post("/auth/open")
            response.raise_for_status()
            token = response.json()["access_token"]
        self.token = token
        self.http.headers["Authorization"] = f"Bearer {token}"

    def voice(self, name: str) -> dict:
        for profile in self.http.get("/voice/profiles").json()["profiles"]:
            if profile["name"] == name:
                return profile
        raise SystemExit(f"[{BAD}] no voice named {name!r}")


def decode_check(data: bytes, suffix: str, path: str) -> tuple[float, float]:
    with open(path, "wb") as fh:
        fh.write(data)
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    return len(audio) / rate, float(np.sqrt(np.mean(audio ** 2)))


def cmd_clone(kai: Kai, args: argparse.Namespace) -> None:
    started = time.monotonic()
    with open(args.reference, "rb") as fh:
        response = kai.http.post("/voice/profiles", data={
            "name": args.name, "transcript": args.transcript or "", "consent_confirmed": "true",
            "consent_basis": "permission", "consent_subject": "Verification script test speaker",
        }, files={"file": (os.path.basename(args.reference), fh, "application/octet-stream")})
    report(response.status_code == 201, f"upload accepted ({response.status_code}) {response.text[:200] if response.status_code != 201 else ''}")
    profile = response.json()
    while profile["status"] == "processing":
        time.sleep(1)
        profile = kai.http.get(f"/voice/profiles/{profile['id']}").json()
        if time.monotonic() - started > 1200:
            report(False, "cloning timed out")
    report(profile["status"] == "ready", f"voice ready in {time.monotonic() - started:.1f}s: {profile['status_detail']}")
    print(f"       model={profile['model_id']} mode={profile['meta'].get('clone_mode')} duration={profile['duration_s']}s")
    print(f"       transcript: {profile['transcript'][:120]}")


def cmd_tts(kai: Kai, args: argparse.Namespace) -> None:
    profile = kai.voice(args.name)
    report(profile["status"] == "ready", f"voice {args.name!r} loaded from the database")
    response = kai.http.post("/voice/tts/generate", json={
        "profile_id": profile["id"], "text": args.text, "language": args.language, "speed": args.speed,
        "pitch_semitones": args.pitch, "seed": 7,
    })
    report(response.status_code == 202, f"generation queued {response.text[:200] if response.status_code != 202 else ''}")
    generation = response.json()
    seen_progress = False
    while generation["status"] in ("queued", "running"):
        time.sleep(1)
        generation = kai.http.get(f"/voice/generations/{generation['id']}").json()
        seen_progress = seen_progress or generation["progress"] > 0
        if args.cancel_after and generation["status"] == "running":
            time.sleep(args.cancel_after)
            kai.http.post(f"/voice/generations/{generation['id']}/cancel")
            args.cancel_after = 0
    if args.expect_cancel:
        report(generation["status"] == "canceled", f"generation canceled (status={generation['status']}, {generation['error']})")
        return
    report(generation["status"] == "completed", f"generation finished: {generation['status']} {generation['error']}")
    print(f"       {generation['duration_s']}s of audio in {generation['inference_s']:.1f}s on {generation['device']} "
          f"({generation['inference_s'] / max(generation['duration_s'], 0.01):.2f}× real time)")
    for fmt in ("wav", "mp3"):
        audio = kai.http.get(f"/voice/generations/{generation['id']}/audio?format={fmt}")
        report(audio.status_code == 200, f"{fmt} downloaded, {len(audio.content)} bytes")
        target = args.out if fmt == "wav" else args.out.rsplit(".", 1)[0] + ".mp3"
        duration, level = decode_check(audio.content, fmt, target)
        report(duration > 0.2 and level > 0.005, f"{fmt} decodes and has sound: {duration:.2f}s rms={level:.3f}")


async def stream_session(kai: Kai, args: argparse.Namespace, profile_id: str, audio_path: str | None,
                         silence_s: float, switch_to: str | None, delayed: bool) -> dict:
    url = kai.base.replace("http", "ws", 1) + "/voice/conversion/ws"
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "token": kai.token, "profile_id": profile_id,
                                  "virtual_mic": bool(args.virtual_mic), "mode": "delayed" if delayed else "live"}))
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), 900))
            if message["type"] == "ready":
                break
            if message["type"] == "too_slow":
                return {"too_slow": message}
            if message["type"] == "error":
                raise SystemExit(f"[{BAD}] {message}")
            print(f"       {message.get('stage')}", flush=True)
        rate, block = message["sample_rate"], message["block_samples"]
        print(f"       ready: {message['engine']} on {message['device']}, {rate} Hz, "
              f"{block / rate * 1000:.0f} ms blocks, calibration {message['calibration']}", flush=True)

        speech = np.zeros(0, dtype=np.float32)
        if audio_path:
            import librosa

            speech, _ = librosa.load(audio_path, sr=rate, mono=True, duration=args.seconds)
        pcm = np.concatenate([np.zeros(int(silence_s * rate), dtype=np.float32), speech])
        total_blocks = len(pcm) // block

        received: list[tuple[int, int, float, float, np.ndarray]] = []
        stats: dict = {}
        target_changed = asyncio.Event()
        finished = asyncio.Event()

        async def receiver() -> None:
            nonlocal stats
            async for frame in ws:
                if isinstance(frame, bytes):
                    seq, flags, capture_ms, proc_ms, queue_ms = DOWN.unpack_from(frame)
                    audio = np.frombuffer(frame, dtype="<i2", offset=DOWN.size).astype(np.float32) / 32768
                    received.append((seq, flags, time.perf_counter() * 1000 - capture_ms, proc_ms, audio))
                    if seq == total_blocks - 1:
                        finished.set()
                else:
                    message = json.loads(frame)
                    if message["type"] == "target_changed":
                        target_changed.set()
                    elif message["type"] in ("stats", "stopped"):
                        stats = message.get("stats", message)
                    elif message["type"] == "error":
                        print(f"       server error: {message}", flush=True)
            finished.set()

        receive_task = asyncio.create_task(receiver())
        started = time.perf_counter()
        switched_at = None
        for seq in range(total_blocks):
            # Paced like a microphone: one block per block's worth of wall clock.
            await asyncio.sleep(max(0.0, started + seq * block / rate - time.perf_counter()))
            samples = pcm[seq * block: (seq + 1) * block]
            payload = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
            await ws.send(UP.pack(seq, 0, time.perf_counter() * 1000) + payload)
            if switch_to and seq == total_blocks // 2:
                switched_at = seq
                await ws.send(json.dumps({"type": "set_target", "profile_id": switch_to}))
        wait = float(args.drain_s)
        try:
            await asyncio.wait_for(finished.wait(), wait)
        except asyncio.TimeoutError:
            pass
        if switched_at is not None:
            report(target_changed.is_set(), "target voice changed during the session")
        await ws.send(json.dumps({"type": "stop"}))
        try:
            await asyncio.wait_for(receive_task, 30)
        except asyncio.TimeoutError:
            receive_task.cancel()
    return {"received": received, "rate": rate, "block": block, "total_blocks": total_blocks, "stats": stats}


def summarize(result: dict, label: str, out: str | None) -> None:
    received = result["received"]
    rate, block = result["rate"], result["block"]
    report(len(received) > 0, f"{label}: converted audio came back ({len(received)} of {result['total_blocks']} blocks)")
    seqs = [r[0] for r in received]
    report(seqs == sorted(seqs), f"{label}: blocks arrived in order")
    speech = [r for r in received if not r[1] & 1]
    silent = [r for r in received if r[1] & 1]
    print(f"       speech blocks={len(speech)} silent blocks={len(silent)}")
    if speech:
        trip = np.array([r[2] for r in speech])
        proc = np.array([r[3] for r in speech])
        block_ms = block / rate * 1000
        print(f"       round trip per block: p50={np.median(trip):.0f} ms p95={np.percentile(trip, 95):.0f} ms | "
              f"inference: p50={np.median(proc):.0f} ms p95={np.percentile(proc, 95):.0f} ms | block={block_ms:.0f} ms | "
              f"speed={block_ms / np.median(proc):.2f}× real time")
    # The first silent block after speech carries the crossfade tail, by design. The rest must be exact zero.
    ordered = sorted(received, key=lambda r: r[0])
    true_silence = [r for prev, r in zip([None] + ordered, ordered) if r[1] & 1 and (prev is None or prev[1] & 1)]
    if true_silence:
        peak = max(float(np.max(np.abs(r[4]))) for r in true_silence)
        report(peak == 0.0, f"{label}: silence stays silent ({len(true_silence)} blocks, peak {peak})")
    print(f"       server stats: {result['stats']}")
    if out:
        ordered = sorted(received, key=lambda r: r[0])
        sf.write(out, np.concatenate([r[4] for r in ordered]), rate, subtype="PCM_16")
        print(f"       wrote {out}")


def cmd_live(kai: Kai, args: argparse.Namespace) -> None:
    profile = kai.voice(args.name)
    other = kai.voice(args.switch_to)["id"] if args.switch_to else None
    capture = None
    if args.virtual_mic:
        kai.http.put("/voice/conversion/virtual-mic", json={"enabled": True}).raise_for_status()
        status = kai.http.get("/voice/conversion/status").json()["virtual_mic"]
        report(status["enabled"], f"virtual microphone exists: {status['source_name']}")
        capture = subprocess.Popen(["pw-record", "--target", status["source_name"], "--rate", "48000",
                                    "--channels", "1", args.virtual_mic],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        atexit.register(capture.terminate)  # a failed stage must not leave a recorder running
        time.sleep(0.5)

    print("Session 1: real speech, after a stretch of silence", flush=True)
    result = asyncio.run(stream_session(kai, args, profile["id"], args.source, args.silence, other, args.delayed))
    if "too_slow" in result:
        info = result["too_slow"]
        report(False, f"hardware cannot do this live: {info['proc_ms']:.0f} ms to convert {info['block_ms']:.0f} ms "
                      f"on {info['device']} ({info['block_ms'] / info['proc_ms']:.2f}× real time). Rerun with --delayed to test the pipeline.")
    summarize(result, "session 1", args.out)

    status = kai.http.get("/voice/conversion/status").json()
    report(not status["active"], "conversion stopped: no session left active")

    print("Session 2: restart after stop", flush=True)
    args2 = argparse.Namespace(**{**vars(args), "seconds": min(args.seconds, 2.0), "virtual_mic": args.virtual_mic})
    result = asyncio.run(stream_session(kai, args2, profile["id"], args.source, 0.0, None, args.delayed))
    summarize(result, "session 2", None)

    sessions = kai.http.get("/voice/conversion/sessions?limit=2").json()["sessions"]
    report(len(sessions) == 2 and all(s["status"] == "stopped" for s in sessions), "both sessions recorded as stopped")
    if capture:
        time.sleep(1)
        capture.terminate()
        capture.wait(5)
        kai.http.put("/voice/conversion/virtual-mic", json={"enabled": False}).raise_for_status()
        audio, _ = sf.read(args.virtual_mic, dtype="float32")
        level = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
        report(level > 0.002, f"virtual microphone carried the converted voice: {len(audio) / 48000:.1f}s rms={level:.4f}")


def cmd_delete(kai: Kai, args: argparse.Namespace) -> None:
    profile = kai.voice(args.name)
    response = kai.http.delete(f"/voice/profiles/{profile['id']}")
    report(response.status_code == 200, f"deleted {args.name!r}: {response.text[:120]}")
    gone = kai.http.get(f"/voice/profiles/{profile['id']}")
    report(gone.status_code == 404, "profile is gone")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=os.environ.get("KAI_VOICE_BASE", "http://127.0.0.1:8008"))
    sub = parser.add_subparsers(dest="command", required=True)
    clone = sub.add_parser("clone")
    clone.add_argument("--reference", required=True)
    clone.add_argument("--transcript", default="")
    clone.add_argument("--name", required=True)
    tts = sub.add_parser("tts")
    tts.add_argument("--name", required=True)
    tts.add_argument("--text", required=True)
    tts.add_argument("--language", default="auto")
    tts.add_argument("--speed", type=float, default=1.0)
    tts.add_argument("--pitch", type=float, default=0.0)
    tts.add_argument("--out", default="tts.wav")
    tts.add_argument("--cancel-after", type=float, default=0)
    tts.add_argument("--expect-cancel", action="store_true")
    live = sub.add_parser("live")
    live.add_argument("--name", required=True)
    live.add_argument("--source", required=True)
    live.add_argument("--out", default="converted.wav")
    live.add_argument("--seconds", type=float, default=6.0)
    live.add_argument("--silence", type=float, default=1.0)
    live.add_argument("--switch-to")
    live.add_argument("--delayed", action="store_true", help="test the pipeline when the hardware is too slow for live")
    live.add_argument("--virtual-mic", help="record the virtual microphone's output to this file")
    live.add_argument("--drain-s", type=float, default=900)
    delete = sub.add_parser("delete")
    delete.add_argument("--name", required=True)
    args = parser.parse_args()
    kai = Kai(args.base)
    {"clone": cmd_clone, "tts": cmd_tts, "live": cmd_live, "delete": cmd_delete}[args.command](kai, args)


if __name__ == "__main__":
    main()
