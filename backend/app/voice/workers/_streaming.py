"""Engine-independent streaming helpers. Needs numpy only.

Converting one block at a time gives audible seams, because each inference ends at a
slightly different phase. SOLA hides them: every inference returns a little extra audio,
the new audio is aligned to where the previous block ended using cross-correlation, and
the overlap is crossfaded.
"""
from __future__ import annotations

import numpy as np


class ContextBuffer:
    """The last ``size`` input samples, oldest first."""

    def __init__(self, size: int) -> None:
        self.data = np.zeros(size, dtype=np.float32)

    def push(self, block: np.ndarray) -> np.ndarray:
        n = len(block)
        if n >= len(self.data):
            self.data[:] = block[-len(self.data):]
        else:
            self.data[:-n] = self.data[n:]
            self.data[-n:] = block
        return self.data


class Sola:
    def __init__(self, block: int, crossfade: int, search: int) -> None:
        self.block = block
        self.crossfade = crossfade
        self.search = search
        self.required = block + crossfade + search
        self.tail = np.zeros(crossfade, dtype=np.float32)
        self.has_tail = False
        phase = np.linspace(0, np.pi / 2, crossfade, dtype=np.float32)
        # Equal power: the two sides are not phase coherent after a voice change.
        self.fade_in = np.sin(phase)
        self.fade_out = np.cos(phase)

    def reset(self) -> None:
        self.tail[:] = 0
        self.has_tail = False

    def best_offset(self, audio: np.ndarray) -> int:
        if not self.has_tail or self.search == 0:
            return 0
        window = audio[: self.crossfade + self.search]
        numerator = np.correlate(window, self.tail, mode="valid")
        energy = np.cumsum(window ** 2)
        energy_windows = energy[self.crossfade - 1:] - np.concatenate(([0.0], energy[:-self.crossfade]))
        scores = numerator / (np.sqrt(np.maximum(energy_windows, 1e-8)))
        return int(np.argmax(scores))

    def process(self, audio: np.ndarray) -> np.ndarray:
        if len(audio) < self.required:
            audio = np.pad(audio, (self.required - len(audio), 0))
        offset = self.best_offset(audio)
        audio = audio[offset:]
        out = audio[: self.block].copy()
        if self.has_tail:
            out[: self.crossfade] = out[: self.crossfade] * self.fade_in + self.tail * self.fade_out
        else:
            out[: self.crossfade] *= self.fade_in
        self.tail[:] = audio[self.block: self.block + self.crossfade]
        self.has_tail = True
        return out

    def fade_to_silence(self) -> np.ndarray:
        """First silent block after speech: let the stored tail die away, no click."""
        out = np.zeros(self.block, dtype=np.float32)
        out[: self.crossfade] = self.tail * self.fade_out
        self.reset()
        return out


class SpeechGate:
    """Holds the gate open after speech so word endings and short pauses are not cut."""

    def __init__(self, hangover_blocks: int) -> None:
        self.hangover = hangover_blocks
        self.remaining = 0

    def update(self, is_speech: bool) -> bool:
        if is_speech:
            self.remaining = self.hangover
            return True
        if self.remaining > 0:
            self.remaining -= 1
            return True
        return False


def to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def from_pcm16(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
