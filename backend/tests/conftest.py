"""Shared test fixtures: disposable test DB + fakeredis + ASGI client."""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

# Ensure a secret exists before app modules read settings.
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")

def _derive_test_db_url() -> str:
    """Prefer TEST_DATABASE_URL; else derive from the app's DATABASE_URL (.env),
    swapping the database name to kai_test. No secret is hardcoded here."""
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    from app.core.config import get_settings

    url = get_settings().database_url
    base, _, _ = url.rpartition("/")
    return f"{base}/kai_test"


TEST_DATABASE_URL = _derive_test_db_url()

import app.database.models  # noqa: E402,F401  (register tables on metadata)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True)
_session_maker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _prepare_db() -> AsyncGenerator[None, None]:
    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with _session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def fake_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=True)


@pytest_asyncio.fixture
async def client(fake_redis) -> AsyncGenerator[AsyncClient, None]:
    from app.core.redis import get_redis
    from app.database.session import get_session
    from app.main import create_app

    app = create_app()

    async def _override_get_session():
        async with _session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_get_redis():
        return fake_redis

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_redis] = _override_get_redis

    # Chat turns run in a background task with their own session; point it at the test DB.
    import app.api.chat as chat_api
    _orig_maker = chat_api.async_session_maker
    chat_api.async_session_maker = _session_maker

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.app = app  # type: ignore[attr-defined]  # expose for dependency overrides in tests
        yield c

    app.dependency_overrides.clear()
    chat_api.async_session_maker = _orig_maker
