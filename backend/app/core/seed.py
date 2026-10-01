"""Bootstrap-admin seeding (idempotent)."""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.database.models.user import User
from app.database.repositories.user_repo import UserRepository
from app.database.session import async_session_maker

logger = get_logger("kai.seed")


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
