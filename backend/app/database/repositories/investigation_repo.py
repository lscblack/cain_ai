"""Investigation repository + case-code allocation."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select

from app.database.models.investigation import Investigation
from app.database.repositories.base import BaseRepository
from app.intelligence.code import generate_case_code, next_sequence


class InvestigationRepository(BaseRepository[Investigation]):
    model = Investigation

    async def list_newest(self, *, limit: int = 100, offset: int = 0) -> list[Investigation]:
        result = await self.session.execute(
            select(Investigation).order_by(desc(Investigation.created_at)).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def _latest_code_for_year(self, year: int) -> str | None:
        prefix = f"CASE-{year:04d}-"
        result = await self.session.execute(
            select(Investigation.code)
            .where(Investigation.code.like(f"{prefix}%"))
            .order_by(desc(Investigation.code))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def allocate_code(self) -> str:
        year = datetime.now(timezone.utc).year
        latest = await self._latest_code_for_year(year)
        return generate_case_code(year, next_sequence(latest, year))
