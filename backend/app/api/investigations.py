"""Investigation / case CRUD and graph endpoints (operator-authenticated)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.database.models.entity import Entity
from app.database.models.evidence import Evidence
from app.database.models.investigation import Investigation
from app.database.models.relationship import Relationship
from app.database.models.user import User
from app.database.repositories.audit_repo import AuditRepository
from app.database.repositories.graph_repos import (
    EntityRepository,
    EvidenceRepository,
    RelationshipRepository,
)
from app.database.repositories.investigation_repo import InvestigationRepository
from app.database.session import get_session
from app.intelligence.correlation.correlate import EvidenceRef, suggest_relationships
from app.schemas.investigation import (
    EntityCreate,
    EntityOut,
    EvidenceCreate,
    EvidenceOut,
    GraphOut,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationOut,
    InvestigationUpdate,
    RelationshipCreate,
    RelationshipOut,
)

router = APIRouter(prefix="/investigations", tags=["investigations"], dependencies=[])


def _entity_out(e: Entity) -> EntityOut:
    return EntityOut(
        id=e.id,
        investigation_id=e.investigation_id,
        type=e.type,
        value=e.value,
        label=e.label,
        metadata=e.meta,
        created_at=e.created_at,
    )


async def _get_investigation_or_404(
    inv_id: uuid.UUID, session: AsyncSession
) -> Investigation:
    inv = await InvestigationRepository(session).get(inv_id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="investigation_not_found")
    return inv


@router.post("", response_model=InvestigationOut, status_code=status.HTTP_201_CREATED)
async def create_investigation(
    body: InvestigationCreate,
    request: Request,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> InvestigationOut:
    repo = InvestigationRepository(session)
    code = await repo.allocate_code()
    inv = await repo.add(
        Investigation(
            code=code, name=body.name, description=body.description, created_by=operator.id
        )
    )
    await session.flush()
    await AuditRepository(session).record(
        "investigation.create", actor_id=operator.id, detail={"code": code}
    )
    return InvestigationOut(**inv.model_dump())


@router.get("", response_model=list[InvestigationDetail])
async def list_investigations(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[InvestigationDetail]:
    repo = InvestigationRepository(session)
    ents, evs, rels = (
        EntityRepository(session),
        EvidenceRepository(session),
        RelationshipRepository(session),
    )
    out: list[InvestigationDetail] = []
    for inv in await repo.list_newest():
        out.append(
            InvestigationDetail(
                **inv.model_dump(),
                entity_count=await ents.count_for_investigation(inv.id),
                evidence_count=await evs.count_for_investigation(inv.id),
                relationship_count=await rels.count_for_investigation(inv.id),
            )
        )
    return out


@router.get("/{inv_id}", response_model=InvestigationDetail)
async def get_investigation(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> InvestigationDetail:
    inv = await _get_investigation_or_404(inv_id, session)
    return InvestigationDetail(
        **inv.model_dump(),
        entity_count=await EntityRepository(session).count_for_investigation(inv.id),
        evidence_count=await EvidenceRepository(session).count_for_investigation(inv.id),
        relationship_count=await RelationshipRepository(session).count_for_investigation(inv.id),
    )


@router.patch("/{inv_id}", response_model=InvestigationOut)
async def update_investigation(
    inv_id: uuid.UUID,
    body: InvestigationUpdate,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> InvestigationOut:
    inv = await _get_investigation_or_404(inv_id, session)
    data = body.model_dump(exclude_none=True)
    for key, val in data.items():
        setattr(inv, key, val)
    session.add(inv)
    await session.flush()
    await session.refresh(inv)  # reload server-managed updated_at
    return InvestigationOut(**inv.model_dump())


@router.delete("/{inv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investigation(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> None:
    inv = await _get_investigation_or_404(inv_id, session)
    code = inv.code
    # Manual cascade (children reference entities, so order matters).
    for model in (Relationship, Evidence, Entity):
        await session.execute(sa_delete(model).where(model.investigation_id == inv_id))
    await session.delete(inv)
    await session.flush()
    await AuditRepository(session).record(
        "investigation.delete", actor_id=operator.id, detail={"code": code}
    )


# ---- Entities ---------------------------------------------------------------
@router.post("/{inv_id}/entities", response_model=EntityOut, status_code=status.HTTP_201_CREATED)
async def add_entity(
    inv_id: uuid.UUID,
    body: EntityCreate,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> EntityOut:
    await _get_investigation_or_404(inv_id, session)
    entity = await EntityRepository(session).add(
        Entity(
            investigation_id=inv_id,
            type=body.type.value,
            value=body.value,
            label=body.label,
            meta=body.metadata,
        )
    )
    await session.flush()
    return _entity_out(entity)


@router.get("/{inv_id}/entities", response_model=list[EntityOut])
async def list_entities(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[EntityOut]:
    await _get_investigation_or_404(inv_id, session)
    return [_entity_out(e) for e in await EntityRepository(session).list_for_investigation(inv_id)]


# ---- Evidence ---------------------------------------------------------------
@router.post("/{inv_id}/evidence", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED)
async def add_evidence(
    inv_id: uuid.UUID,
    body: EvidenceCreate,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> EvidenceOut:
    await _get_investigation_or_404(inv_id, session)
    if body.entity_id is not None:
        if not await EntityRepository(session).exists_in_investigation(body.entity_id, inv_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="entity_not_in_investigation")
    ev = await EvidenceRepository(session).add(
        Evidence(
            investigation_id=inv_id,
            entity_id=body.entity_id,
            type=body.type.value,
            source_url=body.source_url,
            collected_at=body.collected_at or datetime.now(timezone.utc),
            first_seen=body.first_seen,
            last_seen=body.last_seen,
            hash=body.hash,
            confidence=body.confidence,
            band=body.band.value if body.band else None,
            raw_metadata=body.raw_metadata,
            processed_metadata=body.processed_metadata,
        )
    )
    await session.flush()
    return EvidenceOut(**ev.model_dump())


@router.get("/{inv_id}/evidence", response_model=list[EvidenceOut])
async def list_evidence(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[EvidenceOut]:
    await _get_investigation_or_404(inv_id, session)
    return [EvidenceOut(**e.model_dump()) for e in await EvidenceRepository(session).list_for_investigation(inv_id)]


# ---- Relationships ----------------------------------------------------------
@router.post(
    "/{inv_id}/relationships", response_model=RelationshipOut, status_code=status.HTTP_201_CREATED
)
async def add_relationship(
    inv_id: uuid.UUID,
    body: RelationshipCreate,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> RelationshipOut:
    await _get_investigation_or_404(inv_id, session)
    ents = EntityRepository(session)
    for eid in (body.source_entity_id, body.target_entity_id):
        if not await ents.exists_in_investigation(eid, inv_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="entity_not_in_investigation"
            )
    rel = await RelationshipRepository(session).add(
        Relationship(
            investigation_id=inv_id,
            source_entity_id=body.source_entity_id,
            target_entity_id=body.target_entity_id,
            rel_type=body.rel_type,
            source_url=body.source_url,
            observed_at=body.observed_at or datetime.now(timezone.utc),
            confidence=body.confidence,
            evidence_excerpt=body.evidence_excerpt,
        )
    )
    await session.flush()
    return RelationshipOut(**rel.model_dump())


@router.get("/{inv_id}/relationships", response_model=list[RelationshipOut])
async def list_relationships(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[RelationshipOut]:
    await _get_investigation_or_404(inv_id, session)
    rels = await RelationshipRepository(session).list_for_investigation(inv_id)
    return [RelationshipOut(**r.model_dump()) for r in rels]


@router.get("/{inv_id}/correlations")
async def get_correlations(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _get_investigation_or_404(inv_id, session)
    evd = await EvidenceRepository(session).list_for_investigation(inv_id)
    rels = await RelationshipRepository(session).list_for_investigation(inv_id)
    existing = {frozenset({r.source_entity_id, r.target_entity_id}) for r in rels}
    refs = [EvidenceRef(entity_id=e.entity_id, source_url=e.source_url) for e in evd]
    suggestions = suggest_relationships(refs, existing_pairs=existing)
    return {"suggestions": [s.to_dict() for s in suggestions]}


@router.get("/{inv_id}/graph", response_model=GraphOut)
async def get_graph(
    inv_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> GraphOut:
    await _get_investigation_or_404(inv_id, session)
    nodes = [_entity_out(e) for e in await EntityRepository(session).list_for_investigation(inv_id)]
    edges = [
        RelationshipOut(**r.model_dump())
        for r in await RelationshipRepository(session).list_for_investigation(inv_id)
    ]
    return GraphOut(nodes=nodes, edges=edges)
