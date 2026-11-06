"""The models KAI can install. Revisions are pinned: an upstream change cannot silently
alter behaviour, and every stored voice representation records the revision that made it."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WeightFile:
    repo: str
    revision: str
    # None downloads the listed patterns into `subdir`.
    filename: str | None = None
    patterns: tuple[str, ...] = ()
    subdir: str = ""


@dataclass(frozen=True)
class EnvSpec:
    name: str
    python: str
    torch_index: str
    packages: tuple[str, ...]
    worker: str


TORCH_INDEX = "https://download.pytorch.org/whl/cu126"

TTS_ENV = EnvSpec(
    name="kai_voice_tts", python="3.12", torch_index=TORCH_INDEX, worker="tts_worker.py",
    packages=("qwen-tts==0.1.1", "silero-vad==6.2.3", "faster-whisper==1.2.1"),
)
VC_ENV = EnvSpec(
    name="kai_voice_vc", python="3.10", torch_index=TORCH_INDEX, worker="vc_worker.py",
    packages=(
        "numpy<2", "scipy", "librosa", "soundfile", "transformers==4.46.3", "huggingface-hub<0.27",
        "munch", "einops", "pyyaml", "hydra-core==1.3.2", "descript-audio-codec==1.0.0", "onnxruntime",
        "silero-vad==6.2.3", "accelerate",
    ),
)


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    kind: str  # tts | vc
    env: EnvSpec
    license: str
    description: str
    repo_url: str
    revision: str
    download_gb: float
    min_ram_gb: float
    min_vram_gb: float
    weights: tuple[WeightFile, ...]
    required_files: tuple[str, ...]
    optional: bool = False
    format_version: int = 1
    source_repo: str = ""  # cloned at source_commit when the engine isn't pip-installable
    source_commit: str = ""
    source_dir: str = ""
    extra: dict = field(default_factory=dict)


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="qwen3-tts-0.6b", name="Qwen3-TTS 0.6B Base", kind="tts", env=TTS_ENV, license="Apache-2.0",
        description="The default voice cloning and text-to-speech model. Reuses a stored voice without the original recording.",
        repo_url="https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        revision="5d83992436eae1d760afd27aff78a71d676296fc", download_gb=2.52, min_ram_gb=4, min_vram_gb=3,
        weights=(WeightFile("Qwen/Qwen3-TTS-12Hz-0.6B-Base", "5d83992436eae1d760afd27aff78a71d676296fc"),),
        required_files=("model.safetensors", "speech_tokenizer/model.safetensors", "config.json"),
    ),
    ModelSpec(
        id="qwen3-tts-1.7b", name="Qwen3-TTS 1.7B Base", kind="tts", env=TTS_ENV, license="Apache-2.0",
        description="Higher quality option that uses much more memory. Too slow for regular CPU use.",
        repo_url="https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        revision="fd4b254389122332181a7c3db7f27e918eec64e3", download_gb=4.54, min_ram_gb=8, min_vram_gb=6,
        weights=(WeightFile("Qwen/Qwen3-TTS-12Hz-1.7B-Base", "fd4b254389122332181a7c3db7f27e918eec64e3"),),
        required_files=("model.safetensors", "speech_tokenizer/model.safetensors", "config.json"),
        optional=True,
    ),
    ModelSpec(
        id="seed-vc-tiny", name="Seed-VC Tiny (real-time)", kind="vc", env=VC_ENV, license="GPL-3.0 (isolated process)",
        description="Zero-shot live conversion from a short reference. Upstream is archived, so it's pinned to its final commit. Built for a GPU.",
        repo_url="https://github.com/Plachtaa/seed-vc",
        revision="51383efd921027683c89e5348211d93ff12ac2a8", download_gb=1.6, min_ram_gb=4, min_vram_gb=2,
        source_repo="https://github.com/Plachtaa/seed-vc.git",
        source_commit="51383efd921027683c89e5348211d93ff12ac2a8", source_dir="seed-vc",
        weights=(
            WeightFile("Plachta/Seed-VC", "257283f9f41585055e8f858fba4fd044e5caed6e", filename="DiT_uvit_tat_xlsr_ema.pth"),
            WeightFile("funasr/campplus", "e4b6ede7ce16997aff4ae69fbca1f0175e2afede", filename="campplus_cn_common.bin"),
            WeightFile("FunAudioLLM/CosyVoice-300M", "24c40509c3c5ea6fe06b5f8790ff99e3714a6bee", filename="hift.pt"),
            WeightFile("facebook/wav2vec2-xls-r-300m", "1a640f32ac3e39899438a2931f9924c02f080a54",
                       patterns=("*.json", "pytorch_model.bin", "model.safetensors"), subdir="wav2vec2-xls-r-300m"),
        ),
        required_files=("DiT_uvit_tat_xlsr_ema.pth", "campplus_cn_common.bin", "hift.pt", "wav2vec2-xls-r-300m/config.json"),
    ),
    ModelSpec(
        id="openvoice-v2", name="OpenVoice V2 (CPU live conversion)", kind="vc", env=VC_ENV, license="MIT",
        description="Used for live conversion when there's no working GPU. Runs continuously on a CPU with a delay of a few seconds. Changes the speaker's timbre and keeps their pitch.",
        repo_url="https://github.com/myshell-ai/OpenVoice",
        revision="f36e7edfe1684461a8343844af60babc2efbb727", download_gb=0.13, min_ram_gb=2, min_vram_gb=1,
        source_repo="https://github.com/myshell-ai/OpenVoice.git",
        source_commit="74a1d147b17a8c3092dd5430504bd83ef6c7eb23", source_dir="OpenVoice",
        weights=(WeightFile("myshell-ai/OpenVoiceV2", "f36e7edfe1684461a8343844af60babc2efbb727", patterns=("converter/*",)),),
        required_files=("converter/checkpoint.pth", "converter/config.json"),
        extra={"long_blocks": True, "cpu_preferred": True},
    ),
)

_BY_ID = {m.id: m for m in MODELS}


def find(model_id: str) -> ModelSpec | None:
    return _BY_ID.get(model_id)


def get(model_id: str) -> ModelSpec:
    return _BY_ID[model_id]


def of_kind(kind: str) -> list[ModelSpec]:
    return [m for m in MODELS if m.kind == kind]
