"""KAI FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analyst, auth, emails, export, faces, geo, health, investigations, maps, phones,
    powerup, public, search, settings as settings_api, sources, system, timeline, usernames,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from sqlmodel import SQLModel


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

    @app.middleware("http")
    async def usage_analytics(request, call_next):
        response = await call_next(request)
        try:
            path = request.url.path
            event = None
            if path.endswith("/face/public/search/stream"):
                event = "public_search"
            elif path.endswith("/face/public/compare"):
                event = "public_compare"
            elif path.endswith("/public/lookup"):
                event = "public_lookup"
            elif path.endswith("/sources/public-submit"):
                event = "public_submit"
            if event and response.status_code < 500:
                from app.core.analytics import record_event
                from app.core.redis import get_redis_client

                ip = request.client.host if request.client else "unknown"
                await record_event(get_redis_client(), event, ip, detail=path)
        except Exception:
            pass
        return response

    @app.on_event("startup")
    async def _startup() -> None:
        from app.database import models as _models  # noqa: F401  (register tables on metadata)
        from app.database.session import engine
        from app.core.seed import seed_admin, seed_default_sources

        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        try:
            await seed_admin()
            await seed_default_sources(only_if_empty=True)
            # Reset sources left 'crawling' by a prior process that was killed
            # mid-crawl (e.g. a restart), so they aren't stuck forever.
            from sqlalchemy import update as _update

            from app.database.models.source import Source as _Source
            from app.database.session import async_session_maker as _asm

            async with _asm() as _s:
                await _s.execute(
                    _update(_Source).where(_Source.status == "crawling").values(status="idle")
                )
                await _s.commit()
        except Exception:  # never block startup on seeding
            get_logger("kai.startup").exception("startup seeding failed")
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
    app.include_router(public.router)
    app.include_router(geo.router)
    app.include_router(settings_api.router)

    @app.get("/", tags=["meta"])
    async def root() -> dict:
        return {"name": "KAI", "tagline": "Knowledge • Analysis • Intelligence"}

    return app


app = create_app()
