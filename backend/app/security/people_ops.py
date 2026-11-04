"""KAI chat operation: person investigation (people.investigate).

Wraps app.agents.router.run_investigation and returns a compact, JSON-safe
dict suitable for a local model's context window (no image bytes, capped lists).
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Request
from app.agents.router import run_investigation

PEOPLE_INVESTIGATE = "people.investigate"
PEOPLE_OP_KEYS = frozenset({PEOPLE_INVESTIGATE})

MAX_REL = 10
MAX_WEB = 5
_ALLOWED = {"nid", "phone", "name", "web", "analyse"}
_STR = ("nid", "phone", "name")
_BOOL = ("web", "analyse")


def preview(params: dict | None) -> str:
    p = params or {}
    who = next((str(p[k]).strip() for k in _STR if isinstance(p.get(k), str) and p[k].strip()), "(?)")
    extras = [k for k in _BOOL if p.get(k) is True]
    return f"investigate person {who[:80]}" + (f" (+{', '.join(extras)})" if extras else "")


def _validate(params: dict) -> tuple[Request | None, str | None]:
    if not isinstance(params, dict):
        return None, "params must be an object"
    unknown = sorted(set(params) - _ALLOWED)
    if unknown:
        return None, f"unknown params: {', '.join(unknown)}; allowed: nid, phone, name, web, analyse"
    vals: dict = {}
    for k in _STR:
        v = params.get(k)
        if v is None:
            continue
        if not isinstance(v, str):
            return None, f"{k} must be a string"
        if v.strip():
            vals[k] = v.strip()
    for k in _BOOL:
        v = params.get(k, False)
        if not isinstance(v, bool):
            return None, f"{k} must be a boolean"
        vals[k] = v
    if not any(k in vals for k in _STR):
        return None, "provide at least one of nid, phone, name"
    return Request(**vals), None


def _trim(lst, truncated: list[bool]):
    if isinstance(lst, dict):  # kin: {"parents": [...], ...}
        return {k: _trim(v, truncated) for k, v in lst.items()}
    if isinstance(lst, list) and len(lst) > MAX_REL:
        truncated.append(True)
        return lst[:MAX_REL]
    return lst


def _strip_bytes(obj):
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return None
    if isinstance(obj, dict):
        return {k: _strip_bytes(v) for k, v in obj.items()
                if k not in ("image", "image_bytes", "photo", "thumbnail")}
    if isinstance(obj, (list, tuple)):
        return [_strip_bytes(v) for v in obj]
    return obj


async def run_people_op(session: AsyncSession, *, user_id: uuid.UUID,
                        op_key: str, params: dict) -> dict:
    if op_key != PEOPLE_INVESTIGATE:
        return {"ok": False, "error": f"unknown operation {op_key}"}
    req, err = _validate(params or {})
    if err:
        return {"ok": False, "error": err}

    async def _noop(event: str, payload: dict) -> None:
        return None

    try:
        out = await run_investigation(session, user_id, req, _noop)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"investigation failed: {type(e).__name__}"}

    truncated: list[bool] = []
    rel = out.get("relations") or {}
    relations = {k: _trim(rel.get(k), truncated)
                 for k in ("kin", "associates", "weak_associates")}
    res = {
        "ok": True,
        "person": out.get("person"),
        "relations": {**relations, **({"truncated": True} if truncated else {})},
        "web_findings": list(out.get("web_findings") or [])[:MAX_WEB],
        "spouse_candidates": out.get("spouse_candidates") or [],
        "analysis": out.get("analysis"),
        "notes": list(out.get("notes") or []),
        "agents_run": list(out.get("agents_run") or []),
    }
    return _strip_bytes(res)
