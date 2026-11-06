"""Index a person's NID photo into the face corpus, linked back to the Person.

The person's identity (NID, names, phones, bio) is stored in the Face row's
``extra`` so the existing 1:N face search surfaces it automatically — searching
by an uploaded image returns the matching NID record with all its information.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enrich import Person
from app.database.models.face import Face
from app.database.repositories.face_repo import FaceRepository
from app.intelligence.face.crops import save_crop
from app.intelligence.face.service import detect_and_embed_async, get_face_engine


def _decode_image(b64: str) -> bytes | None:
    if not b64:
        return None
    raw = b64.strip()
    if raw.startswith("data:"):  # strip a data-URL prefix if present
        _, _, raw = raw.partition(",")
    try:
        return base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError):
        return None


def _person_extra(person: Person, phones: list[str] | None) -> dict:
    """Identity payload stored on the Face row so search results carry it."""
    full_name = " ".join(
        p for p in [person.forenames, person.surnames] if p
    ).strip() or (person.surnames or person.forenames or person.nid)
    names = [n for n in {full_name, person.surnames, person.forenames} if n]
    location = ", ".join(
        p for p in [person.village, person.cell, person.sector, person.district, person.province] if p
    )
    return {
        "kind": "nid",
        "nid": person.nid,
        "national_id": person.nid,
        "person_id": str(person.id),
        "names": names,
        "phones": list(phones or []),
        "locations": [location] if location else [],
        "sex": person.sex,
        "age": None,
        "caption": full_name,
        "context": f"National ID {person.nid}",
        "bio": {
            "date_of_birth": person.date_of_birth,
            "father_names": person.father_names,
            "mother_names": person.mother_names,
            "place_of_birth": person.place_of_birth,
            "nationality": person.nationality,
            "document_number": person.document_number,
        },
    }


async def index_person_photo(
    session: AsyncSession,
    *,
    person: Person,
    photo_b64: str,
    phones: list[str] | None = None,
) -> uuid.UUID | None:
    """Detect + embed the NID photo and store a Face linked to the person.

    Returns the new (or existing) face id, or ``None`` if the engine is
    unavailable or no face is found. Re-indexing the same image replaces the
    prior NID face for that person so there is one current photo per person.
    """
    data = _decode_image(photo_b64)
    if not data:
        return None
    try:
        engine = get_face_engine()
        if not engine.available():
            return None
        faces = await detect_and_embed_async(engine, data)
    except Exception:  # noqa: BLE001 — never let face indexing break a scrape
        return None
    if not faces:
        return None

    # Best face = highest quality.
    f = max(faces, key=lambda x: x.quality)
    image_hash = hashlib.sha256(data).hexdigest()
    crop_hash = hashlib.sha256(
        (image_hash + ":" + ",".join(str(b) for b in f.bbox)).encode()
    ).hexdigest()
    extra = {**(f.extra or {}), **_person_extra(person, phones)}

    repo = FaceRepository(session)
    rec = await repo.add(
        Face(
            investigation_id=None,
            source_url=f"nid:{person.nid}",
            image_hash=image_hash,
            face_crop_hash=crop_hash,
            bbox=f.bbox,
            det_score=f.det_score,
            quality=f.quality,
            model=engine.model_name,
            model_version=engine.model_version,
            embedding_dim=len(f.embedding),
            embedding=f.embedding,
            extra=extra,
        )
    )
    await session.flush()
    try:
        save_crop(data, f.bbox, str(rec.id))
    except Exception:  # noqa: BLE001
        pass
    return rec.id
