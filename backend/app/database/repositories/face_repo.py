"""Face repository."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database.models.face import Face
from app.database.repositories.base import BaseRepository


class FaceRepository(BaseRepository[Face]):
    model = Face

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Face))
        return int(result.scalar_one())

    async def list_with_embeddings(
        self, *, investigation_id: uuid.UUID | None = None, limit: int = 100000
    ) -> list[Face]:
        stmt = select(Face)
        if investigation_id is not None:
            stmt = stmt.where(Face.investigation_id == investigation_id)
        stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())
