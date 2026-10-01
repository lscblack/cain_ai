"""KAI FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    auth, emails, faces, health, investigations, phones, search, sources, usernames,
)
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("DEBUG" if settings.is_dev else "INFO")

    app = FastAPI(
        title="KAI — Knowledge, Analysis & Intelligence",
        version="0.1.0",
        description="Local-first OSINT intelligence platform.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(investigations.router)
    app.include_router(search.router)
    app.include_router(phones.router)
    app.include_router(emails.router)
    app.include_router(usernames.router)
    app.include_router(faces.router)
    app.include_router(sources.router)

    @app.get("/", tags=["meta"])
    async def root() -> dict:
        return {"name": "KAI", "tagline": "Knowledge • Analysis • Intelligence"}

    return app


app = create_app()
