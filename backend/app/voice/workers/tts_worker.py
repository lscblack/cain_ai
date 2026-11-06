"""Voice cloning and text-to-speech worker. Runs inside the kai_voice_tts environment."""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _runtime  # noqa: E402
from _runtime import WorkerError  # noqa: E402
from _text import chunk_text, max_speech_seconds  # noqa: E402

_PAUSE_S = {"none": 0.0, "sentence": 0.14, "paragraph": 0.42}
_EDGE_FADE_S = 0.012
_ASR_MODEL = "base"
_TARGET_RMS = 0.11
_CODEC_FRAMES_PER_S = 12


def _decode(path: str, rate: int) -> np.ndarray:
    """Decode anything FFmpeg understands (including browser WebM/Opus) to mono float."""
    import av

    container = av.open(path)
    stream = next((s for s in container.streams if s.type == "audio"), None)
    if stream is None:
        raise WorkerError("no_audio_stream", "That file has no audio track.")
    resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
    parts = []
    try:
        for frame in container.decode(stream):
            for converted in resampler.resample(frame):
                parts.append(converted.to_ndarray().reshape(-1).copy())
        for converted in resampler.resample(None):
            parts.append(converted.to_ndarray().reshape(-1).copy())
    except av.error.FFmpegError as exc:
        raise WorkerError("audio_decode_failed", "That audio file could not be decoded.") from exc
    finally:
        container.close()
    if not parts:
        raise WorkerError("audio_decode_failed", "That audio file contains no samples.")
    return np.concatenate(parts).astype(np.float32)


def _fade_edges(audio: np.ndarray, rate: int) -> np.ndarray:
    n = min(int(rate * _EDGE_FADE_S), len(audio) // 2)
    if n:
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        audio = audio.copy()
        audio[:n] *= ramp
        audio[-n:] *= ramp[::-1]
    return audio


def _level(audio: np.ndarray) -> np.ndarray:
    """Even out loudness between chunks so joined speech sounds like one recording."""
    voiced = audio[np.abs(audio) > 0.01]
    if len(voiced) == 0:
        return audio
    gain = _TARGET_RMS / max(float(np.sqrt(np.mean(voiced ** 2))), 1e-5)
    return audio * float(np.clip(gain, 0.35, 4.0))


def _trim_silence(audio: np.ndarray, rate: int, threshold: float = 0.004) -> np.ndarray:
    """Remove the silence a model leaves at chunk edges so pauses come only from the text."""
    frame = max(1, int(rate * 0.01))
    energy = np.sqrt(np.convolve(audio ** 2, np.ones(frame) / frame, mode="same"))
    voiced = np.nonzero(energy > threshold)[0]
    if len(voiced) == 0:
        return audio
    margin = int(rate * 0.03)
    return audio[max(0, voiced[0] - margin): min(len(audio), voiced[-1] + margin)]


class Worker:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.model = None
        self.model_id: str | None = None
        self.device = "cpu"
        self.vad = None
        self.asr = None

    def _torch(self):
        import torch

        torch.set_num_threads(self.args.threads)
        return torch

    def health(self, ctx, args, payload):
        torch = self._torch()
        info = {"torch": torch.__version__, "cuda_available": torch.cuda.is_available(),
                "torch_cuda": torch.version.cuda, "loaded": self.model_id, "device": self.device}
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
        model_id = args["model_id"]
        if self.model is not None and self.model_id == model_id:
            return {"model_id": model_id, "device": self.device}
        self.unload(ctx, {}, b"")
        torch = self._torch()
        requested = args.get("device", "auto")
        if requested == "cuda" and not torch.cuda.is_available():
            raise WorkerError("cuda_unavailable", "CUDA was requested but PyTorch cannot use it")
        self.device = "cuda:0" if requested != "cpu" and torch.cuda.is_available() else "cpu"
        from qwen_tts import Qwen3TTSModel

        started = time.monotonic()
        dtype = torch.bfloat16 if self.device != "cpu" else torch.float32
        self.model = Qwen3TTSModel.from_pretrained(
            args["path"], device_map=self.device, dtype=dtype, attn_implementation="sdpa",
        )
        self.model_id = model_id
        return {"model_id": model_id, "device": self.device, "load_s": round(time.monotonic() - started, 1)}

    def unload(self, ctx, args, payload):
        had = self.model is not None
        self.model = None
        self.model_id = None
        if had:
            import gc

            gc.collect()
            torch = self._torch()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        return {"loaded": None}

    def _require(self, model_id: str):
        if self.model is None or self.model_id != model_id:
            raise WorkerError("model_not_loaded", f"{model_id} is not loaded")
        return self.model

    def _speech_seconds(self, audio: np.ndarray, rate: int) -> tuple[float, list[dict]]:
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad

        if self.vad is None:
            self.vad = load_silero_vad(onnx=True)
        segments = get_speech_timestamps(torch.from_numpy(audio), self.vad, sampling_rate=rate)
        return sum(s["end"] - s["start"] for s in segments) / rate, segments

    def normalize(self, ctx, args, payload):
        """Source recording → clean mono reference. Keeps the file's own speech, nothing invented."""
        import soundfile as sf

        rate = int(args["rate"])
        audio = _decode(args["src"], 16000)
        speech_s, segments = self._speech_seconds(audio, 16000)
        audio = _decode(args["src"], rate)
        clipped = float(np.mean(np.abs(audio) >= 0.999))
        max_samples = int(float(args.get("max_s", 30)) * rate)
        truncated = False
        if segments:
            scale = rate / 16000
            pad = int(0.1 * rate)
            start = max(0, int(segments[0]["start"] * scale) - pad)
            end = min(len(audio), int(segments[-1]["end"] * scale) + pad)
            # Too long: stop at the last pause that fits, so no word is cut in half.
            fitting = [s for s in segments if int(s["end"] * scale) + pad - start <= max_samples]
            if end - start > max_samples:
                truncated = True
                end = int(fitting[-1]["end"] * scale) + pad if fitting else start + max_samples
            audio = audio[start:end]
        if len(audio) > max_samples:
            truncated = True
            audio = audio[:max_samples]
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        if peak > 1e-4:
            audio = audio * (0.89 / peak)
        sf.write(args["dst"], audio, rate, subtype="PCM_16")
        return {"duration_s": round(len(audio) / rate, 3), "speech_s": round(speech_s, 3),
                "sample_rate": rate, "clipped_ratio": round(clipped, 5), "peak_before": round(peak, 4), "truncated": truncated}

    def transcribe(self, ctx, args, payload):
        """Optional text only. Live conversion never goes through here."""
        from faster_whisper import WhisperModel

        if self.asr is None:
            self.asr = WhisperModel(_ASR_MODEL, device="cpu", compute_type="int8", cpu_threads=self.args.threads,
                                    download_root=self.args.asr_dir)
        language = args.get("language")
        language = None if not language or language == "auto" else _WHISPER_LANG.get(language.lower())
        # Samples, not a path: faster-whisper's own decoder passes an argument newer PyAV removed.
        segments, info = self.asr.transcribe(_decode(args["path"], 16000), language=language, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"text": text, "language": info.language, "language_probability": round(info.language_probability, 3)}

    def create_prompt(self, ctx, args, payload):
        torch = self._torch()
        model = self._require(args["model_id"])
        transcript = (args.get("transcript") or "").strip()
        # Without a transcript the model can only use the speaker embedding: weaker, but it works.
        x_vector_only = not transcript
        started = time.monotonic()
        items = model.create_voice_clone_prompt(
            ref_audio=args["ref"], ref_text=transcript or None, x_vector_only_mode=x_vector_only,
        )
        data = []
        for item in items:
            record = dataclasses.asdict(item)
            data.append({k: (v.cpu() if isinstance(v, torch.Tensor) else v) for k, v in record.items()})
        torch.save({"format": 1, "model_id": args["model_id"], "items": data}, args["out"])
        return {"mode": "x_vector" if x_vector_only else "full", "device": self.device,
                "seconds": round(time.monotonic() - started, 1)}

    def _load_prompt(self, path: str, model_id: str):
        torch = self._torch()
        from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem

        stored = torch.load(path, map_location="cpu", weights_only=True)
        if stored.get("model_id") != model_id:
            raise WorkerError("representation_model_mismatch", "This voice was built for another model.")
        items = []
        for record in stored["items"]:
            items.append(VoiceClonePromptItem(**{
                k: (v.to(self.device) if isinstance(v, torch.Tensor) else v) for k, v in record.items()
            }))
        return items

    def generate(self, ctx, args, payload):
        import soundfile as sf

        torch = self._torch()
        from transformers import StoppingCriteria, StoppingCriteriaList

        model = self._require(args["model_id"])
        prompt = self._load_prompt(args["prompt"], args["model_id"])
        chunks = chunk_text(args["text"], limit=int(args.get("chunk_chars", 300)))
        if not chunks:
            raise WorkerError("text_required", "There is no text to speak.")
        if args.get("seed") is not None:
            torch.manual_seed(int(args["seed"]))

        class StopOnCancel(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return torch.full((input_ids.shape[0],), ctx.cancel.is_set(), dtype=torch.bool, device=input_ids.device)

        started = time.monotonic()
        parts: list[np.ndarray] = []
        rate = 24000
        language = args.get("language") or "auto"
        for index, chunk in enumerate(chunks):
            ctx.check_cancel()
            with torch.inference_mode():
                wavs, rate = model.generate_voice_clone(
                    text=chunk.text, language=language, voice_clone_prompt=prompt,
                    temperature=args.get("temperature"), top_p=args.get("top_p"),
                    max_new_tokens=int(max_speech_seconds(chunk.text) * _CODEC_FRAMES_PER_S),
                    stopping_criteria=StoppingCriteriaList([StopOnCancel()]),
                )
            ctx.check_cancel()
            audio = _fade_edges(_level(_trim_silence(np.asarray(wavs[0], dtype=np.float32), rate)), rate)
            parts.append(audio)
            pause = _PAUSE_S[chunk.pause]
            if pause:
                parts.append(np.zeros(int(rate * pause), dtype=np.float32))
            ctx.event(progress=round((index + 1) / len(chunks) * 0.97, 3))

        audio = np.concatenate(parts)
        speed = float(args.get("speed") or 1.0)
        pitch = float(args.get("pitch_semitones") or 0.0)
        if abs(speed - 1.0) > 1e-3 or abs(pitch) > 1e-3:
            import librosa

            if abs(pitch) > 1e-3:
                audio = librosa.effects.pitch_shift(audio, sr=rate, n_steps=pitch)
            if abs(speed - 1.0) > 1e-3:
                audio = librosa.effects.time_stretch(audio, rate=speed)
        peak = float(np.max(np.abs(audio)))
        if peak > 0.98:
            audio = audio * (0.98 / peak)
        sf.write(args["out_wav"], audio, rate, subtype="PCM_16")
        sf.write(args["out_mp3"], audio, rate, format="MP3")
        return {"duration_s": round(len(audio) / rate, 3), "sample_rate": rate, "chunks": len(chunks),
                "device": self.device, "inference_s": round(time.monotonic() - started, 2)}

    def probe_inference(self, ctx, args, payload):
        """Health check: real inference, checked for real output."""
        model = self._require(args["model_id"])
        started = time.monotonic()
        import numpy as _np

        rate = 24000
        t = _np.arange(rate * 3) / rate
        reference = 0.2 * _np.sin(2 * _np.pi * 150 * t).astype(_np.float32)
        with self._torch().inference_mode():
            wavs, rate = model.generate_voice_clone(
                text="Test.", language="english", ref_audio=(reference, rate), x_vector_only_mode=True,
                max_new_tokens=48,
            )
        samples = len(wavs[0])
        if samples == 0:
            raise WorkerError("inference_failed", "The model returned no audio.")
        return {"ok": True, "samples": samples, "device": self.device, "seconds": round(time.monotonic() - started, 1)}


_WHISPER_LANG = {
    "english": "en", "chinese": "zh", "french": "fr", "german": "de", "italian": "it", "japanese": "ja",
    "korean": "ko", "portuguese": "pt", "russian": "ru", "spanish": "es",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--asr-dir", default=None)
    worker = Worker(parser.parse_args())
    _runtime.serve({
        "health": worker.health, "load": worker.load, "unload": worker.unload, "normalize": worker.normalize,
        "transcribe": worker.transcribe, "create_prompt": worker.create_prompt, "generate": worker.generate,
        "probe_inference": worker.probe_inference,
    })


if __name__ == "__main__":
    main()
