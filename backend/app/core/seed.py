"""Bootstrap-admin seeding (idempotent)."""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.database.models.user import User
from app.database.repositories.user_repo import UserRepository
from app.database.session import async_session_maker

logger = get_logger("kai.seed")


async def seed_default_sources(session=None, *, only_if_empty: bool = True) -> dict:
    """Insert the curated default crawl sources, deduped by domain.

    If `session` is given, uses it (caller owns the transaction); otherwise opens
    its own session and commits.
    """
    from sqlalchemy import select

    from app.data.default_sources import DEFAULT_SOURCES
    from app.database.models.source import Source

    async def _run(sess) -> dict:
        existing_total = (await sess.execute(select(Source.id))).first()
        if only_if_empty and existing_total is not None:
            return {"created": 0, "skipped": 0, "note": "sources already present"}
        existing_domains = set((await sess.execute(select(Source.domain))).scalars().all())
        created = skipped = 0
        for name, domain, category, priority in DEFAULT_SOURCES:
            d = domain.strip().lower()
            if d in existing_domains:
                skipped += 1
                continue
            sess.add(
                Source(
                    name=name, base_url=f"https://{d}", domain=d,
                    allowed_paths=[], excluded_paths=[], max_depth=1, max_pages=50,
                    schedule="manual", category=category, priority=priority,
                )
            )
            existing_domains.add(d)
            created += 1
        await sess.flush()
        return {"created": created, "skipped": skipped}

    if session is not None:
        result = await _run(session)
    else:
        async with async_session_maker() as own:
            result = await _run(own)
            await own.commit()
    logger.info("Seeded default sources: %s", result)
    return result


async def seed_admin() -> None:
    """Create the operator from ADMIN_EMAIL/ADMIN_PASSWORD if no users exist."""
    s = get_settings()
    if not s.admin_email or not s.admin_password:
        return
    async with async_session_maker() as session:
        repo = UserRepository(session)
        if await repo.count() > 0:
            return
        await repo.add(
            User(email=s.admin_email.strip().lower(), password_hash=hash_password(s.admin_password))
        )
        await session.commit()
        logger.info("Seeded bootstrap admin operator: %s", s.admin_email)
