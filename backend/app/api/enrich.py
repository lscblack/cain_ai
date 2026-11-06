"""Data-enrichment API: external-endpoint registry, background scrape jobs
(phone-seed / NID-seed / UPI-CSV), and browsing the resulting people, parcels,
phones and ownership history. Operator-authenticated."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.database.models.enrich import (
    ENDPOINT_KINDS,
    ExternalEndpoint,
    Parcel,
    ParcelOwnership,
    Person,
    PhoneNumber,
    ScrapeJob,
)
from app.database.models.user import User
from app.database.session import get_session
from app.enrich import endpoints as ep_mod
from app.enrich import runner
from app.enrich.client import call_endpoint
from app.enrich.csv_upi import parse_upi_csv
from app.intelligence.face.crops import has_crop

router = APIRouter(prefix="/enrich", tags=["enrich"])

_AUTH_TYPES = {"none", "bearer", "header_key", "basic"}


async def _ensure_seeded(session: AsyncSession, user_id: uuid.UUID) -> None:
    if await ep_mod.seed_defaults(session, user_id):
        await session.commit()


# ───────────────────────── endpoint registry ────────────────────────────── #
class EndpointBody(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    category: str = "general"
    description: str = ""
    kind: str = "custom"
    method: str = "GET"
    url_template: str
    query_template: dict = Field(default_factory=dict)
    headers: dict = Field(default_factory=dict)
    body_template: dict = Field(default_factory=dict)
    auth_type: str = "none"
    auth_config: dict = Field(default_factory=dict)
    result_path: str = ""
    image_keys: list[str] = Field(default_factory=list)
    enabled: bool = True
    rate_limit_per_min: int = 10
    sample_response: str = ""


def _validate_endpoint(body: EndpointBody) -> None:
    if body.kind not in ENDPOINT_KINDS:
        raise HTTPException(422, f"invalid kind; valid: {list(ENDPOINT_KINDS)}")
    if body.auth_type not in _AUTH_TYPES:
        raise HTTPException(422, f"invalid auth_type; valid: {sorted(_AUTH_TYPES)}")
    if body.method.upper() not in ("GET", "POST"):
        raise HTTPException(422, "method must be GET or POST")


@router.get("/endpoints")
async def list_endpoints(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _ensure_seeded(session, operator.id)
    rows = await ep_mod.list_endpoints(session, operator.id)
    return {"endpoints": [ep_mod.endpoint_out(e) for e in rows], "kinds": list(ENDPOINT_KINDS)}


@router.post("/endpoints", status_code=201)
async def create_endpoint(
    body: EndpointBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _validate_endpoint(body)
    if await ep_mod.get_by_slug(session, operator.id, body.slug):
        raise HTTPException(409, f"an endpoint with slug '{body.slug}' already exists")
    row = ExternalEndpoint(user_id=operator.id, **body.model_dump())
    row.method = row.method.upper()
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return ep_mod.endpoint_out(row)


async def _get_endpoint_or_404(
    ep_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession
) -> ExternalEndpoint:
    row = await session.get(ExternalEndpoint, ep_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(404, "endpoint_not_found")
    return row


@router.put("/endpoints/{ep_id}")
async def update_endpoint(
    ep_id: uuid.UUID,
    body: EndpointBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _validate_endpoint(body)
    row = await _get_endpoint_or_404(ep_id, operator.id, session)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    row.method = row.method.upper()
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return ep_mod.endpoint_out(row)


@router.delete("/endpoints/{ep_id}", status_code=204)
async def delete_endpoint(
    ep_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_endpoint_or_404(ep_id, operator.id, session)
    await session.delete(row)
    await session.flush()


class TestBody(BaseModel):
    params: dict = Field(default_factory=dict)  # e.g. {"nid": "..."} / {"phone": "..."} / {"upi": "..."}


@router.post("/endpoints/{ep_id}/test")
async def test_endpoint(
    ep_id: uuid.UUID,
    body: TestBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await _get_endpoint_or_404(ep_id, operator.id, session)
    res = await call_endpoint(row, body.params)
    # Don't ship base64 image blobs back — just report which keys were found.
    data = res.data
    if isinstance(data, dict):
        data = {k: (f"<image {len(v)} chars>" if k in (row.image_keys or []) and isinstance(v, str) else v)
                for k, v in data.items()}
    return {
        "ok": res.ok, "status": res.status, "url": res.url, "error": res.error,
        "data": data, "images_found": sorted(res.images.keys()),
    }


@router.post("/endpoints/seed")
async def reseed(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    created = await ep_mod.seed_defaults(session, operator.id)
    await session.flush()
    return {"created": created}


# ───────────────────────── scrape jobs ──────────────────────────────────── #
def _job_out(j: ScrapeJob) -> dict:
    return {
        "id": str(j.id), "kind": j.kind, "status": j.status,
        "total": j.total, "processed": j.processed, "stats": j.stats,
        "last_message": j.last_message, "rate_limit_per_min": j.rate_limit_per_min,
        "running": runner.is_running(j.id),
        "started_at": j.started_at, "finished_at": j.finished_at,
        "created_at": j.created_at.isoformat() if j.created_at else None,
    }


class PhoneSeedBody(BaseModel):
    phones: list[str] = Field(min_length=1)
    rate_limit_per_min: int = 10


class NidSeedBody(BaseModel):
    nids: list[str] = Field(min_length=1)
    rate_limit_per_min: int = 10


async def _launch(session: AsyncSession, user_id: uuid.UUID, kind: str,
                  params: dict, rate: int) -> ScrapeJob:
    await _ensure_seeded(session, user_id)
    job = ScrapeJob(user_id=user_id, kind=kind, status="queued", params=params,
                    rate_limit_per_min=max(1, min(int(rate or 10), 120)), stats={})
    session.add(job)
    await session.flush()
    await session.refresh(job)
    await session.commit()  # persist before the background task loads it
    await runner.start_job(job.id, user_id)
    return job


@router.post("/jobs/phone", status_code=201)
async def start_phone_job(
    body: PhoneSeedBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    job = await _launch(session, operator.id, "phone_seed",
                        {"phones": body.phones}, body.rate_limit_per_min)
    return _job_out(job)


@router.post("/jobs/nid", status_code=201)
async def start_nid_job(
    body: NidSeedBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    job = await _launch(session, operator.id, "nid_seed",
                        {"nids": body.nids}, body.rate_limit_per_min)
    return _job_out(job)


@router.post("/jobs/csv", status_code=201)
async def start_csv_job(
    file: UploadFile = File(...),
    rate_limit_per_min: int = Form(default=10),
    expand_owner_parcels: bool = Form(default=False),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    content = await file.read()
    rows, errors = parse_upi_csv(content)
    if not rows:
        raise HTTPException(422, {"message": "no usable rows in CSV", "errors": errors[:20]})
    job = await _launch(
        session, operator.id, "csv_upi",
        {"rows": rows, "csv_name": file.filename, "parse_errors": errors[:50],
         "expand_owner_parcels": expand_owner_parcels},
        rate_limit_per_min,
    )
    out = _job_out(job)
    out["parsed_rows"] = len(rows)
    out["parse_errors"] = errors[:20]
    return out


@router.get("/jobs")
async def list_jobs(
    limit: int = 50,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.execute(
            select(ScrapeJob).where(ScrapeJob.user_id == operator.id)
            .order_by(ScrapeJob.created_at.desc()).limit(max(1, min(limit, 200)))
        )
    ).scalars().all()
    return [_job_out(j) for j in rows]


async def _get_job_or_404(job_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession) -> ScrapeJob:
    j = await session.get(ScrapeJob, job_id)
    if j is None or j.user_id != user_id:
        raise HTTPException(404, "job_not_found")
    return j


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    j = await _get_job_or_404(job_id, operator.id, session)
    out = _job_out(j)
    out["log"] = (j.log or [])[-60:]
    return out


@router.post("/jobs/{job_id}/{action}")
async def control_job(
    job_id: uuid.UUID,
    action: str,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    j = await _get_job_or_404(job_id, operator.id, session)
    if action == "pause":
        ok = runner.pause_job(job_id)
        if ok:
            j.status = "paused"; session.add(j); await session.flush()
    elif action == "resume":
        if runner.is_running(job_id):
            ok = runner.resume_job(job_id)
        else:
            # task gone (e.g. after restart) → relaunch; idempotent flows make this safe
            await runner.start_job(job_id, operator.id)
            ok = True
        if ok:
            j.status = "running"; session.add(j); await session.flush()
    elif action == "cancel":
        ok = runner.cancel_job(job_id)
        if not ok:
            j.status = "cancelled"; session.add(j); await session.flush()
    else:
        raise HTTPException(422, "action must be pause | resume | cancel")
    return {"ok": True, "action": action, "job": _job_out(await _get_job_or_404(job_id, operator.id, session))}


# ───────────────────────── browse results ───────────────────────────────── #
def _person_out(p: Person) -> dict:
    name = " ".join(x for x in [p.forenames, p.surnames] if x).strip() or p.nid
    return {
        "id": str(p.id), "nid": p.nid, "name": name,
        "surnames": p.surnames, "forenames": p.forenames,
        "sex": p.sex, "date_of_birth": p.date_of_birth,
        "father_names": p.father_names, "mother_names": p.mother_names,
        "nationality": p.nationality, "civil_status": p.civil_status,
        "province": p.province, "district": p.district, "sector": p.sector,
        "cell": p.cell, "village": p.village, "place_of_birth": p.place_of_birth,
        "document_number": p.document_number, "date_of_issue": p.date_of_issue,
        "date_of_expiry": p.date_of_expiry,
        "photo_face_id": str(p.photo_face_id) if p.photo_face_id else None,
        "crop_url": (f"/intelligence/face/crop/{p.photo_face_id}"
                     if p.photo_face_id and has_crop(str(p.photo_face_id)) else None),
        "last_scraped_at": p.last_scraped_at,
    }


@router.get("/stats")
async def stats(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    async def count(model) -> int:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()
    return {
        "persons": await count(Person),
        "parcels": await count(Parcel),
        "phones": await count(PhoneNumber),
        "ownership_records": await count(ParcelOwnership),
        "jobs": (await session.execute(
            select(func.count()).select_from(ScrapeJob).where(ScrapeJob.user_id == operator.id)
        )).scalar_one(),
    }


@router.get("/persons")
async def list_persons(
    q: str | None = None,
    limit: int = 50,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    stmt = select(Person)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Person.nid.ilike(like), Person.surnames.ilike(like),
                              Person.forenames.ilike(like), Person.district.ilike(like)))
    stmt = stmt.order_by(Person.updated_at.desc()).limit(max(1, min(limit, 200)))
    rows = (await session.execute(stmt)).scalars().all()
    return [_person_out(p) for p in rows]


@router.get("/persons/{nid}")
async def get_person(
    nid: str,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    p = (await session.execute(select(Person).where(Person.nid == nid))).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "person_not_found")
    phones = (await session.execute(
        select(PhoneNumber).where(PhoneNumber.nid == nid))).scalars().all()
    owned = (await session.execute(
        select(ParcelOwnership).where(ParcelOwnership.owner_nid == nid)
        .order_by(ParcelOwnership.created_at.desc()))).scalars().all()
    out = _person_out(p)
    out["phones"] = [{"msisdn": ph.msisdn, "mno": ph.mno, "service_period": ph.service_period}
                     for ph in phones]
    out["parcels"] = [{"upi": o.upi, "is_current": o.is_current, "start_date": o.start_date,
                       "end_date": o.end_date, "source": o.source} for o in owned]
    out["upi_count"] = sum(1 for o in owned if o.is_current)
    out["raw"] = p.raw
    return out


def _parcel_out(p: Parcel) -> dict:
    return {
        "id": str(p.id), "upi": p.upi, "province": p.province, "district": p.district,
        "sector": p.sector, "cell": p.cell, "village": p.village,
        "land_use": p.land_use, "size": p.size, "current_owner_nid": p.current_owner_nid,
        "last_scraped_at": p.last_scraped_at,
    }


@router.get("/parcels")
async def list_parcels(
    q: str | None = None,
    limit: int = 50,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    stmt = select(Parcel)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Parcel.upi.ilike(like), Parcel.district.ilike(like),
                              Parcel.current_owner_nid.ilike(like)))
    stmt = stmt.order_by(Parcel.updated_at.desc()).limit(max(1, min(limit, 200)))
    rows = (await session.execute(stmt)).scalars().all()
    return [_parcel_out(p) for p in rows]


@router.get("/parcels/{upi:path}")
async def get_parcel(
    upi: str,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    p = (await session.execute(select(Parcel).where(Parcel.upi == upi))).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "parcel_not_found")
    history = (await session.execute(
        select(ParcelOwnership).where(ParcelOwnership.upi == upi)
        .order_by(ParcelOwnership.is_current.desc(), ParcelOwnership.created_at.desc()))).scalars().all()
    out = _parcel_out(p)
    out["ownership_history"] = [{
        "owner_nid": o.owner_nid, "is_current": o.is_current, "start_date": o.start_date,
        "end_date": o.end_date, "transaction_type": o.transaction_type,
        "sale_price": o.sale_price, "source": o.source,
    } for o in history]
    return out


@router.get("/person/by-face/{face_id}")
async def person_by_face(
    face_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Resolve a face in the index to its NID person record (used to enrich face
    search results with full identity info)."""
    p = (await session.execute(
        select(Person).where(Person.photo_face_id == face_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "no_person_for_face")
    return await get_person(p.nid, operator, session)


# ───────────────────────── people search + family ───────────────────────── #
_IMG_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}


@router.post("/people/search")
async def people_search(
    file: UploadFile | None = File(default=None),
    nid: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    name: str | None = Form(default=None),
    min_pct: float = Form(default=49.0),
    top_k: int = Form(default=20),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Search by image, NID, phone and/or name. Face matches below ``min_pct`` are
    dropped; each person comes back with photo + parents / siblings / children."""
    from app.enrich.people_search import search_people

    image = None
    if file is not None:
        if file.content_type not in _IMG_TYPES:
            raise HTTPException(status_code=415, detail="unsupported_image_type")
        image = await file.read()
        if len(image) > 12 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="image_too_large")
    await _ensure_seeded(session, operator.id)
    res = await search_people(session, operator.id, image=image, nid=nid, phone=phone,
                             name=name, min_pct=max(0.0, min(min_pct, 100.0)), top_k=top_k)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "bad_request"))
    return res


@router.get("/family/{nid}")
async def family_tree(
    nid: str,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Family tree (nodes + edges) for a saved person, inferred from parent names."""
    from app.enrich import family
    from app.enrich.scraper import normalize_nid

    person = (await session.execute(
        select(Person).where(Person.nid == normalize_nid(nid)))).scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    rel = await family.find_relatives(session, person)
    ext = await family.extended_family(session, person)
    tree = family.add_extended_to_tree(family.build_tree(person, rel), ext)
    return {**tree, "relatives": {**family.relatives_out(rel), "extended": family.extended_out(ext)},
            "note": "Inferred from recorded parent names and locations — not confirmed kinship."}


@router.get("/web-face/{face_id}")
async def web_face_detail(
    face_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Everything crawled around one web face: the face record, the page it was
    found on (title, full description, emails, phones, usernames, structured
    meta, crawl dates), the source, the original image, other faces on the same
    page, other pages crawled on the same site, and other photos of the same
    person across the whole index."""
    from app.database.models.face import Face
    from app.database.models.source import Image, Page, Source
    from app.intelligence.face.index_cache import get_index_cache

    face = await session.get(Face, face_id)
    if face is None:
        raise HTTPException(status_code=404, detail="face_not_found")
    ex = face.extra or {}

    def crop(fid) -> str | None:
        return f"/intelligence/face/crop/{fid}" if has_crop(str(fid)) else None

    page = (await session.execute(
        select(Page).where(Page.url == face.source_url).order_by(Page.last_crawled_at.desc().nullslast())
    )).scalars().first() if face.source_url else None
    source = await session.get(Source, page.source_id) if page else None
    image = (await session.execute(select(Image).where(Image.image_hash == face.image_hash))).scalars().first()

    same_page = []
    if face.source_url:
        rows = (await session.execute(
            select(Face).where(Face.source_url == face.source_url, Face.id != face.id).limit(24))).scalars().all()
        same_page = [{"face_id": str(r.id), "crop_url": crop(r.id),
                      "names": (r.extra or {}).get("names") or []} for r in rows]

    site_pages = []
    if source is not None:
        rows = (await session.execute(
            select(Page).where(Page.source_id == source.id, Page.url != (face.source_url or ""))
            .order_by(Page.faces_found.desc()).limit(20))).scalars().all()
        site_pages = [{"url": p.url, "title": p.title, "faces_found": p.faces_found,
                       "emails": p.emails, "phones": p.phones} for p in rows]

    # Other photos of the same person anywhere in the index (≥ 50% similar).
    appearances = []
    if face.embedding:
        best = await get_index_cache().search(session, [list(face.embedding)], floor=0.50)
        best.pop(str(face.id), None)
        top = sorted(best, key=lambda k: -best[k])[:16]
        recs = {str(r.id): r for r in (await session.execute(
            select(Face).where(Face.id.in_([uuid.UUID(t) for t in top])))).scalars().all()} if top else {}
        for fid in top:
            r = recs.get(fid)
            if r is None:
                continue
            rx = r.extra or {}
            appearances.append({"face_id": fid, "crop_url": crop(fid), "match_pct": round(best[fid] * 100, 1),
                                "kind": "nid" if rx.get("kind") == "nid" else "web",
                                "source_url": r.source_url, "page_title": rx.get("page_title"),
                                "names": rx.get("names") or [], "nid": rx.get("nid")})

    return {
        "face": {
            "face_id": str(face.id), "crop_url": crop(face.id), "source_url": face.source_url,
            "image_url": ex.get("image_url") or (image.image_url if image else None),
            "image_size": [image.width, image.height] if image and image.width else None,
            "detected_at": face.created_at.isoformat() if face.created_at else None,
            "quality": face.quality, "det_score": face.det_score,
            **{k: ex.get(k) for k in ("page_title", "caption", "alt", "context", "age", "sex")},
            **{k: ex.get(k) or [] for k in ("names", "phones", "emails", "usernames",
                                            "titles", "orgs", "locations")},
        },
        "page": None if page is None else {
            "url": page.url, "title": page.title, "description": page.description,
            "emails": page.emails, "phones": page.phones, "usernames": page.usernames,
            "meta": page.meta, "http_status": page.http_status,
            "images_found": page.images_found, "faces_found": page.faces_found,
            "last_crawled_at": page.last_crawled_at, "last_changed_at": page.last_changed_at,
        },
        "source": None if source is None else {
            "name": source.name, "domain": source.domain, "base_url": source.base_url,
            "category": source.category, "last_crawled_at": source.last_crawled_at,
        },
        "same_page_faces": same_page,
        "site_pages": site_pages,
        "appearances": appearances,
    }
