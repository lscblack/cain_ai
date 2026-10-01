"""Audit log repository."""
from __future__ import annotations

import uuid

from app.database.models.audit import AuditLog
from app.database.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def record(
        self,
        action: str,
        *,
        actor_id: uuid.UUID | None = None,
        detail: dict | None = None,
        ip: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(action=action, actor_id=actor_id, detail=detail, ip=ip)
        return await self.add(entry)
