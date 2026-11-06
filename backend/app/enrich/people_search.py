"""One search over everything the system knows about a person.

Inputs (any combination): an image, a NID, a phone number, a name. Output is a
single ranked list of people, each with their photo, record, and the parents /
siblings / children found in the saved database.

* Text inputs (nid / phone / name) go through the local-first resolver — saved DB
  first, then the registered endpoints (persisting what they return).
* An image is matched against the whole face index, which holds BOTH the photos
  from the operator's NID endpoint and the web-scraped faces. Only matches at or
  above ``MIN_MATCH_PCT`` are kept. Matches that belong to a NID record are folded
  into that person's card (with family); the rest are returned as web matches.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enrich import Person
from app.database.repositories.face_repo import FaceRepository
from app.enrich import family
from app.enrich.lookup import _person_view, local_phone, resolve_identity
from app.enrich.scraper import normalize_nid
from app.intelligence.face.crops import has_crop
from app.intelligence.face.service import detect_and_embed_async, get_face_engine

MIN_MATCH_PCT = 49.0
MAX_FOLLOW_UPS = 12  # web matches whose phones/names are chased into the DB/endpoint
MAX_EXTENDED = 5     # people that get the (heavier) extended-family walk


_WEB_FIELDS = ("face_id", "crop_url", "source_url", "page_title", "match_pct", "caption", "context",
               "names", "phones", "emails", "usernames", "titles", "orgs", "locations", "age", "sex")


def _web_photo(m: dict) -> dict:
    """Everything the face index holds for a web face (shown on the person card)."""
    return {k: m.get(k) for k in _WEB_FIELDS}


async def search_people(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    image: bytes | None = None,
    nid: str | None = None,
    phone: str | None = None,
    name: str | None = None,
    min_pct: float = MIN_MATCH_PCT,
    top_k: int = 20,
) -> dict:
    nid, phone, name = (nid or "").strip() or None, (phone or "").strip() or None, (name or "").strip() or None
    if not (image or nid or phone or name):
        return {"ok": False, "error": "provide an image, nid, phone, or name"}

    people: dict[str, dict] = {}   # nid -> card
    notes: list[str] = []
    faces_detected = 0

    # ── text identifiers ─────────────────────────────────────────────────── #
    for kw in ({"nid": nid}, {"phone": phone}, {"name": name}):
        key, value = next(iter(kw.items()))
        if not value:
            continue
        res = await resolve_identity(session, user_id, **kw)
        if res.get("note"):
            notes.append(res["note"])
        for card in res.get("people") or []:
            entry = people.setdefault(card["nid"], {**card, "match_pct": None, "matched_by": []})
            entry["matched_by"].append(key)

    # ── image → face index (ALL indexed faces: NID photos + web-scraped) ── #
    face_matches: list[dict] = []
    if image:
        engine = get_face_engine()
        if not engine.available():
            notes.append("face engine unavailable — image skipped")
        else:
            faces = await detect_and_embed_async(engine, image)
            faces_detected = len(faces)
            if not faces:
                notes.append("no face detected in the image")
            repo = FaceRepository(session)
            # Scan the WHOLE index in batches (it is far larger than fits in memory).
            best = await repo.search_all([f.embedding for f in faces], floor=min_pct / 100.0) if faces else {}
            top = sorted(best, key=lambda k: -best[k])[: max(1, top_k) * 3]
            by_id = {str(r.id): r for r in await repo.get_many(top)}
            best = {k: best[k] for k in top if k in by_id}
            seen_img: set[str] = set()
            for fid, score in sorted(best.items(), key=lambda kv: -kv[1]):
                rec = by_id[fid]
                if rec.image_hash in seen_img:   # same picture indexed twice
                    continue
                seen_img.add(rec.image_hash)
                ex = rec.extra or {}
                face_matches.append({
                    "face_id": fid, "match_pct": round(score * 100, 1),
                    "kind": "nid" if ex.get("kind") == "nid" else "web",
                    "crop_url": f"/intelligence/face/crop/{fid}" if has_crop(fid) else None,
                    "source_url": rec.source_url, "page_title": ex.get("page_title"),
                    "caption": ex.get("caption"), "context": ex.get("context"),
                    "names": ex.get("names") or [], "phones": ex.get("phones") or [],
                    "emails": ex.get("emails") or [], "usernames": ex.get("usernames") or [],
                    "locations": ex.get("locations") or [], "orgs": ex.get("orgs") or [],
                    "titles": ex.get("titles") or [], "age": ex.get("age"), "sex": ex.get("sex"),
                    "nid_hint": normalize_nid(ex.get("nid") or ex.get("national_id") or ""),
                    "linked_nid": None, "linked_by": None,
                })

    # ── link every face match to a citizen record ────────────────────────── #
    # NID photo → its NID directly. Web face → chase its phones (then an
    # unambiguous name) through the saved DB, then the endpoint.
    follow_ups = 0
    for m in face_matches:
        hits: list[tuple[str, dict]] = []
        if m["nid_hint"]:
            person = (await session.execute(
                select(Person).where(Person.nid == m["nid_hint"]))).scalar_one_or_none()
            if person is not None:
                card = people.get(person.nid) or await _person_view(session, person)
                hits.append(("face (ID photo)", card))
        elif follow_ups < MAX_FOLLOW_UPS:
            follow_ups += 1
            for ph in dict.fromkeys(local_phone(p) for p in m["phones"][:2]):
                if len(ph) == 10:
                    res = await resolve_identity(session, user_id, phone=ph)
                    hits += [("face → phone", c) for c in res.get("people") or []]
            if not hits:
                for nm in m["names"][:1]:
                    res = await resolve_identity(session, user_id, name=nm)
                    found = res.get("people") or []
                    if len(found) == 1:   # only trust an unambiguous name hit
                        hits.append(("face → name", found[0]))
        for how, card in hits[:1]:
            entry = people.setdefault(card["nid"], {**card, "match_pct": None, "matched_by": []})
            entry["match_pct"] = max(entry["match_pct"] or 0, m["match_pct"])
            entry["matched_by"] = sorted(set(entry["matched_by"]) | {how})
            if m["kind"] == "web":
                entry.setdefault("web_photos", []).append(_web_photo(m))
            m["linked_nid"], m["linked_by"] = card["nid"], how

    # Exact text hits (no face score) first, then by face match %.
    ranked = sorted(people.values(),
                    key=lambda c: -(c["match_pct"] if c["match_pct"] is not None else 101))[: max(1, top_k)]

    # Extended family (grandparents, uncles/aunts, cousins, …) for the top people.
    for card in ranked[:MAX_EXTENDED]:
        person = (await session.execute(
            select(Person).where(Person.nid == card["nid"]))).scalar_one_or_none()
        if person is not None and card.get("relatives") is not None:
            card["relatives"]["extended"] = family.extended_out(
                await family.extended_family(session, person))

    return {
        "ok": True,
        "min_match_pct": min_pct,
        "faces_detected": faces_detected,
        "people": ranked,
        # every face-index match ≥ min_pct, in order — the UI's slider
        "face_matches": face_matches[: max(1, top_k)],
        "web_matches": [m for m in face_matches if not m["linked_nid"]][: max(1, top_k)],
        "notes": notes,
        "disclaimer": "Face matches are potential matches, and family links are inferred "
                      "from recorded parent names and locations — neither is confirmed.",
    }
