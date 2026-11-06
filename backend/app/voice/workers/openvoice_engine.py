"""OpenVoice V2 tone color conversion (MIT). Light enough to run on a CPU.

It changes the timbre of the speaker while keeping their pitch contour, accent and
rhythm. That makes it fast, but a cross-gender conversion is less convincing than with
Seed-VC, which regenerates the voice with a diffusion model.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import torch

_SOURCE_WINDOW_S = 8.0
_SOURCE_UPDATE_EVERY_S = 6.0
_MAX_SOURCE_UPDATES = 3


class OpenVoiceEngine:
    engine_id = "openvoice-v2"
    sample_rate = 22050
    context_s = 1.0
    lookahead_s = 0.03
    crossfade_s = 0.04
    search_s = 0.012
    default_block_s = 0.2

    def __init__(self, source_dir: str, weights_dir: str, device: str) -> None:
        sys.path.insert(0, source_dir)
        from openvoice import utils
        from openvoice.mel_processing import spectrogram_torch
        from openvoice.models import SynthesizerTrn

        self._spectrogram = spectrogram_torch
        self.device = device
        self.hps = utils.get_hparams_from_file(os.path.join(weights_dir, "converter", "config.json"))
        self.sample_rate = self.hps.data.sampling_rate
        self.model = SynthesizerTrn(
            len(getattr(self.hps, "symbols", [])), self.hps.data.filter_length // 2 + 1,
            n_speakers=self.hps.data.n_speakers, **self.hps.model,
        ).to(device).eval()
        checkpoint = torch.load(os.path.join(weights_dir, "converter", "checkpoint.pth"),
                                map_location=device, weights_only=True)
        self.model.load_state_dict(checkpoint["model"], strict=False)
        self.target = None
        self.source = None
        self._heard: list[np.ndarray] = []
        self._heard_len = 0
        self._last_source_update = 0.0
        self._source_updates = 0
        self.tau = 0.3

    def _spec(self, audio: torch.Tensor) -> torch.Tensor:
        d = self.hps.data
        return self._spectrogram(audio, d.filter_length, d.sampling_rate, d.hop_length, d.win_length, center=False)

    def _embedding(self, audio: np.ndarray) -> torch.Tensor:
        y = torch.from_numpy(audio).float().to(self.device).unsqueeze(0)
        return self.model.ref_enc(self._spec(y).transpose(1, 2)).unsqueeze(-1)

    @torch.inference_mode()
    def set_target(self, reference: np.ndarray) -> None:
        self.target = self._embedding(reference)
        if self.source is None:
            # Until enough of the speaker has been heard, assume a neutral starting point.
            self.source = self.target

    @torch.inference_mode()
    def observe_speech(self, block: np.ndarray) -> None:
        """Learn the live speaker's own embedding from what they actually say."""
        self._heard.append(block.copy())
        self._heard_len += len(block)
        limit = int(_SOURCE_WINDOW_S * self.sample_rate)
        while self._heard_len - len(self._heard[0]) > limit:
            self._heard_len -= len(self._heard.pop(0))
        now = time.monotonic()
        # A speaker's voice doesn't change mid-sentence, and this costs real time on a CPU. Settle
        # on a good estimate early, then keep it.
        if (self._heard_len >= self.sample_rate and self._source_updates < _MAX_SOURCE_UPDATES
                and now - self._last_source_update > _SOURCE_UPDATE_EVERY_S):
            self._last_source_update = now
            self._source_updates += 1
            self.source = self._embedding(np.concatenate(self._heard))

    def reset_stream(self) -> None:
        self._heard, self._heard_len, self.source = [], 0, self.target
        self._source_updates = 0

    @torch.inference_mode()
    def convert(self, window: np.ndarray, need: int, lookahead: int) -> np.ndarray:
        y = torch.from_numpy(window).float().to(self.device).unsqueeze(0)
        spec = self._spec(y)
        lengths = torch.LongTensor([spec.size(-1)]).to(self.device)
        out = self.model.voice_conversion(spec, lengths, sid_src=self.source, sid_tgt=self.target, tau=self.tau)[0]
        audio = out[0, 0].cpu().numpy()
        end = len(audio) - lookahead
        return audio[max(0, end - need): end]
