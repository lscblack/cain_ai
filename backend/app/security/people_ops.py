"""KAI chat operation: person investigation (people.investigate).

Wraps app.agents.router.run_investigation and returns a compact, JSON-safe
dict suitable for a local model's context window (no image bytes, capped lists).
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Request
from app.agents.ratelimit import check_investigation_rate
from app.agents.router import run_investigation
from app.database.session import async_session_maker

PEOPLE_INVESTIGATE = "people.investigate"
PEOPLE_OP_KEYS = frozenset({PEOPLE_INVESTIGATE})

MAX_REL = 10
MAX_WEB = 5
MAX_LEN = 200
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
        v = v.strip()
        if len(v) > MAX_LEN:
            return None, "parameter too long"
        if k == "nid" and v:
            v = v.replace(" ", "").replace("-", "")
            if not v.isdigit():
                return None, "nid must contain digits only (spaces and dashes are ignored)"
        if v:
            vals[k] = v
    for k in _BOOL:
        v = params.get(k, False)
        if not isinstance(v, bool):
            return None, f"{k} must be a boolean"
        vals[k] = v
    if not any(k in vals for k in _STR):
        return None, "provide at least one of nid, phone, name"
    return Request(**vals), None


_NESTED_KEYS = ("nid", "name", "label", "confidence")
_NODE_KEYS = ("nid", "name", "in_system", "ambiguous", "source_ref")


def _cap(lst: list, path: str, cut: dict) -> list:
    if len(lst) > MAX_REL:
        cut[path] = True
        return lst[:MAX_REL]
    return lst


def _reduce_nested(entry, path: str, cut: dict):
    """A kin card keeps its own fields, but nested person lists inside it (e.g. a
    parent's "children") shrink to {nid, name, label, confidence}, capped."""
    if not isinstance(entry, dict):
        return entry
    out = {}
    for k, v in entry.items():
        if isinstance(v, list) and any(isinstance(x, dict) for x in v):
            v = [{kk: x[kk] for kk in _NESTED_KEYS if kk in x} for x in v if isinstance(x, dict)]
            v = _cap(v, f"{path}.{k}", cut)
        out[k] = v
    return out


def _trim(lst, path: str, cut: dict, *, kin: bool = False):
    if isinstance(lst, dict):  # kin: {"parents": [...], ...}
        return {k: _trim(v, f"{path}.{k}", cut, kin=kin) for k, v in lst.items()}
    if isinstance(lst, list):
        lst = _cap(lst, path, cut)
        # only kin cards carry nested person lists; associates keep their
        # "shared" facts intact (that list is what the edge is based on)
        return [_reduce_nested(e, path, cut) for e in lst] if kin else lst
    return lst


def _nodes(nodes, cut: dict) -> list:
    """Graph nodes (incl. web-reported spouses and whether each is in the system)."""
    if not isinstance(nodes, list):
        return []
    return [{k: n[k] for k in _NODE_KEYS if k in n}
            for n in _cap(nodes, "nodes", cut) if isinstance(n, dict)]


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

    # The investigation runs in its OWN session: run_investigation may roll back
    # on an agent failure, which must never discard the chat turn's uncommitted
    # work in the caller's session. `session` is therefore unused here.
    try:
        async with async_session_maker() as own:
            limited = await check_investigation_rate(own, user_id, web=req.web)
            if limited:
                return {"ok": False, "error": limited}
            try:
                out = await run_investigation(own, user_id, req, _noop)
                await own.commit()
            except Exception:
                await own.rollback()
                raise
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": type(e).__name__}

    cut: dict = {}
    rel = out.get("relations") or {}
    relations = {k: _trim(rel.get(k), k, cut, kin=k == "kin")
                 for k in ("kin", "associates", "weak_associates")}
    relations["nodes"] = _nodes(rel.get("nodes"), cut)
    relations["truncated"] = cut or False
    person = out.get("person")
    people = list(out.get("people") or ([person] if person else []))
    count = int(out.get("candidate_count") or len(people))
    exact = bool(req.nid or req.phone)
    ambiguous = bool(out.get("ambiguous")) or ((not exact) and count > 1)
    notes = list(out.get("notes") or [])
    if ambiguous:
        notes.append("multiple people match this name \u2014 ask the operator which one "
                     "before treating results as about a specific person")
    shown = person.get("nid") if isinstance(person, dict) else None
    others = [{"nid": c.get("nid"), "name": c.get("name")} for c in people
              if isinstance(c, dict) and c.get("nid") != shown][:5]
    res = {
        "ok": True,
        "match": "exact" if exact else "fuzzy",
        "candidate_count": count,
        "ambiguous": ambiguous,
        "other_candidates": others,
        "person": person,
        "relations": relations,
        "web_findings": list(out.get("web_findings") or [])[:MAX_WEB],
        "spouse_candidates": out.get("spouse_candidates") or [],
        "analysis": out.get("analysis"),
        # count only: removed sentences are ungrounded and never forwarded
        "analysis_dropped_count": int(out.get("analysis_dropped_count") or 0),
        "name_collision_warning": bool(out.get("name_collision_warning")),
        "notes": notes,
        "agents_run": list(out.get("agents_run") or []),
        "confidence_note": "kin, associate and web results are inferred/unconfirmed leads",
    }
    return _strip_bytes(res)
