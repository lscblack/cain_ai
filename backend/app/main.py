"""KAI FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analyst, auth, emails, export, faces, geo, health, investigations, maps, phones,
    powerup, search, settings as settings_api, sources, system, timeline, usernames,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger


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

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return response

    @app.on_event("startup")
    async def _startup() -> None:
        import asyncio

        from app.core.seed import seed_admin
        from app.crawlers.scheduler import scheduler_loop

        try:
            await seed_admin()
        except Exception:  # never block startup on seeding
            get_logger("kai.startup").exception("admin seeding failed")
        # background crawl scheduler (manual sources are never auto-crawled)
        app.state.scheduler_task = asyncio.create_task(scheduler_loop())

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(investigations.router)
    app.include_router(search.router)
    app.include_router(phones.router)
    app.include_router(emails.router)
    app.include_router(usernames.router)
    app.include_router(faces.router)
    app.include_router(sources.router)
    app.include_router(powerup.router)
    app.include_router(analyst.router)
    app.include_router(maps.router)
    app.include_router(timeline.router)
    app.include_router(export.router)
    app.include_router(system.router)
    app.include_router(geo.router)
    app.include_router(settings_api.router)

    @app.get("/", tags=["meta"])
    async def root() -> dict:
        return {"name": "KAI", "tagline": "Knowledge • Analysis • Intelligence"}

    return app


app = create_app()
