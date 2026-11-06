"""KAI FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analyst, auth, chat, contacts, discovery, emails, enrich, export, faces, geo, health,
    investigations, maps, phones, powerup, public, search, settings as settings_api, sources,
    system, timeline, tools, usernames, voice,
)
from app.api import investigate
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
            # Enrichment jobs left 'running' by a killed process can't resume
            # themselves — mark them interrupted so the UI is accurate.
            from app.enrich import runner as _enrich_runner

            await _enrich_runner.reset_stale_jobs()

            # Load operator-defined tool capabilities into the live registry.
            from app.security import custom_tools as _custom_tools
            from app.database.session import async_session_maker as _asm2

            async with _asm2() as _s2:
                await _custom_tools.reload_registry(_s2)
        except Exception:  # never block startup on seeding
            get_logger("kai.startup").exception("startup seeding failed")

        # Pre-warm the chat model in the background so the operator's FIRST
        # message isn't a ~40s cold load. Loads the model + caches the system
        # prompt prefix. Fire-and-forget; never blocks or fails startup.
        async def _warm_model() -> None:
            try:
                from app.ai.ollama import GenParams, get_ollama_provider
                from app.ai.router import AIMessage
                from app.security.orchestrator import protocol_system_message

                sys_msg = await protocol_system_message(get_settings().tool_max_agent_steps)
                provider = get_ollama_provider()
                await provider.chat(
                    [sys_msg, AIMessage(role="user", content="ready?")],
                    params=GenParams(num_predict=1),
                )
                get_logger("kai.startup").info("chat model pre-warmed")
            except Exception:  # model offline / not installed — ignore
                get_logger("kai.startup").info("chat model pre-warm skipped (unavailable)")

        try:
            from app.voice.services import reset_interrupted as _voice_reset

            await _voice_reset()
        except Exception:  # never block startup on the voice module
            get_logger("kai.startup").exception("voice startup cleanup failed")

        import asyncio as _asyncio
        _asyncio.create_task(_warm_model())

        async def _warm_face_index() -> None:
            # Load the whole face index into memory once (~40 s for ~230k faces)
            # so image searches scan every face in well under a second.
            try:
                from app.database.session import async_session_maker
                from app.intelligence.face.index_cache import get_index_cache

                async with async_session_maker() as s:
                    await get_index_cache().refresh(s)
                get_logger("kai.startup").info(
                    "face index cache warmed: %d faces", get_index_cache().size)
            except Exception as exc:  # DB down etc. — first search will load it
                get_logger("kai.startup").info("face index warm skipped: %s", exc)

        _asyncio.create_task(_warm_face_index())
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(investigations.router)
    app.include_router(search.router)
    app.include_router(phones.router)
    app.include_router(emails.router)
    app.include_router(usernames.router)
    app.include_router(faces.router)
    app.include_router(sources.router)
    app.include_router(discovery.router)
    app.include_router(contacts.router)
    app.include_router(powerup.router)
    app.include_router(analyst.router)
    app.include_router(maps.router)
    app.include_router(timeline.router)
    app.include_router(export.router)
    app.include_router(system.router)
    app.include_router(public.router)
    app.include_router(geo.router)
    app.include_router(settings_api.router)
    app.include_router(chat.router)
    app.include_router(tools.router)
    app.include_router(enrich.router)
    app.include_router(investigate.router)
    app.include_router(voice.router)
    app.include_router(voice.ws_router)

    @app.get("/", tags=["meta"])
    async def root() -> dict:
        return {"name": "KAI", "tagline": "Knowledge • Analysis • Intelligence"}

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        from app.voice.manager import get_manager as _voice_manager

        await _voice_manager().shutdown()

    return app


app = create_app()
