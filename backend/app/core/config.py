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
    face_cpu_threads: int = Field(default=0)
    # Nice value applied to the (CPU) face-inference worker thread so interactive
    # requests and the rest of the system keep priority (0-19; higher = lower priority).
    face_infer_nice: int = Field(default=10)
    # Tor SOCKS proxy for .onion crawling (empty = onion disabled)
    tor_socks_proxy: str = Field(default="")

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173"]
    )

    # ── External provider keys (empty => provider reports UNAVAILABLE) ──
    serpapi_api_key: str = Field(default="")
    bing_visual_key: str = Field(default="")
    tineye_api_key: str = Field(default="")
    unavatar_api_key: str = Field(default="")  # optional; raises unavatar free 25/day limit

    # AI analyst (OpenRouter / OpenAI-compatible)
    openrouter_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    ai_model: str = Field(default="openai/gpt-4o-mini")

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
