"""Real-time voice conversion worker. Runs inside the kai_voice_vc environment.

Each ``push`` is one microphone block; the reply is that block's converted audio. Silence
never reaches the model, so the CPU rests between phrases and quiet does not turn into
synthesized noise.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _runtime  # noqa: E402
from _runtime import WorkerError  # noqa: E402
from _streaming import ContextBuffer, Sola, SpeechGate, from_pcm16, rms, to_pcm16  # noqa: E402

_VAD_RATE = 16000
_VAD_WINDOW = 512
_SPEECH_THRESHOLD = 0.4
_HANGOVER_S = 0.35
_MIN_RMS = 0.002


class Vad:
    def __init__(self, sample_rate: int) -> None:
        from silero_vad import load_silero_vad

        import torchaudio

        self._model = load_silero_vad(onnx=True)
        self._resampler = torchaudio.transforms.Resample(sample_rate, _VAD_RATE)
        self._rest = np.zeros(0, dtype=np.float32)

    def reset(self) -> None:
        self._model.reset_states()
        self._rest = np.zeros(0, dtype=np.float32)

    def is_speech(self, block: np.ndarray) -> bool:
        import torch

        audio = np.concatenate([self._rest, self._resampler(torch.from_numpy(block)).numpy()])
        windows = len(audio) // _VAD_WINDOW
        self._rest = audio[windows * _VAD_WINDOW:]
        best = 0.0
        for i in range(windows):
            chunk = torch.from_numpy(audio[i * _VAD_WINDOW: (i + 1) * _VAD_WINDOW])
            best = max(best, float(self._model(chunk, _VAD_RATE)))
        return best >= _SPEECH_THRESHOLD


class Session:
    def __init__(self, engine, block_s: float, context_s: float | None = None) -> None:
        self.engine = engine
        sr = engine.sample_rate
        self.block = int(sr * block_s)
        self.crossfade = int(sr * engine.crossfade_s)
        self.search = int(sr * engine.search_s)
        self.lookahead = int(sr * engine.lookahead_s)
        self.context = int(sr * (engine.context_s if context_s is None else context_s))
        self.total = self.context + self.block + self.crossfade + self.search + self.lookahead
        self.need = self.block + self.crossfade + self.search
        self.buffer = ContextBuffer(self.total)
        self.sola = Sola(self.block, self.crossfade, self.search)
        self.gate = SpeechGate(max(1, round(_HANGOVER_S / block_s)))
        self.vad = Vad(sr)
        self.was_active = False

    def reset(self) -> None:
        self.buffer.data[:] = 0
        self.sola.reset()
        self.gate.remaining = 0
        self.vad.reset()
        self.engine.reset_stream()
        self.was_active = False

    def push(self, block: np.ndarray) -> tuple[np.ndarray, bool]:
        window = self.buffer.push(block)
        speech = rms(block) >= _MIN_RMS and self.vad.is_speech(block)
        if speech:
            self.engine.observe_speech(block)
        active = self.gate.update(speech)
        if not active:
            if self.was_active:
                self.was_active = False
                return self.sola.fade_to_silence(), True
            return np.zeros(self.block, dtype=np.float32), True
        self.was_active = True
        return self.sola.process(self.engine.convert(window, self.need, self.lookahead)), False


class Worker:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.engine = None
        self.session: Session | None = None
        self.device = "cpu"

    def _torch(self):
        import torch

        torch.set_num_threads(self.args.threads)
        return torch

    def _pick_device(self, requested: str) -> str:
        torch = self._torch()
        if requested == "cpu":
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if requested == "cuda":
            raise WorkerError("cuda_unavailable", "CUDA was requested but PyTorch cannot use it")
        return "cpu"

    def health(self, ctx, args, payload):
        torch = self._torch()
        info = {"torch": torch.__version__, "cuda_available": torch.cuda.is_available(),
                "torch_cuda": torch.version.cuda, "loaded": self.engine.engine_id if self.engine else None,
                "device": self.device}
        if info["cuda_available"]:
            info["gpu"] = torch.cuda.get_device_name(0)
            free, total = torch.cuda.mem_get_info(0)
            info["vram_free_mb"], info["vram_total_mb"] = free // 2**20, total // 2**20
        else:
            try:
                torch.zeros(1).to("cuda")
            except Exception as exc:  # noqa: BLE001 — the reason is what the operator needs
                info["error"] = str(exc).strip().splitlines()[0][:300]
        return info

    def load(self, ctx, args, payload):
        engine_id = args["engine"]
        if self.engine and self.engine.engine_id == engine_id:
            return {"engine": engine_id, "device": self.device, "sample_rate": self.engine.sample_rate}
        self.engine = None
        self.session = None
        self.device = self._pick_device(args.get("device", "auto"))
        started = time.monotonic()
        if engine_id == "openvoice-v2":
            from openvoice_engine import OpenVoiceEngine

            self.engine = OpenVoiceEngine(args["source_dir"], args["weights_dir"], self.device)
        elif engine_id == "seed-vc-tiny":
            from seed_vc_engine import SeedVcEngine

            self.engine = SeedVcEngine(args["source_dir"], args["weights_dir"], self.device,
                                       diffusion_steps=args.get("diffusion_steps", 6))
        else:
            raise WorkerError("unknown_engine", engine_id)
        return {"engine": engine_id, "device": self.device, "sample_rate": self.engine.sample_rate,
                "load_s": round(time.monotonic() - started, 2)}

    def unload(self, ctx, args, payload):
        self.engine = None
        self.session = None
        return {"loaded": None}

    def _require_engine(self):
        if self.engine is None:
            raise WorkerError("model_not_loaded")
        return self.engine

    def set_target(self, ctx, args, payload):
        import soundfile as sf
        import librosa

        engine = self._require_engine()
        audio, rate = sf.read(args["reference"], dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)
        if rate != engine.sample_rate:
            audio = librosa.resample(audio, orig_sr=rate, target_sr=engine.sample_rate)
        started = time.monotonic()
        engine.set_target(audio)
        return {"seconds": round(time.monotonic() - started, 3)}

    def start(self, ctx, args, payload):
        engine = self._require_engine()
        block_s = float(args.get("block_s") or engine.default_block_s)
        self.session = Session(engine, block_s, args.get("context_s"))
        self.session.reset()
        s = self.session
        return {"sample_rate": engine.sample_rate, "block_samples": s.block, "device": self.device,
                "engine": engine.engine_id,
                "lookahead_ms": round(1000 * (s.lookahead + s.crossfade) / engine.sample_rate, 1),
                "window_s": round(s.total / engine.sample_rate, 4),
                "fixed_overhead_s": round((s.crossfade + s.search + s.lookahead) / engine.sample_rate, 4)}

    def calibrate(self, ctx, args, payload):
        """Times real inference on this machine, right now, with the session's own settings."""
        if self.session is None:
            raise WorkerError("session_not_started")
        s = self.session
        rng = np.random.default_rng(0)
        t = np.arange(s.total) / self.engine.sample_rate
        window = (0.1 * np.sin(2 * np.pi * 140 * t) + 0.01 * rng.standard_normal(s.total)).astype(np.float32)
        timings = []
        for _ in range(2):  # the first run also pays for lazy initialization
            started = time.perf_counter()
            self.engine.convert(window, s.need, s.lookahead)
            timings.append((time.perf_counter() - started) * 1000)
        return {"proc_ms": round(timings[-1], 1), "block_ms": round(1000 * s.block / self.engine.sample_rate, 1)}

    def probe_inference(self, ctx, args, payload):
        """Health check: real conversion of a synthetic signal, checked for real output."""
        engine = self._require_engine()
        rate = engine.sample_rate
        t = np.arange(rate * 3) / rate
        engine.set_target((0.2 * np.sin(2 * np.pi * 150 * t)).astype(np.float32))
        session = Session(engine, engine.default_block_s)
        session.reset()
        window = (0.2 * np.sin(2 * np.pi * 180 * (np.arange(session.total) / rate))).astype(np.float32)
        started = time.perf_counter()
        out = engine.convert(window, session.need, session.lookahead)
        elapsed = (time.perf_counter() - started) * 1000
        self.session = None
        engine.reset_stream()
        if len(out) == 0 or not np.isfinite(out).all():
            raise WorkerError("inference_failed", "The model returned no usable audio.")
        return {"ok": True, "samples": len(out), "device": self.device, "proc_ms": round(elapsed, 1),
                "block_ms": round(1000 * session.block / rate, 1)}

    def push(self, ctx, args, payload):
        if self.session is None:
            raise WorkerError("session_not_started")
        started = time.perf_counter()
        out, silent = self.session.push(from_pcm16(payload))
        return ({"silent": silent, "proc_ms": round((time.perf_counter() - started) * 1000, 2)},
                to_pcm16(out))

    def stop(self, ctx, args, payload):
        self.session = None
        return {"stopped": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--cpus", default="", help="comma-separated CPU ids to run on")
    args = parser.parse_args()
    if args.cpus:
        # On a hybrid CPU the thread pool waits for its slowest member, so an efficiency core
        # holds up the whole block. Staying on performance cores makes timing far steadier.
        os.sched_setaffinity(0, {int(c) for c in args.cpus.split(",")})
    worker = Worker(args)
    _runtime.serve({
        "health": worker.health, "load": worker.load, "unload": worker.unload,
        "set_target": worker.set_target, "start": worker.start, "calibrate": worker.calibrate, "probe_inference": worker.probe_inference, "push": worker.push, "stop": worker.stop,
    })


if __name__ == "__main__":
    main()
