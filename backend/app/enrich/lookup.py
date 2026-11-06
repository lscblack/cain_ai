"""Local-first identity resolution.

Resolves a NID / phone / name by checking the SAVED database first and only
falling back to the external endpoints when the record is missing — persisting
anything newly fetched so the next lookup is a local hit. This is the single
source of truth for the "search saved DB, else use the endpoint" rule, so the
behaviour doesn't depend on the model remembering the order.
"""
from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enrich import (
    KIND_NID_BY_PHONE,
    ParcelOwnership,
    Person,
    PhoneNumber,
)
from app.enrich import endpoints as ep_mod
from app.enrich import family
from app.enrich.client import call_endpoint
from app.enrich.scraper import RateLimiter, _get_person, enrich_nid, normalize_nid


def local_phone(value: str) -> str:
    """'+250 790 110 231' / '250790110231' → '0790110231' (format stored in enrich_phones)."""
    digits = "".join(c for c in str(value or "") if c.isdigit())
    if digits.startswith("250") and len(digits) == 12:
        digits = "0" + digits[3:]
    elif len(digits) == 9 and digits[0] == "7":
        digits = "0" + digits
    return digits


class _LiveCtx:
    """Minimal context satisfying the scraper's upsert/enrich helpers for a
    one-off, interactive lookup (no ScrapeJob, no progress persistence)."""

    def __init__(self, session: AsyncSession, endpoints: dict) -> None:
        self.session = session
        self.endpoints = endpoints
        self.limiter = RateLimiter(10)
        self.calls = 0

    def bump(self, key: str, n: int = 1) -> None:  # stats sink (ignored here)
        pass

    def log(self, msg: str, level: str = "info") -> None:
        pass

    async def call(self, kind: str, params: dict):
        endpoint = self.endpoints.get(kind)
        if endpoint is None:
            return None
        await self.limiter.acquire()
        self.calls += 1
        res = await call_endpoint(endpoint, params)
        return res if res.ok else None


async def _person_view(session: AsyncSession, person: Person, *, relatives: bool = True) -> dict:
    from app.intelligence.face.crops import has_crop

    phones = (
        await session.execute(select(PhoneNumber).where(PhoneNumber.nid == person.nid))
    ).scalars().all()
    owned = (
        await session.execute(
            select(ParcelOwnership).where(ParcelOwnership.owner_nid == person.nid)
        )
    ).scalars().all()
    name = " ".join(x for x in [person.forenames, person.surnames] if x).strip() or person.nid
    fid = str(person.photo_face_id) if person.photo_face_id else None
    rel = family.relatives_out(await family.find_relatives(session, person)) if relatives else None
    return {
        "nid": person.nid,
        "name": name,
        "sex": person.sex,
        "date_of_birth": person.date_of_birth,
        "father_names": person.father_names,
        "mother_names": person.mother_names,
        "nationality": person.nationality,
        "place_of_birth": person.place_of_birth,
        "marital_status": person.marital_status,
        "province": person.province,
        "district": person.district,
        "sector": person.sector,
        "cell": person.cell,
        "village": person.village,
        "document_number": person.document_number,
        "phones": [p.msisdn for p in phones],
        "upi_count": sum(1 for o in owned if o.is_current),
        "upis": [o.upi for o in owned if o.is_current],
        "photo_face_id": str(person.photo_face_id) if person.photo_face_id else None,
        "has_photo": bool(person.photo_face_id and has_crop(str(person.photo_face_id))),
        "photo_url": f"/intelligence/face/crop/{fid}" if fid and has_crop(fid) else None,
        "relatives": rel,
    }


async def resolve_identity(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    nid: str | None = None,
    phone: str | None = None,
    name: str | None = None,
) -> dict:
    """Local-first resolve. Returns a dict with ``source`` ('local' | 'endpoint'
    | 'local(name)'), ``found``, and the matched ``person`` / ``matches``."""
    eps = {e.kind: e for e in await ep_mod.list_endpoints(session, user_id) if e.enabled}
    ctx = _LiveCtx(session, eps)

    # ── name: saved DB only (names aren't an endpoint key) ──
    if name and not nid and not phone:
        # every word must appear (in any order) across forenames + surnames
        toks = [t for t in family.name_tokens(name)]
        full = family._full_name_col()
        rows = (
            await session.execute(
                select(Person).where(and_(*[full.like(f"%{t}%") for t in toks])).limit(25)
            )
        ).scalars().all() if toks else []
        return {
            "ok": True, "source": "local(name)", "found": bool(rows),
            "matches": [await _person_view(session, p) for p in rows],
            "people": [await _person_view(session, p) for p in rows],
            "note": ("Name search runs against the saved database only — names are "
                     "not an external-endpoint key. Use a NID or phone to fetch new records."),
        }

    # ── phone: local phone → its NID, else endpoint phone→NID ──
    resolved_from_endpoint = False
    if phone and not nid:
        phone = local_phone(phone) or phone.strip()
        ph = (
            await session.execute(
                select(PhoneNumber).where(PhoneNumber.msisdn == phone.strip())
            )
        ).scalars().first()
        if ph is not None and ph.nid:
            nid = ph.nid
        else:
            res = await ctx.call(KIND_NID_BY_PHONE, {"phone": phone.strip()})
            if res is not None:
                raw = res.data.get("result") if isinstance(res.data, dict) else res.data
                nid = normalize_nid(raw) if raw else None
                resolved_from_endpoint = nid is not None
            if not nid:
                return {"ok": True, "found": False, "source": "endpoint",
                        "note": "phone not in saved DB and the phone→NID endpoint returned nothing."}

    # ── nid: local person, else endpoint person_by_nid (+persist) ──
    if nid:
        nid = normalize_nid(nid)
        person = await _get_person(session, nid)
        source = "local"
        if person is None:
            person = await enrich_nid(ctx, nid)  # calls endpoints + persists
            source = "endpoint"
        elif resolved_from_endpoint:
            source = "local"  # NID came via endpoint but the person was already saved
        if person is None:
            return {"ok": True, "found": False, "source": "endpoint",
                    "note": f"NID {nid} not in saved DB and the person endpoint returned nothing "
                            f"(is it built/enabled?).", "api_calls": ctx.calls}
        return {"ok": True, "found": True, "source": source,
                "person": (pv := await _person_view(session, person)), "people": [pv],
                "api_calls": ctx.calls}

    return {"ok": False, "error": "provide a nid, phone, or name"}
