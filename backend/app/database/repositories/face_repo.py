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

    async def search_all(
        self, queries: list[list[float]], *, floor: float, batch: int = 20000,
    ) -> dict[str, float]:
        """Score EVERY indexed face against ``queries`` via the in-memory index
        cache (loaded once, then refreshed incrementally). Returns
        ``{face_id: best score ≥ floor}``.

        Unlike :meth:`list_with_embeddings` (capped at ``limit`` rows), this never
        silently skips part of the index.
        """
        from app.intelligence.face.index_cache import get_index_cache

        # ``batch`` kept for API compatibility; the cache pages internally.
        return await get_index_cache().search(self.session, queries, floor=floor)

    async def get_many(self, ids: list[str]) -> list[Face]:
        if not ids:
            return []
        return list((await self.session.execute(
            select(Face).where(Face.id.in_([uuid.UUID(i) for i in ids])))).scalars().all())
