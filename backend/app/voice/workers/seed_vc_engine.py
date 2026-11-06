# SPDX-License-Identifier: GPL-3.0-or-later
"""Seed-VC adapter. Imports GPL-3.0 code, so this file is GPL-3.0 too, and it only ever
runs inside the isolated worker process; the rest of KAI talks to it over a pipe.

The streaming steps follow Seed-VC's real-time-gui.py (custom_infer), without its GUI and
its unconditional use of torch.cuda timing events, which make it crash on a CPU.
Pinned to upstream commit 51383efd, the final one: the repository is archived.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import torch
import torchaudio
import yaml

_CE_DIT_DIFFERENCE_S = 2.0
_MAX_PROMPT_S = 3.0


class SeedVcEngine:
    engine_id = "seed-vc-tiny"
    sample_rate = 22050
    context_s = 2.5
    lookahead_s = 0.02
    crossfade_s = 0.04
    search_s = 0.012
    default_block_s = 0.18

    def __init__(self, source_dir: str, weights_dir: str, device: str, diffusion_steps: int = 6) -> None:
        sys.path.insert(0, source_dir)
        os.chdir(source_dir)  # upstream loads configs/hifigan.yml relative to the working directory
        from modules.bigvgan.meldataset import mel_spectrogram  # noqa: F401
        from modules.audio import mel_spectrogram as to_mel_fn
        from modules.campplus.DTDNN import CAMPPlus
        from modules.commons import build_model, load_checkpoint, recursive_munch
        from modules.hifigan.f0_predictor import ConvRNNF0Predictor
        from modules.hifigan.generator import HiFTGenerator
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2Model

        self.device = torch.device(device)
        self.fp16 = device.startswith("cuda")
        self.diffusion_steps = diffusion_steps
        self.cfg_rate = 0.7
        config = yaml.safe_load(open("configs/presets/config_dit_mel_seed_uvit_xlsr_tiny.yml"))
        params = recursive_munch(config["model_params"])
        params.dit_type = "DiT"
        self.model = build_model(params, stage="DiT")
        self.model, *_ = load_checkpoint(
            self.model, None, os.path.join(weights_dir, "DiT_uvit_tat_xlsr_ema.pth"),
            load_only_params=True, ignore_modules=[], is_distributed=False,
        )
        for key in self.model:
            self.model[key].eval().to(self.device)
        self.model.cfm.estimator.setup_caches(max_batch_size=1, max_seq_length=8192)

        self.campplus = CAMPPlus(feat_dim=80, embedding_size=192)
        self.campplus.load_state_dict(torch.load(os.path.join(weights_dir, "campplus_cn_common.bin"), map_location="cpu"))
        self.campplus.eval().to(self.device)

        hift_config = yaml.safe_load(open("configs/hifigan.yml"))
        self.vocoder = HiFTGenerator(**hift_config["hift"], f0_predictor=ConvRNNF0Predictor(**hift_config["f0_predictor"]))
        self.vocoder.load_state_dict(torch.load(os.path.join(weights_dir, "hift.pt"), map_location="cpu"))
        self.vocoder.eval().to(self.device)

        name = os.path.join(weights_dir, "wav2vec2-xls-r-300m")
        self.extractor = Wav2Vec2FeatureExtractor.from_pretrained(name)
        self.content = Wav2Vec2Model.from_pretrained(name)
        self.content.encoder.layers = self.content.encoder.layers[: config["model_params"]["speech_tokenizer"]["output_layer"]]
        self.content = self.content.to(self.device).eval()
        if self.fp16:
            self.content = self.content.half()

        spect = config["preprocess_params"]["spect_params"]
        self.mel_args = {
            "n_fft": spect["n_fft"], "win_size": spect["win_length"], "hop_size": spect["hop_length"],
            "num_mels": spect["n_mels"], "sampling_rate": self.sample_rate, "fmin": spect.get("fmin", 0),
            "fmax": None if spect.get("fmax", "None") == "None" else 8000, "center": False,
        }
        self._to_mel = lambda x: to_mel_fn(x, **self.mel_args)
        self.hop = spect["hop_length"]
        self.prompt = None
        self.mel2 = None
        self.style2 = None

    def _semantic(self, waves_16k: torch.Tensor) -> torch.Tensor:
        inputs = self.extractor(
            [waves_16k[0].cpu().numpy()], return_tensors="pt", return_attention_mask=True,
            padding=True, sampling_rate=16000,
        ).to(self.device)
        values = inputs.input_values.half() if self.fp16 else inputs.input_values
        return self.content(values).last_hidden_state.float()

    @torch.inference_mode()
    def set_target(self, reference: np.ndarray) -> None:
        reference = reference[: int(self.sample_rate * _MAX_PROMPT_S)]
        wav = torch.from_numpy(reference).float().to(self.device)
        wav_16k = torchaudio.functional.resample(wav, self.sample_rate, 16000)
        semantic = self._semantic(wav_16k.unsqueeze(0))
        feat = torchaudio.compliance.kaldi.fbank(wav_16k.unsqueeze(0), num_mel_bins=80, dither=0, sample_frequency=16000)
        feat = feat - feat.mean(dim=0, keepdim=True)
        self.style2 = self.campplus(feat.unsqueeze(0))
        self.mel2 = self._to_mel(wav.unsqueeze(0))
        lengths = torch.LongTensor([self.mel2.size(2)]).to(self.device)
        self.prompt = self.model.length_regulator(semantic, ylens=lengths, n_quantizers=3, f0=None)[0]

    def observe_speech(self, block: np.ndarray) -> None:
        """Zero-shot: the model takes content from the audio itself, no source embedding."""

    def reset_stream(self) -> None:
        pass

    @torch.inference_mode()
    def convert(self, window: np.ndarray, need: int, lookahead: int) -> np.ndarray:
        wav = torch.from_numpy(window).float().to(self.device)
        wav_16k = torchaudio.functional.resample(wav, self.sample_rate, 16000)
        semantic = self._semantic(wav_16k.unsqueeze(0))
        skip_frames = int(_CE_DIT_DIFFERENCE_S * 50)
        semantic = semantic[:, skip_frames:]
        kept_s = len(window) / self.sample_rate - _CE_DIT_DIFFERENCE_S
        lengths = torch.LongTensor([int(kept_s * self.sample_rate // self.hop)]).to(self.device)
        cond = self.model.length_regulator(semantic, ylens=lengths, n_quantizers=3, f0=None)[0]
        full = torch.cat([self.prompt, cond], dim=1)
        with torch.autocast(device_type=self.device.type, dtype=torch.float16 if self.fp16 else torch.float32, enabled=self.fp16):
            target = self.model.cfm.inference(
                full, torch.LongTensor([full.size(1)]).to(self.device), self.mel2, self.style2, None,
                n_timesteps=self.diffusion_steps, inference_cfg_rate=self.cfg_rate,
            )
            target = target[:, :, self.mel2.size(-1):]
            audio = self.vocoder(target).squeeze()
        audio = audio.float().cpu().numpy()
        end = len(audio) - lookahead
        return audio[max(0, end - need): end]
