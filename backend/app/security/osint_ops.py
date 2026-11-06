"""Investigation / casework operations KAI can run itself.

These let the model create and read the operator's investigation case files and
record entities + evidence — through the SAME repositories the HTTP API uses, so
everything behaves identically. Benign DB I/O on the operator's own cases;
``service.run_operation`` rate-limits and audits them but does not gate them
behind ``tools_enabled``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.entity import Entity
from app.database.models.evidence import Evidence
from app.database.models.investigation import Investigation
from app.database.repositories.graph_repos import EntityRepository, EvidenceRepository
from app.database.repositories.investigation_repo import InvestigationRepository

CREATE = "investigation.create"
LIST = "investigation.list"
GET = "investigation.get"
ADD_ENTITY = "investigation.add_entity"
ADD_EVIDENCE = "investigation.add_evidence"

INV_OP_KEYS = frozenset({CREATE, LIST, GET, ADD_ENTITY, ADD_EVIDENCE})

# Entity/observation types the graph understands.
VALID_ENTITY_TYPES = frozenset({
    "face", "phone", "email", "username", "domain", "url", "image",
    "organization", "location", "document", "vehicle", "aircraft", "vessel",
    "person", "nid", "parcel",
})


def preview(op_key: str, params: dict) -> str:
    params = params or {}
    if op_key == CREATE:
        return f"create investigation: {str(params.get('name') or '(unnamed)')[:80]}"
    if op_key == LIST:
        return "list investigations"
    if op_key == GET:
        return f"read investigation {params.get('investigation_id') or '(?)'}"
    if op_key == ADD_ENTITY:
        return (f"record {params.get('type') or 'entity'} "
                f"'{str(params.get('value') or '')[:60]}' in {params.get('investigation_id') or '(?)'}")
    if op_key == ADD_EVIDENCE:
        return (f"record {params.get('type') or 'evidence'} evidence "
                f"from {str(params.get('source_url') or '')[:60]}")
    return op_key


def _inv_out(inv: Investigation) -> dict:
    return {
        "id": str(inv.id), "code": inv.code, "name": inv.name,
        "description": inv.description, "status": inv.status,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


def _entity_out(e: Entity) -> dict:
    return {"id": str(e.id), "investigation_id": str(e.investigation_id),
            "type": e.type, "value": e.value, "label": e.label, "metadata": e.meta}


def _parse_uuid(val) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError, AttributeError):
        return None


async def run_investigation_op(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    op_key: str,
    params: dict,
) -> dict:
    params = params or {}

    if op_key == CREATE:
        name = str(params.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "name is required"}
        repo = InvestigationRepository(session)
        code = await repo.allocate_code()
        inv = await repo.add(Investigation(
            code=code, name=name[:300],
            description=(str(params.get("description")) if params.get("description") else None),
            created_by=user_id,
        ))
        await session.flush()
        return {"ok": True, "investigation": _inv_out(inv),
                "message": f"Created investigation {code}."}

    if op_key == LIST:
        rows = await InvestigationRepository(session).list_newest(limit=100)
        return {"ok": True, "investigations": [_inv_out(i) for i in rows], "count": len(rows)}

    if op_key == GET:
        inv_id = _parse_uuid(params.get("investigation_id") or params.get("id"))
        if inv_id is None:
            return {"ok": False, "error": "valid investigation_id is required"}
        inv = await InvestigationRepository(session).get(inv_id)
        if inv is None:
            return {"ok": False, "error": "investigation_not_found"}
        entities = await EntityRepository(session).list_for_investigation(inv_id)
        return {"ok": True, "investigation": _inv_out(inv),
                "entities": [_entity_out(e) for e in entities], "entity_count": len(entities)}

    if op_key == ADD_ENTITY:
        inv_id = _parse_uuid(params.get("investigation_id"))
        if inv_id is None:
            return {"ok": False, "error": "valid investigation_id is required"}
        if await InvestigationRepository(session).get(inv_id) is None:
            return {"ok": False, "error": "investigation_not_found"}
        etype = str(params.get("type") or "").strip().lower()
        value = str(params.get("value") or "").strip()
        if not etype or not value:
            return {"ok": False, "error": "type and value are required"}
        if etype not in VALID_ENTITY_TYPES:
            return {"ok": False, "error": f"invalid type '{etype}'; valid: {sorted(VALID_ENTITY_TYPES)}"}
        meta = params.get("metadata") if isinstance(params.get("metadata"), dict) else {}
        entity = await EntityRepository(session).add(Entity(
            investigation_id=inv_id, type=etype, value=value[:2000],
            label=(str(params.get("label")) if params.get("label") else None), meta=meta,
        ))
        await session.flush()
        return {"ok": True, "entity": _entity_out(entity), "message": f"Recorded {etype}."}

    if op_key == ADD_EVIDENCE:
        inv_id = _parse_uuid(params.get("investigation_id"))
        if inv_id is None:
            return {"ok": False, "error": "valid investigation_id is required"}
        if await InvestigationRepository(session).get(inv_id) is None:
            return {"ok": False, "error": "investigation_not_found"}
        source_url = str(params.get("source_url") or "").strip()
        if not source_url:
            return {"ok": False, "error": "source_url is required (evidence must be provenanced)"}
        etype = str(params.get("type") or "document").strip().lower()
        try:
            confidence = float(params.get("confidence")) if params.get("confidence") is not None else None
        except (TypeError, ValueError):
            confidence = None
        ev = await EvidenceRepository(session).add(Evidence(
            investigation_id=inv_id, type=etype, source_url=source_url[:2000],
            collected_at=datetime.now(timezone.utc), confidence=confidence,
            raw_metadata=params.get("metadata") if isinstance(params.get("metadata"), dict) else {},
        ))
        await session.flush()
        return {"ok": True, "evidence": {"id": str(ev.id), "type": ev.type,
                "source_url": ev.source_url, "confidence": ev.confidence},
                "message": "Recorded evidence."}

    return {"ok": False, "error": f"unknown investigation operation: {op_key}"}
