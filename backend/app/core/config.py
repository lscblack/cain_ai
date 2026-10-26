"""Application configuration via pydantic-settings.

Values are read from the environment / a local `.env` file. Secrets live only
here and never reach the frontend.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Repo-root .env, resolved absolutely so it loads regardless of CWD
# (uvicorn from backend/, alembic from backend/, pytest from backend/).
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(default="dev")
    app_secret_key: str = Field(default="change-me")
    access_token_expire_minutes: int = Field(default=720)

    # Bootstrap admin — seeded on first startup if the DB has no users.
    admin_email: str = Field(default="")
    admin_password: str = Field(default="")

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/kai"
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0")
    face_use_gpu: bool = Field(default=True)  # use GPU only when a working CUDA driver is present
    # Cap CPU threads used by face inference so background work never saturates the box.
    # 0 = auto (half the cores, min 2). Ignored when the GPU is in use.
    face_cpu_threads: int = Field(default=6)
    # Nice value applied to the (CPU) face-inference worker thread so interactive
    # requests and the rest of the system keep priority (0-19; higher = lower priority).
    face_infer_nice: int = Field(default=10)
    # Hard ceiling on pages crawled per source run, regardless of the source's
    # configured max_pages — stops one huge site from monopolising the worker.
    crawl_max_pages_ceiling: int = Field(default=1500)
    # How many sources the worker crawls in parallel (face inference stays
    # serialised; this keeps one giant source from blocking all the others).
    crawl_consumers: int = Field(default=2)
    # Pin the worker process to this many CPU cores. onnxruntime ignores thread
    # env caps and sizes its pool to all physical cores, hogging the machine; a
    # CPU affinity bound is the only reliable cap. 0 = no pin.
    worker_cpu_cores: int = Field(default=8)
    # Max images face-processed per crawled page (pages commit after all of them,
    # so a high cap makes image-heavy pages take minutes).
    crawl_max_images_per_page: int = Field(default=12)
    # Tor SOCKS proxy for .onion crawling (empty = onion disabled)
    tor_socks_proxy: str = Field(default="")
    # Route ALL crawler/discovery egress through this proxy (anonymity).
    # e.g. socks5://127.0.0.1:9050 (Tor) or an http(s) proxy. Empty = direct
    # (use this when ProtonVPN is connected system-wide — egress is already VPN'd).
    crawl_proxy: str = Field(default="")
    # Fail closed: when true, refuse to crawl the open web unless a proxy is set
    # (so nothing leaves without Tor/VPN-proxy). Does NOT apply to system VPNs.
    crawl_require_proxy: bool = Field(default=False)
    # Politeness: minimum seconds between requests to the SAME host.
    crawl_rate_delay: float = Field(default=1.0)

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173"]
    )

    # ── External provider keys (empty => provider reports UNAVAILABLE) ──
    serpapi_api_key: str = Field(default="")  # reverse-image only; web discovery is keyless
    # Self-hosted SearXNG base URL (open-source metasearch, JSON API). When set it
    # becomes the preferred discovery engine — reliable, unlimited, aggregates many
    # engines. e.g. http://127.0.0.1:8888  (run `docker compose up -d searxng`).
    searxng_url: str = Field(default="")
    bing_visual_key: str = Field(default="")
    tineye_api_key: str = Field(default="")
    unavatar_api_key: str = Field(default="")  # optional; raises unavatar free 25/day limit

    # AI analyst (OpenRouter / OpenAI-compatible)
    openrouter_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    ai_model: str = Field(default="openai/gpt-4o-mini")

    # ── Local KAI chat model (Ollama) ──
    # The customised security model served by a local Ollama. KAI never
    # silently falls back to a cloud model when this is unreachable — it
    # reports the exact problem instead.
    # Which local inference server backs KAI Chat: "llamacpp" (llama-server,
    # CUDA-capable) or "ollama". Switchable at runtime from Power Up.
    # Shared secret that lets the local desktop app sign in without a password
    # (POST /auth/desktop). Empty = endpoint disabled. Lives only in .env.
    kai_desktop_token: str = Field(default="")
    kai_llm_backend: str = Field(default="ollama")
    llamacpp_base_url: str = Field(default="http://127.0.0.1:8080")
    kai_llamacpp_model: str = Field(default="kai")      # alias llama-server serves the GGUF under
    llamacpp_log_path: str = Field(default="")          # llama-server log (for GPU/CPU detection)
    # Extra llama-server instances serving the SAME model on other hardware (e.g. the
    # Intel iGPU next to the CPU one). Conversations are spread across all of them.
    llamacpp_extra_urls: str = Field(default="")        # comma-separated base URLs
    llamacpp_extra_log_paths: str = Field(default="")   # comma-separated, same order
    llamacpp_extra_weight: float = Field(default=0.35)  # relative speed of an extra instance
    kai_ollama_model: str = Field(default="kai-security")
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    kai_ollama_num_ctx: int = Field(default=8192)       # model context window (tokens)
    kai_ollama_temperature: float = Field(default=0.2)
    # CPU inference of an 8B model on this host is slow (minutes for a long
    # answer); streaming keeps the UI responsive, but non-stream calls need a
    # generous ceiling so a real generation isn't cut off mid-thought.
    kai_ollama_timeout_s: float = Field(default=600.0)  # per-request HTTP timeout
    # Rough chars-per-token used only to trim history so the prompt fits num_ctx.
    kai_ollama_chars_per_token: int = Field(default=4)

    # ── Security tool execution ──
    tool_exec_timeout_s: int = Field(default=60)        # hard wall-clock cap per tool run
    tool_output_max_bytes: int = Field(default=200_000)  # stdout/stderr capture ceiling
    tool_rate_limit_per_min: int = Field(default=30)    # per-operator tool runs / minute
    tool_max_agent_steps: int = Field(default=6)        # tool calls the model may chain in one turn
    # Privileged package installs. The backend never gives the model a root
    # shell; installs run a single argv through this helper. "sudo" needs a
    # scoped NOPASSWD sudoers entry; "pkexec" prompts the desktop. Empty string
    # disables real installation (approval workflow still records the request).
    tool_install_helper: str = Field(default="sudo")
    tool_install_enabled: bool = Field(default=True)
    # When true, an ACTIVE operation whose target isn't on the operator's
    # authorized list auto-adds it (normalized to host/domain; subdomains
    # included) and proceeds — every auto-authorization is still audited and
    # shown in the Targets list. Set false to require explicit authorization.
    tool_auto_authorize_targets: bool = Field(default=True)

    # Maps / geo
    tomtom_api_key: str = Field(default="")
    cesium_ion_token: str = Field(default="")

    # Live geo-intelligence providers
    firms_map_key: str = Field(default="")
    aisstream_api_key: str = Field(default="")
    opensky_client_id: str = Field(default="")
    opensky_client_secret: str = Field(default="")
    windy_webcams_api_key: str = Field(default="")
    windy_webcams_countries: str = Field(default="")
    celestrak_fetch_timeout_ms: int = Field(default=180000)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_dev(self) -> bool:
        return self.app_env.lower() in {"dev", "development", "local"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
