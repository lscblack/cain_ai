"""Repositories for entities, evidence, and relationships (the case graph)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database.models.entity import Entity
from app.database.models.evidence import Evidence
from app.database.models.relationship import Relationship
from app.database.repositories.base import BaseRepository


class EntityRepository(BaseRepository[Entity]):
    model = Entity

    async def list_for_investigation(self, investigation_id: uuid.UUID) -> list[Entity]:
        result = await self.session.execute(
            select(Entity).where(Entity.investigation_id == investigation_id)
        )
        return list(result.scalars().all())

    async def count_for_investigation(self, investigation_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Entity).where(Entity.investigation_id == investigation_id)
        )
        return int(result.scalar_one())

    async def exists_in_investigation(self, entity_id: uuid.UUID, investigation_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(Entity.id).where(
                Entity.id == entity_id, Entity.investigation_id == investigation_id
            )
        )
        return result.scalar_one_or_none() is not None


class EvidenceRepository(BaseRepository[Evidence]):
    model = Evidence

    async def list_for_investigation(self, investigation_id: uuid.UUID) -> list[Evidence]:
        result = await self.session.execute(
            select(Evidence).where(Evidence.investigation_id == investigation_id)
        )
        return list(result.scalars().all())

    async def count_for_investigation(self, investigation_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Evidence).where(
                Evidence.investigation_id == investigation_id
            )
        )
        return int(result.scalar_one())


class RelationshipRepository(BaseRepository[Relationship]):
    model = Relationship

    async def list_for_investigation(self, investigation_id: uuid.UUID) -> list[Relationship]:
        result = await self.session.execute(
            select(Relationship).where(Relationship.investigation_id == investigation_id)
        )
        return list(result.scalars().all())

    async def count_for_investigation(self, investigation_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Relationship).where(
                Relationship.investigation_id == investigation_id
            )
        )
        return int(result.scalar_one())
