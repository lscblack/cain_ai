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

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/kai"
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0")

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173"]
    )

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
